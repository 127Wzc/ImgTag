from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

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

class Collection(CollectionBase):
    id: int
    cover_image_id: Optional[int] = None
    sort_order: int
    is_public: bool
    image_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CollectionList(BaseModel):
    items: List[Collection]
    total: int

class CollectionImageAdd(BaseModel):
    image_id: int
