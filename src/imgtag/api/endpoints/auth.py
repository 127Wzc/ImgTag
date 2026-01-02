#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Authentication API endpoints.

Provides user authentication, registration, and management.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.core.config_cache import config_cache
from imgtag.db import get_async_session
from imgtag.db.repositories import user_repository
from imgtag.models.user import User
from imgtag.schemas.user import Token, UserCreate, UserLogin, UserResponse
from imgtag.services import auth_service

logger = get_logger(__name__)

router = APIRouter()
security = HTTPBearer(auto_error=False)


def _user_to_dict(user: User) -> dict[str, Any]:
    """Convert User model to dictionary.

    Args:
        user: User model instance.

    Returns:
        Dictionary representation of user.
    """
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "password_hash": user.password_hash,
        "api_key": user.api_key,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """Get current authenticated user.

    Args:
        credentials: HTTP Bearer credentials.
        session: Database session.

    Returns:
        User dictionary.

    Raises:
        HTTPException: If authentication fails.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="未提供认证凭据")

    payload = auth_service.decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    user_id = int(payload["sub"])
    user = await user_repository.get_by_id(session, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="用户已被禁用")

    return _user_to_dict(user)


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_async_session),
) -> Optional[dict[str, Any]]:
    """Get current user if authenticated (optional).

    Args:
        credentials: HTTP Bearer credentials.
        session: Database session.

    Returns:
        User dictionary or None.
    """
    if not credentials:
        return None

    try:
        return await get_current_user(credentials, session)
    except HTTPException:
        return None


async def require_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """Require admin role.

    Args:
        user: Current user dictionary.

    Returns:
        User dictionary if admin.

    Raises:
        HTTPException: If user is not admin.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


@router.post("/login", response_model=Token)
async def login(
    data: UserLogin,
    session: AsyncSession = Depends(get_async_session),
):
    """User login.

    Args:
        data: Login credentials.
        session: Database session.

    Returns:
        JWT access token.
    """
    user = await user_repository.get_by_username(session, data.username)

    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not user.is_active:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not auth_service.verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # Update last login time
    await user_repository.update_last_login(session, user)

    token = auth_service.create_access_token(user.id, user.username, user.role)

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": auth_service.JWT_EXPIRE_HOURS * 3600,
    }


@router.get("/public-config")
async def get_public_config():
    """Get public configuration (no auth required).

    Returns:
        Public config including registration status.
    """
    allow_register = await config_cache.get("allow_register", "false")
    return {
        "allow_register": (allow_register or "false").lower() == "true"
    }


@router.post("/register", response_model=dict[str, Any])
async def register(
    data: UserCreate,
    session: AsyncSession = Depends(get_async_session),
):
    """User registration.

    Args:
        data: Registration data.
        session: Database session.

    Returns:
        Success message with user ID.
    """
    # Check if registration is allowed
    allow_register_value = await config_cache.get("allow_register", "false")
    allow_register = (allow_register_value or "false").lower() == "true"
    if not allow_register:
        raise HTTPException(status_code=403, detail="注册功能已关闭")

    # Check if username exists
    if await user_repository.username_exists(session, data.username):
        raise HTTPException(status_code=400, detail="用户名已存在")

    password_hash = auth_service.hash_password(data.password)

    try:
        user = await user_repository.create_user(
            session,
            username=data.username,
            password_hash=password_hash,
            email=data.email,
        )
        logger.info(f"用户注册成功: {data.username} (ID: {user.id})")
        return {"message": "注册成功", "user_id": user.id}
    except Exception as e:
        logger.error(f"用户注册失败: {e}")
        raise HTTPException(status_code=400, detail="注册失败")


