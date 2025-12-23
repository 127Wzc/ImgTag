#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
认证 API 端点
"""

from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from imgtag.schemas.user import UserCreate, UserLogin, UserResponse, Token
from pydantic import BaseModel, Field
from imgtag.services import auth_service
from imgtag.db import db
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """获取当前登录用户"""
    if not credentials:
        raise HTTPException(status_code=401, detail="未提供认证凭据")
    
    payload = auth_service.decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")
    
    user_id = int(payload["sub"])
    user = db.get_user_by_id(user_id)
    
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="用户已被禁用")
    
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict[str, Any]:
    """获取当前用户（可选，不强制登录）"""
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


async def require_admin(user: Dict = Depends(get_current_user)) -> Dict:
    """要求管理员权限"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.post("/login", response_model=Token)
async def login(data: UserLogin):
    """用户登录"""
    user = auth_service.authenticate_user(data.username, data.password)
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    token = auth_service.create_access_token(
        user["id"], 
        user["username"], 
        user["role"]
    )
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": auth_service.JWT_EXPIRE_HOURS * 3600
    }


@router.post("/register", response_model=Dict[str, Any])
async def register(data: UserCreate):
    """用户注册"""
    user_id = auth_service.register_user(
        data.username, 
        data.password, 
        data.email
    )
    
    if not user_id:
        raise HTTPException(status_code=400, detail="用户名已存在或注册失败")
    
    return {
        "message": "注册成功",
        "user_id": user_id
    }


@router.get("/me", response_model=UserResponse)
async def get_me(user: Dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user.get("email"),
        role=user["role"],
        is_active=user.get("is_active", True),
        created_at=user["created_at"],
        last_login_at=user.get("last_login_at")
    )


@router.post("/logout")
async def logout(user: Dict = Depends(get_current_user)):
    """用户登出（客户端需删除 Token）"""
    return {"message": "已登出"}


# ========== 用户管理（管理员） ==========

@router.get("/users")
async def list_users(admin: Dict = Depends(require_admin)):
    """获取所有用户列表（管理员）"""
    users = db.get_all_users()
    return {"users": users}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    is_active: bool = None,
    role: str = None,
    admin: Dict = Depends(require_admin)
):
    """更新用户信息（管理员）"""
    # 不允许修改自己
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能修改自己的权限")
    
    if role is not None and role not in ["user", "admin"]:
        raise HTTPException(status_code=400, detail="无效的角色")
    
    success = db.update_user(user_id, is_active=is_active, role=role)
    if not success:
        raise HTTPException(status_code=500, detail="更新失败")
    
    return {"message": "更新成功"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: Dict = Depends(require_admin)):
    """删除用户（管理员）"""
    # 不允许删除自己
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    success = db.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    
    return {"message": "删除成功"}


@router.post("/users")
async def create_user_by_admin(
    data: UserCreate,
    admin: Dict = Depends(require_admin)
):
    """管理员创建用户"""
    user_id = auth_service.register_user(
        data.username, 
        data.password, 
        data.email
    )
    
    if not user_id:
        raise HTTPException(status_code=400, detail="用户名已存在或创建失败")
    
    return {"message": "创建成功", "user_id": user_id}


@router.put("/users/{user_id}/password")
async def change_user_password(
    user_id: int,
    new_password: str,
    admin: Dict = Depends(require_admin)
):
    """管理员修改用户密码"""
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    
    success = db.change_user_password(user_id, new_password)
    if not success:
        raise HTTPException(status_code=500, detail="修改密码失败")
    
    return {"message": "密码修改成功"}


# ========== 个人中心 ==========

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6)


@router.put("/me/password")
async def change_my_password(
    data: ChangePasswordRequest,
    user: Dict = Depends(get_current_user)
):
    """修改自己的密码（需验证旧密码）"""
    # 获取完整用户信息（包含密码哈希）
    full_user = db.get_user_by_id(user["id"])
    if not full_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 验证旧密码
    if not auth_service.verify_password(data.old_password, full_user["password_hash"]):
        raise HTTPException(status_code=400, detail="旧密码错误")
    
    # 修改密码
    success = db.change_user_password(user["id"], data.new_password)
    if not success:
        raise HTTPException(status_code=500, detail="修改密码失败")
    
    return {"message": "密码修改成功"}


@router.post("/me/api-key")
async def generate_my_api_key(user: Dict = Depends(get_current_user)):
    """生成新的个人 API 密钥（会覆盖旧密钥）"""
    api_key = db.generate_user_api_key(user["id"])
    if not api_key:
        raise HTTPException(status_code=500, detail="生成 API 密钥失败")
    
    return {
        "api_key": api_key,
        "message": "API 密钥生成成功，请妥善保存"
    }


@router.get("/me/api-key")
async def get_my_api_key(user: Dict = Depends(get_current_user)):
    """获取当前 API 密钥（脱敏显示）"""
    api_key = db.get_user_api_key(user["id"])
    
    if not api_key:
        return {"has_key": False, "masked_key": None}
    
    # 脱敏显示：前8位...后8位
    masked_key = f"{api_key[:8]}...{api_key[-8:]}"
    
    return {
        "has_key": True,
        "masked_key": masked_key
    }


@router.delete("/me/api-key")
async def delete_my_api_key(user: Dict = Depends(get_current_user)):
    """删除个人 API 密钥"""
    success = db.delete_user_api_key(user["id"])
    if not success:
        raise HTTPException(status_code=500, detail="删除 API 密钥失败")
    
    return {"message": "API 密钥已删除"}

