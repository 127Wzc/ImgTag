from typing import Optional
from datetime import datetime
from pydantic import BaseModel

from .base import BaseSchema, PaginatedResponse


class CollectionBase(BaseModel):
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None


class CollectionCreate(CollectionBase):
    pass


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image_id: Optional[int] = None
    parent_id: Optional[int] = None


class Collection(BaseSchema):
    """收藏夹响应模型"""
    id: int
    name: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    cover_image_id: Optional[int] = None
    sort_order: int = 0
    is_public: bool = True
    image_count: int = 0
    created_at: datetime
    updated_at: datetime


# 收藏夹列表响应 - 直接使用通用分页基类
CollectionList = PaginatedResponse[Collection]


class CollectionImageAdd(BaseModel):
    image_id: int
