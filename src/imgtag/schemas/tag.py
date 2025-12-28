from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

class TagBase(BaseModel):
    name: str

class TagCreate(TagBase):
    pass

class TagUpdate(BaseModel):
    name: str

class Tag(TagBase):
    id: int
    level: int = 2  # 0=分类, 1=分辨率, 2=普通标签
    usage_count: int
    created_at: datetime

    class Config:
        from_attributes = True

class TagList(BaseModel):
    items: List[Tag]
    total: int