@router.get("/me", response_model=UserResponse)
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user information.

    Args:
        user: Current user dictionary.

    Returns:
        User response.
    """
    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user.get("email"),
        role=user["role"],
        is_active=user.get("is_active", True),
        created_at=user["created_at"],
        last_login_at=user.get("last_login_at"),
    )


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)):
    """User logout (client should delete token).

    Args:
        user: Current user dictionary.

    Returns:
        Logout confirmation.
    """
    return {"message": "已登出"}


# ========== User Management (Admin) ==========


@router.get("/users")
async def list_users(
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """List all users (admin only).

    Args:
        admin: Current admin user.
        session: Database session.

    Returns:
        List of users.
    """
    users = await user_repository.get_all_users(session)
    return {"users": [_user_to_dict(u) for u in users]}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    is_active: Optional[bool] = None,
    role: Optional[str] = None,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Update user (admin only).

    Args:
        user_id: Target user ID.
        is_active: Active status to set.
        role: Role to set.
        admin: Current admin user.
        session: Database session.

    Returns:
        Update confirmation.
    """
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能修改自己的权限")
    
    # 保护超级管理员 (id=1)
    if user_id == 1 and admin["id"] != 1:
        raise HTTPException(status_code=403, detail="无权修改超级管理员")

    if role is not None and role not in ["user", "admin"]:
        raise HTTPException(status_code=400, detail="无效的角色")

    user = await user_repository.get_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if is_active is not None:
        await user_repository.set_active(session, user, is_active)
    if role is not None:
        await user_repository.set_role(session, user, role)

    return {"message": "更新成功"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete user (admin only).

    Args:
        user_id: Target user ID.
        admin: Current admin user.
        session: Database session.

    Returns:
        Delete confirmation.
    """
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    
    # 保护超级管理员 (id=1)
    if user_id == 1:
        raise HTTPException(status_code=403, detail="不能删除超级管理员")

    user = await user_repository.get_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await user_repository.delete(session, user)
    return {"message": "删除成功"}


@router.post("/users")
async def create_user_by_admin(
    data: UserCreate,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Create user (admin only).

    Args:
        data: User creation data.
        admin: Current admin user.
        session: Database session.

    Returns:
        Created user ID.
    """
    if await user_repository.username_exists(session, data.username):
        raise HTTPException(status_code=400, detail="用户名已存在")

    password_hash = auth_service.hash_password(data.password)

    try:
        user = await user_repository.create_user(
            session,
            username=data.username,
            password_hash=password_hash,
            email=data.email,
            role=data.role or "user",
        )
        return {"message": "创建成功", "user_id": user.id}
    except Exception as e:
        logger.error(f"创建用户失败: {e}")
        raise HTTPException(status_code=400, detail="创建失败")


@router.put("/users/{user_id}/password")
async def change_user_password(
    user_id: int,
    new_password: str,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Change user password (admin only).

    Args:
        user_id: Target user ID.
        new_password: New password.
        admin: Current admin user.
        session: Database session.

    Returns:
        Update confirmation.
    """
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码至少6位")
    
    # 保护超级管理员 (id=1) 的密码只能由本人修改
    if user_id == 1 and admin["id"] != 1:
        raise HTTPException(status_code=403, detail="无权修改超级管理员密码")

    user = await user_repository.get_by_id(session, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    password_hash = auth_service.hash_password(new_password)
    await user_repository.update_password(session, user, password_hash)

    return {"message": "密码修改成功"}


# ========== Personal Settings ==========


class ChangePasswordRequest(BaseModel):
    """Password change request."""

    old_password: str
    new_password: str = Field(..., min_length=6)


@router.put("/me/password")
async def change_my_password(
    data: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Change own password (requires old password).

    Args:
        data: Password change data.
        user: Current user dictionary.
        session: Database session.

    Returns:
        Update confirmation.
    """
    full_user = await user_repository.get_by_id(session, user["id"])
    if not full_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not auth_service.verify_password(data.old_password, full_user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")

    password_hash = auth_service.hash_password(data.new_password)
    await user_repository.update_password(session, full_user, password_hash)

    return {"message": "密码修改成功"}


@router.post("/me/api-key")
async def generate_my_api_key(
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Generate new personal API key (overwrites old key).

    Args:
        user: Current user dictionary.
        session: Database session.

    Returns:
        Generated API key.
    """
    full_user = await user_repository.get_by_id(session, user["id"])
    if not full_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    api_key = await user_repository.generate_api_key(session, full_user)

    return {"api_key": api_key, "message": "API 密钥生成成功，请妥善保存"}


@router.get("/me/api-key")
async def get_my_api_key(
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Get current API key (masked).

    Args:
        user: Current user dictionary.
        session: Database session.

    Returns:
        API key status and masked key.
    """
    full_user = await user_repository.get_by_id(session, user["id"])
    if not full_user or not full_user.api_key:
        return {"has_key": False, "masked_key": None}

    # Mask: first 8...last 8
    api_key = full_user.api_key
    masked_key = f"{api_key[:8]}...{api_key[-8:]}"

    return {"has_key": True, "masked_key": masked_key}


@router.delete("/me/api-key")
async def delete_my_api_key(
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete personal API key.

    Args:
        user: Current user dictionary.
        session: Database session.

    Returns:
        Delete confirmation.
    """
    full_user = await user_repository.get_by_id(session, user["id"])
    if not full_user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await user_repository.delete_api_key(session, full_user)

    return {"message": "API 密钥已删除"}
