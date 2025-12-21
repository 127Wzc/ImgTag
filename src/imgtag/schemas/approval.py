"""审批相关 Schema"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class ApprovalCreate(BaseModel):
    type: str = Field(..., description="审批类型")
    target_type: Optional[str] = None
    target_ids: Optional[List[int]] = None
    payload: Dict[str, Any] = Field(..., description="操作详情")


class ApprovalResponse(BaseModel):
    id: int
    type: str
    status: str
    requester_id: Optional[int] = None
    requester_name: Optional[str] = None
    target_type: Optional[str] = None
    target_ids: Optional[List[int]] = None
    payload: Dict[str, Any]
    reviewer_id: Optional[int] = None
    review_comment: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApprovalList(BaseModel):
    approvals: List[ApprovalResponse]
    total: int
    limit: int
    offset: int


class ApprovalAction(BaseModel):
    comment: Optional[str] = None


class BatchApproveRequest(BaseModel):
    approval_ids: List[int] = Field(..., description="要批准的审批 ID 列表")
    comment: Optional[str] = None
