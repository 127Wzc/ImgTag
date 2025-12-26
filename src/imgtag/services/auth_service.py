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

from imgtag.db import db
from imgtag.core.logging_config import get_logger

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


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """验证用户登录"""
    user = db.get_user_by_username(username)
    
    if not user:
        logger.warning(f"用户不存在: {username}")
        return None
    
    if not user.get("is_active", True):
        logger.warning(f"用户已禁用: {username}")
        return None
    
    if not verify_password(password, user["password_hash"]):
        logger.warning(f"密码错误: {username}")
        return None
    
    # 更新最后登录时间
    db.update_user_last_login(user["id"])
    
    return user


def register_user(username: str, password: str, email: str = None, role: str = "user") -> Optional[int]:
    """注册新用户"""
    # 检查用户名是否存在
    existing = db.get_user_by_username(username)
    if existing:
        logger.warning(f"用户名已存在: {username}")
        return None
    
    password_hash = hash_password(password)
    user_id = db.create_user(username, password_hash, email, role)
    
    if user_id:
        logger.info(f"用户注册成功: {username} (ID: {user_id})")
    
    return user_id


def init_default_admin():
    """初始化默认管理员账号"""
    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")
    
    existing = db.get_user_by_username(admin_username)
    if not existing:
        user_id = register_user(admin_username, admin_password, role="admin")
        if user_id:
            logger.info(f"默认管理员账号已创建: {admin_username}")
    else:
        logger.info(f"管理员账号已存在: {admin_username}")
