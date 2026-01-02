#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API 公共依赖
统一的认证和验证逻辑
"""

from typing import Optional, Dict, Any

from fastapi import Header, Query, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.db.database import get_async_session
from imgtag.db.repositories import user_repository

logger = get_logger(__name__)


async def verify_api_key(
    api_key: str = Query(None, description="API 密钥"),
    header_api_key: str = Header(None, alias="api_key", description="API 密钥（Header 方式）"),
    session: AsyncSession = Depends(get_async_session),
) -> Optional[Dict[str, Any]]:
    """
    统一的 API 密钥验证逻辑
    
    支持两种传递方式：
    1. Header: api_key
    2. Query Parameter: api_key
    
    验证逻辑：
    - 如果提供了密钥，则必须匹配某个用户的个人密钥
    - 如果未提供密钥，则视为匿名访问（返回 None）
    
    Returns:
        user: 匹配的用户信息，或 None（未提供密钥时）
    
    Raises:
        HTTPException: 提供了密钥但无效时抛出 401
    """
    provided_key = api_key or header_api_key
    
    if not provided_key:
        # 未提供密钥，匿名访问
        return None
    
    # 尝试匹配用户密钥
    user = await user_repository.get_by_api_key(session, provided_key)
    if user:
        # 检查用户是否被禁用
        if not user.is_active:
            raise HTTPException(status_code=403, detail="用户已被禁用")
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "is_active": user.is_active,
        }
    
    # 密钥无效
    raise HTTPException(status_code=401, detail="无效的 API 密钥")


async def require_api_key(
    api_key: str = Query(None, description="API 密钥"),
    header_api_key: str = Header(None, alias="api_key", description="API 密钥（Header 方式）"),
    session: AsyncSession = Depends(get_async_session),
) -> Dict[str, Any]:
    """
    强制要求 API 密钥的验证逻辑
    
    与 verify_api_key 不同，此依赖强制要求提供有效的密钥
    
    Returns:
        user: 匹配的用户信息
    
    Raises:
        HTTPException: 未提供密钥或密钥无效时抛出 401
    """
    provided_key = api_key or header_api_key
    
    if not provided_key:
        raise HTTPException(status_code=401, detail="需要 API 密钥")
    
    user = await user_repository.get_by_api_key(session, provided_key)
    if user:
        # 检查用户是否被禁用
        if not user.is_active:
            raise HTTPException(status_code=403, detail="用户已被禁用")
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "is_active": user.is_active,
        }
    
    raise HTTPException(status_code=401, detail="无效的 API 密钥")
