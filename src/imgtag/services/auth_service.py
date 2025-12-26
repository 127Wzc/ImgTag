#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
认证服务
JWT Token 认证和密码管理
"""

import os
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.db.repositories import user_repository
from imgtag.models.user import User

logger = get_logger(__name__)

# JWT 配置
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    """密码哈希"""
    salt = secrets.token_hex(16)
    pw_hash = hashlib.pbkdf2_hmac(
        'sha256', 
        password.encode('utf-8'), 
        salt.encode('utf-8'), 
        100000
    )
    return f"{salt}${pw_hash.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    try:
        salt, stored_hash = password_hash.split('$')
        pw_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return pw_hash.hex() == stored_hash
    except Exception:
        return False


def create_access_token(user_id: int, username: str, role: str) -> str:
    """创建 JWT Token"""
    import jwt
    
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def decode_token(token: str) -> Optional[dict]:
    """解码 JWT Token"""
    import jwt
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("Token 已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Token 无效: {str(e)}")
        return None


async def authenticate_user(
    session: AsyncSession,
    username: str,
    password: str,
) -> Optional[User]:
    """验证用户登录"""
    user = await user_repository.get_by_username(session, username)
    
    if not user:
        logger.warning(f"用户不存在: {username}")
        return None
    
    if not user.is_active:
        logger.warning(f"用户已禁用: {username}")
        return None
    
    if not verify_password(password, user.password_hash):
        logger.warning(f"密码错误: {username}")
        return None
    
    # 更新最后登录时间
    await user_repository.update_last_login(session, user)
    
    return user


async def register_user(
    session: AsyncSession,
    username: str,
    password: str,
    email: str | None = None,
    role: str = "user",
) -> Optional[int]:
    """注册新用户"""
    # 检查用户名是否存在
    if await user_repository.username_exists(session, username):
        logger.warning(f"用户名已存在: {username}")
        return None
    
    password_hash = hash_password(password)
    user = await user_repository.create_user(
        session,
        username=username,
        password_hash=password_hash,
        email=email,
        role=role,
    )
    
    logger.info(f"用户注册成功: {username} (ID: {user.id})")
    return user.id


async def init_default_admin(session: AsyncSession) -> None:
    """初始化默认管理员账号"""
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    
    existing = await user_repository.get_by_username(session, admin_username)
    if not existing:
        user_id = await register_user(
            session,
            admin_username,
            admin_password,
            role="admin",
        )
        if user_id:
            logger.info(f"默认管理员账号已创建: {admin_username}")
    else:
        logger.info(f"管理员账号已存在: {admin_username}")
