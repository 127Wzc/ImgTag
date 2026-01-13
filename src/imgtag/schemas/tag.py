from typing import Optional
from datetime import datetime
from pydantic import BaseModel

from .base import BaseSchema, PaginatedResponse


class TagBase(BaseModel):
    name: str


class TagCreate(TagBase):
    code: Optional[str] = None
    prompt: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    prompt: Optional[str] = None


class Tag(BaseSchema):
    """标签响应模型"""
    id: int
    name: str
    level: int = 2  # 0=分类, 1=分辨率, 2=普通标签
    usage_count: int = 0
    code: Optional[str] = None
    prompt: Optional[str] = None
    created_at: datetime


# 标签列表响应 - 直接使用通用分页基类
TagList = PaginatedResponse[Tag]
