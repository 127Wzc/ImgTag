"""审批相关 Schema"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

from .base import BaseSchema, PaginatedResponse


class ApprovalPreview(BaseModel):
    """审批列表的图片预览信息（用于减少前端 N+1 请求）。"""

    image_id: int = Field(..., description="图片 ID")
    image_url: str = Field(..., description="图片访问 URL（动态生成）")
    uploaded_by: Optional[int] = Field(default=None, description="上传者用户ID")
    uploaded_by_username: Optional[str] = Field(default=None, description="上传者用户名")


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
    preview: Optional[ApprovalPreview] = Field(default=None, description="图片预览信息（可选）")
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
