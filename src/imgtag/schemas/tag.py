from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TagBase(BaseModel):
    name: str


class TagCreate(TagBase):
    code: Optional[str] = None
    prompt: Optional[str] = None


class TagUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    prompt: Optional[str] = None


class Tag(TagBase):
    id: int
    level: int = 2  # 0=分类, 1=分辨率, 2=普通标签
    usage_count: int
    code: Optional[str] = None
    prompt: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TagList(BaseModel):
    items: List[Tag]
    total: int
