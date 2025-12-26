#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
审批管理 API 端点
"""

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
    limit: int = 50,
    offset: int = 0,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """获取待审批列表（仅管理员）"""
    approvals, total = await approval_repository.get_pending(
        session, limit=limit, offset=offset
    )
    return {
        "approvals": [_approval_to_dict(a) for a in approvals],
        "total": total,
    }


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
    success = await execute_approval(session, approval)
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
    
    for approval_id in data.approval_ids:
        try:
            approval = await approval_repository.get_with_relations(session, approval_id)
            if not approval or approval.status != "pending":
                failed_ids.append(approval_id)
                continue
            
            success = await execute_approval(session, approval)
            if success:
                await approval_repository.approve(session, approval, admin["id"], data.comment)
                approved_count += 1
            else:
                failed_ids.append(approval_id)
        except Exception as e:
            logger.error(f"批量审批失败 ID {approval_id}: {str(e)}")
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
    
    return {
        "message": f"已批准 {approved_count} 项",
        "approved_count": approved_count,
        "failed_ids": failed_ids,
    }


async def execute_approval(session: AsyncSession, approval) -> bool:
    """执行审批操作"""
    approval_type = approval.type
    payload = approval.payload
    
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
