#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
审批管理 API 端点
"""

import asyncio
from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.schemas.approval import (
    ApprovalResponse, 
    ApprovalList, 
    ApprovalAction, 
    BatchApproveRequest
)
from imgtag.api.endpoints.auth import get_current_user, require_admin
from imgtag.core.logging_config import get_logger
from imgtag.db.database import get_async_session
from imgtag.db.repositories import (
    approval_repository,
    audit_log_repository,
    image_repository,
)
from imgtag.services.suggestion_service import SUGGEST_IMAGE_UPDATE_TYPE, suggestion_service
from imgtag.services.task_queue import task_queue
from imgtag.utils.pagination import PageParams

logger = get_logger(__name__)

router = APIRouter()


def _approval_to_dict(approval) -> dict:
    """Convert Approval model to response dict."""
    return {
        "id": approval.id,
        "type": approval.type,
        "status": approval.status,
        "requester_id": approval.requester_id,
        "target_type": approval.target_type,
        "target_ids": approval.target_ids,
        "payload": approval.payload,
        "reviewer_id": approval.reviewer_id,
        "review_comment": approval.review_comment,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
    }


@router.get("/", response_model=ApprovalList)
async def get_pending_approvals(
    page: int = 1,
    size: int = 50,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """获取待审批列表（仅管理员）"""
    approvals, total = await approval_repository.get_pending(
        session,
        types=[SUGGEST_IMAGE_UPDATE_TYPE],
        limit=size,
        offset=(page - 1) * size,
    )
    
    params = PageParams(page=page, size=size)
    return params.paginate([_approval_to_dict(a) for a in approvals], total)


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: int,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """获取审批详情"""
    approval = await approval_repository.get_with_relations(session, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    return _approval_to_dict(approval)


@router.post("/{approval_id}/approve", response_model=Dict[str, Any])
async def approve_request(
    approval_id: int,
    data: ApprovalAction,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """批准审批请求"""
    approval = await approval_repository.get_with_relations(session, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="该审批已处理")
    
    # 执行审批操作
    try:
        success = await execute_approval(session, approval)
    except Exception as e:
        logger.error(f"执行审批操作异常: approval_id={approval_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"执行审批操作失败: {e}")
    if not success:
        raise HTTPException(status_code=500, detail="执行审批操作失败")
    
    # 更新审批状态
    await approval_repository.approve(session, approval, admin["id"], data.comment)
    
    # 记录审计日志
    await audit_log_repository.add_log(
        session,
        user_id=admin["id"],
        action="approve_request",
        target_type="approval",
        target_id=approval_id,
        new_value={"status": "approved", "comment": data.comment},
    )

    # 确保修改已提交后再触发异步任务，避免读到旧数据
    await session.commit()

    # 建议落地后触发向量重建（不走视觉分析）
    if approval.type == SUGGEST_IMAGE_UPDATE_TYPE:
        image_id = None
        try:
            if isinstance(approval.payload, dict):
                image_id = approval.payload.get("image_id")
            if not image_id and approval.target_ids:
                image_id = approval.target_ids[0]
            if image_id:
                asyncio.create_task(
                    task_queue.add_tasks([int(image_id)], task_type="rebuild_vector")
                )
        except Exception as e:
            logger.warning(f"触发向量重建失败: approval_id={approval_id}, image_id={image_id}, error={e}")
    
    return {"message": "已批准"}


@router.post("/{approval_id}/reject", response_model=Dict[str, Any])
async def reject_request(
    approval_id: int,
    data: ApprovalAction,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """拒绝审批请求"""
    approval = await approval_repository.get_with_relations(session, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail="该审批已处理")
    
    await approval_repository.reject(session, approval, admin["id"], data.comment)
    
    # 记录审计日志
    await audit_log_repository.add_log(
        session,
        user_id=admin["id"],
        action="reject_request",
        target_type="approval",
        target_id=approval_id,
        new_value={"status": "rejected", "comment": data.comment},
    )
    
    return {"message": "已拒绝"}


@router.post("/batch-approve", response_model=Dict[str, Any])
async def batch_approve(
    data: BatchApproveRequest,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """批量批准审批请求"""
    approved_count = 0
    failed_ids = []
    rebuild_image_ids: list[int] = []
    
    for approval_id in data.approval_ids:
        try:
            # 每条审批使用 SAVEPOINT 保证原子性：
            # - 单条失败不会污染后续审批处理
            # - 单条失败时自动回滚到 savepoint，避免“部分落地修改”被最终 commit
            approved_this = False
            async with session.begin_nested():
                approval = await approval_repository.get_with_relations(session, approval_id)
                if not approval or approval.status != "pending":
                    failed_ids.append(approval_id)
                else:
                    success = await execute_approval(session, approval)
                    if not success:
                        failed_ids.append(approval_id)
                        raise ValueError(f"未知或不支持的审批类型: {approval.type}")

                    await approval_repository.approve(session, approval, admin["id"], data.comment)

                    # 建议落地后触发向量重建
                    if approval.type == SUGGEST_IMAGE_UPDATE_TYPE:
                        if isinstance(approval.payload, dict) and approval.payload.get("image_id"):
                            rebuild_image_ids.append(int(approval.payload["image_id"]))
                        elif approval.target_ids:
                            rebuild_image_ids.append(int(approval.target_ids[0]))

                    approved_this = True

            if approved_this:
                approved_count += 1
        except Exception as e:
            logger.error(f"批量审批失败 ID {approval_id}: {str(e)}")
            if approval_id not in failed_ids:
                failed_ids.append(approval_id)
    
    # 记录审计日志
    await audit_log_repository.add_log(
        session,
        user_id=admin["id"],
        action="batch_approve",
        target_type="approval",
        new_value={
            "approved_ids": [i for i in data.approval_ids if i not in failed_ids],
            "failed_ids": failed_ids,
        },
    )

    # 确保审批与落地已提交后再触发向量重建
    await session.commit()
    if rebuild_image_ids:
        # 去重，避免重复入队导致无意义的重复计算
        rebuild_image_ids = list(dict.fromkeys(rebuild_image_ids))
        try:
            asyncio.create_task(
                task_queue.add_tasks(rebuild_image_ids, task_type="rebuild_vector")
            )
        except Exception as e:
            logger.warning(f"批量触发向量重建失败: {e}")
    
    return {
        "message": f"已批准 {approved_count} 项",
        "approved_count": approved_count,
        "failed_ids": failed_ids,
    }


async def execute_approval(session: AsyncSession, approval) -> bool:
    """执行审批操作"""
    approval_type = approval.type
    payload = approval.payload if isinstance(approval.payload, dict) else {}
    
    # 修改建议审批：必须保证失败时能回滚（由上层 savepoint 负责），因此这里不吞异常
    if approval_type == SUGGEST_IMAGE_UPDATE_TYPE:
        await suggestion_service.apply_image_update_suggestion(session, approval=approval)
        return True

    try:
        if approval_type == "add_tags":
            # 批量添加标签
            image_ids = payload.get("image_ids", [])
            tags = payload.get("tags", [])
            for image_id in image_ids:
                image = await image_repository.get_with_tags(session, image_id)
                if image:
                    current_tags = [it.tag.name for it in image.image_tags] if image.image_tags else []
                    new_tags = list(set(current_tags + tags))
                    # Note: Would need to implement tag update via repository
                    # This is a placeholder for the actual implementation
                    pass
            return True
        
        elif approval_type == "update_tags":
            image_id = payload.get("image_id")
            # new_tags = payload.get("new_tags", [])
            # Implementation needed
            return True
        
        elif approval_type == "update_description":
            image_id = payload.get("image_id")
            description = payload.get("description")
            image = await image_repository.get_by_id(session, image_id)
            if image:
                await image_repository.update_image(
                    session, image, description=description
                )
            return True
        
        elif approval_type == "delete_image":
            image_ids = payload.get("image_ids", [])
            for image_id in image_ids:
                image = await image_repository.get_by_id(session, image_id)
                if image:
                    await image_repository.delete(session, image)
            return True
        
        else:
            logger.warning(f"未知的审批类型: {approval_type}")
            return False
    
    except Exception as e:
        logger.error(f"执行审批操作失败: {str(e)}")
        return False
