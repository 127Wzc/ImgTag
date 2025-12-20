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
    usage_count: int
    created_at: datetime

    class Config:
        from_attributes = True

class TagList(BaseModel):
    items: List[Tag]
    total: int
