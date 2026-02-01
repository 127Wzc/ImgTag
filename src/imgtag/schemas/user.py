"""用户相关 Schema"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

from .base import BaseSchema


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=6)
    role: Optional[str] = Field(default="user", description="user 或 admin")
    permissions: Optional[int] = Field(default=1, description="权限位掩码")


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseSchema):
    id: int
    username: str
    email: Optional[str] = None
    role: str
    is_active: bool
    permissions: int
    created_at: datetime
    last_login_at: Optional[datetime] = None


class Token(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class TokenPayload(BaseModel):
    sub: str  # user_id
    username: str
    role: str
    exp: datetime
