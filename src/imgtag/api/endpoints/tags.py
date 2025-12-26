#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tag API endpoints.

Handles tag CRUD, categories, and resolutions.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.logging_config import get_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import tag_repository
from imgtag.schemas import Tag, TagList, TagUpdate

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=list[Tag])
async def get_tags(
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str = Query("usage_count", pattern="^(usage_count|name)$"),
    level: int = Query(2, ge=0, le=2, description="标签级别: 0=分类, 1=分辨率, 2=普通标签"),
    session: AsyncSession = Depends(get_async_session),
):
    """Get tag list for autocomplete.

    Args:
        limit: Maximum tags to return.
        sort_by: Sort field (usage_count or name).
        level: Tag level filter (default: 2 for normal tags).
        session: Database session.

    Returns:
        List of tags.
    """
    return await tag_repository.get_all_sorted(session, limit=limit, sort_by=sort_by, level=level)


@router.post("/sync", response_model=dict[str, Any])
async def sync_tags(
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Sync tag usage counts (admin only).

    Note: With ORM, usage counts are calculated on-the-fly via joins.
    This endpoint is kept for API compatibility.

    Args:
        admin: Admin user.
        session: Database session.

    Returns:
        Sync result message.
    """
    # Usage counts are now calculated dynamically via joins
    # No need for sync with ORM approach
    return {
        "message": "标签同步完成（ORM 模式下实时计算）",
        "count": 0,
    }


@router.put("/{tag_name}", response_model=dict[str, Any])
async def rename_tag(
    tag_name: str,
    tag_update: TagUpdate,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Rename tag (admin only).

    Args:
        tag_name: Current tag name.
        tag_update: New tag data.
        admin: Admin user.
        session: Database session.

    Returns:
        Rename result.
    """
    if not tag_update.name:
        raise HTTPException(status_code=400, detail="新标签名不能为空")

    if tag_name == tag_update.name:
        raise HTTPException(status_code=400, detail="新标签名与原标签名相同")

    if await tag_repository.exists(session, tag_update.name):
        raise HTTPException(
            status_code=409,
            detail=f"标签 '{tag_update.name}' 已存在，无法重命名",
        )

    success = await tag_repository.rename(session, tag_name, tag_update.name)
    if not success:
        raise HTTPException(status_code=404, detail=f"标签 '{tag_name}' 不存在")

    return {
        "message": f"标签 '{tag_name}' 已重命名为 '{tag_update.name}'",
        "old_name": tag_name,
        "new_name": tag_update.name,
    }


@router.delete("/{tag_name}", response_model=dict[str, Any])
async def delete_tag(
    tag_name: str,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete tag (admin only).

    Args:
        tag_name: Tag name to delete.
        admin: Admin user.
        session: Database session.

    Returns:
        Delete result.
    """
    tag = await tag_repository.get_by_name(session, tag_name)
    if not tag:
        raise HTTPException(status_code=404, detail=f"标签 '{tag_name}' 不存在")

    await tag_repository.delete(session, tag)

    return {
        "message": f"标签 '{tag_name}' 已删除",
        "deleted_name": tag_name,
    }


# ============= Category Management =============


@router.get("/categories", response_model=list[dict[str, Any]])
async def get_categories(
    session: AsyncSession = Depends(get_async_session),
):
    """Get main categories (level=0).

    Args:
        session: Database session.

    Returns:
        List of categories with image counts.
    """
    return await tag_repository.get_categories(session)


@router.post("/categories", response_model=dict[str, Any])
async def create_category(
    name: str,
    description: str = None,
    sort_order: int = 0,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Create main category (admin only).

    Args:
        name: Category name.
        description: Optional description.
        sort_order: Display order.
        admin: Admin user.
        session: Database session.

    Returns:
        Created category info.
    """
    if await tag_repository.exists(session, name):
        raise HTTPException(status_code=409, detail=f"标签 '{name}' 已存在")

    try:
        tag = await tag_repository.create_category(
            session,
            name,
            description=description,
            sort_order=sort_order,
        )
        return {
            "message": f"主分类 '{name}' 创建成功",
            "id": tag.id,
            "name": name,
        }
    except Exception as e:
        logger.error(f"创建分类失败: {e}")
        raise HTTPException(status_code=500, detail="创建主分类失败")


@router.delete("/categories/{tag_id}", response_model=dict[str, Any])
async def delete_category(
    tag_id: int,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete category (admin only, fails if in use).

    Args:
        tag_id: Category tag ID.
        admin: Admin user.
        session: Database session.

    Returns:
        Delete result.
    """
    success, message = await tag_repository.delete_category(session, tag_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"message": message}


# ============= Resolution Tags =============


@router.get("/resolutions", response_model=list[dict[str, Any]])
async def get_resolutions(
    session: AsyncSession = Depends(get_async_session),
):
    """Get resolution tags (level=1).

    Args:
        session: Database session.

    Returns:
        List of resolution tags with image counts.
    """
    return await tag_repository.get_resolutions(session)
