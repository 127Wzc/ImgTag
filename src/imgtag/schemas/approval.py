"""审批相关 Schema"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .base import BaseSchema, PaginatedResponse


class ApprovalCreate(BaseModel):
    type: str = Field(..., description="审批类型")
    target_type: Optional[str] = None
    target_ids: Optional[List[int]] = None
    payload: Dict[str, Any] = Field(..., description="操作详情")


class ApprovalResponse(BaseSchema):
    """审批响应模型"""
    id: int
    type: str
    status: str
    requester_id: Optional[int] = None
    requester_name: Optional[str] = None
    target_type: Optional[str] = None
    target_ids: Optional[List[int]] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    reviewer_id: Optional[int] = None
    review_comment: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


# 审批列表响应 - 直接使用通用分页基类
ApprovalList = PaginatedResponse[ApprovalResponse]


class ApprovalAction(BaseModel):
    comment: Optional[str] = None


class BatchApproveRequest(BaseModel):
    approval_ids: List[int] = Field(..., description="要批准的审批 ID 列表")
    comment: Optional[str] = None
