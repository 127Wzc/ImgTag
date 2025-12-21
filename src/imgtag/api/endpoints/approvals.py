#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
审批管理 API 端点
"""

from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends

from imgtag.schemas.approval import (
    ApprovalResponse, 
    ApprovalList, 
    ApprovalAction, 
    BatchApproveRequest
)
from imgtag.api.endpoints.auth import get_current_user, require_admin
from imgtag.db import db
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=ApprovalList)
async def get_pending_approvals(
    limit: int = 50,
    offset: int = 0,
    admin: Dict = Depends(require_admin)
):
    """获取待审批列表（仅管理员）"""
    result = db.get_pending_approvals(limit, offset)
    return result


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: int,
    admin: Dict = Depends(require_admin)
):
    """获取审批详情"""
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    return approval


@router.post("/{approval_id}/approve", response_model=Dict[str, Any])
async def approve_request(
    approval_id: int,
    data: ApprovalAction,
    admin: Dict = Depends(require_admin)
):
    """批准审批请求"""
    # 获取审批详情
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    
    if approval["status"] != "pending":
        raise HTTPException(status_code=400, detail="该审批已处理")
    
    # 执行审批操作
    success = await execute_approval(approval)
    if not success:
        raise HTTPException(status_code=500, detail="执行审批操作失败")
    
    # 更新审批状态
    db.approve_request(approval_id, admin["id"], data.comment)
    
    # 记录审计日志
    db.add_audit_log(
        user_id=admin["id"],
        action="approve_request",
        target_type="approval",
        target_id=approval_id,
        new_value={"status": "approved", "comment": data.comment}
    )
    
    return {"message": "已批准"}


@router.post("/{approval_id}/reject", response_model=Dict[str, Any])
async def reject_request(
    approval_id: int,
    data: ApprovalAction,
    admin: Dict = Depends(require_admin)
):
    """拒绝审批请求"""
    approval = db.get_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="审批记录不存在")
    
    if approval["status"] != "pending":
        raise HTTPException(status_code=400, detail="该审批已处理")
    
    db.reject_request(approval_id, admin["id"], data.comment)
    
    # 记录审计日志
    db.add_audit_log(
        user_id=admin["id"],
        action="reject_request",
        target_type="approval",
        target_id=approval_id,
        new_value={"status": "rejected", "comment": data.comment}
    )
    
    return {"message": "已拒绝"}


@router.post("/batch-approve", response_model=Dict[str, Any])
async def batch_approve(
    data: BatchApproveRequest,
    admin: Dict = Depends(require_admin)
):
    """批量批准审批请求"""
    approved_count = 0
    failed_ids = []
    
    for approval_id in data.approval_ids:
        try:
            approval = db.get_approval(approval_id)
            if not approval or approval["status"] != "pending":
                failed_ids.append(approval_id)
                continue
            
            success = await execute_approval(approval)
            if success:
                db.approve_request(approval_id, admin["id"], data.comment)
                approved_count += 1
            else:
                failed_ids.append(approval_id)
        except Exception as e:
            logger.error(f"批量审批失败 ID {approval_id}: {str(e)}")
            failed_ids.append(approval_id)
    
    # 记录审计日志
    db.add_audit_log(
        user_id=admin["id"],
        action="batch_approve",
        target_type="approval",
        new_value={
            "approved_ids": [i for i in data.approval_ids if i not in failed_ids],
            "failed_ids": failed_ids
        }
    )
    
    return {
        "message": f"已批准 {approved_count} 项",
        "approved_count": approved_count,
        "failed_ids": failed_ids
    }


async def execute_approval(approval: Dict) -> bool:
    """执行审批操作"""
    approval_type = approval["type"]
    payload = approval["payload"]
    
    try:
        if approval_type == "add_tags":
            # 批量添加标签
            image_ids = payload.get("image_ids", [])
            tags = payload.get("tags", [])
            for image_id in image_ids:
                image = db.get_image(image_id)
                if image:
                    current_tags = image.get("tags", [])
                    new_tags = list(set(current_tags + tags))
                    db.update_image(image_id=image_id, tags=new_tags)
            return True
        
        elif approval_type == "update_tags":
            image_id = payload.get("image_id")
            new_tags = payload.get("new_tags", [])
            db.update_image(image_id=image_id, tags=new_tags)
            return True
        
        elif approval_type == "update_description":
            image_id = payload.get("image_id")
            description = payload.get("description")
            db.update_image(image_id=image_id, description=description)
            return True
        
        elif approval_type == "delete_image":
            image_ids = payload.get("image_ids", [])
            for image_id in image_ids:
                db.delete_image(image_id)
            return True
        
        else:
            logger.warning(f"未知的审批类型: {approval_type}")
            return False
    
    except Exception as e:
        logger.error(f"执行审批操作失败: {str(e)}")
        return False
