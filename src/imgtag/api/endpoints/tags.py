#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tag API endpoints.

Unified tag CRUD with level-based permissions:
- Level 0/1 (categories/resolutions): Admin only
- Level 2 (normal tags): Authenticated users
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin, get_current_user
from imgtag.core.logging_config import get_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import tag_repository
from imgtag.schemas import Tag, TagUpdate

logger = get_logger(__name__)

router = APIRouter()


# ============= Read Operations (Public) =============


@router.get("/", response_model=list[Tag])
async def get_tags(
    page: int = Query(1, ge=1, description="页码 (从 1 开始)"),
    size: int = Query(50, ge=1, le=200, description="每页数量，最大200"),
    sort_by: str = Query("usage_count", pattern="^(usage_count|name)$"),
    level: int | None = Query(None, ge=0, le=2, description="标签级别: 0=分类, 1=分辨率, 2=普通标签"),
    keyword: str | None = Query(None, description="标签名模糊搜索"),
    session: AsyncSession = Depends(get_async_session),
):
    """Get tag list with optional level filter and keyword search."""
    return await tag_repository.get_all_sorted(
        session, limit=size, offset=(page - 1) * size, sort_by=sort_by, level=level, keyword=keyword
    )


@router.get("/stats", response_model=dict[str, Any])
async def get_tag_stats(
    session: AsyncSession = Depends(get_async_session),
):
    """Get tag count statistics by level."""
    return await tag_repository.get_stats(session)


# ============= Create (Level-based permissions) =============


@router.post("/", response_model=dict[str, Any])
async def create_tag(
    name: str,
    level: int = Query(2, ge=0, le=2),
    source: str = "user",
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new tag.
    
    - Level 0/1: Admin only
    - Level 2: Any authenticated user
    """
    # 权限检查
    if level in (0, 1) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可创建主分类和分辨率标签")

    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="标签名不能为空")

    name = name.strip()

    if await tag_repository.exists(session, name):
        raise HTTPException(status_code=409, detail=f"标签 '{name}' 已存在")

    tag = await tag_repository.create(
        session,
        name=name,
        level=level,
        source=source,
    )

    return {
        "message": f"标签 '{name}' 创建成功",
        "id": tag.id,
        "name": tag.name,
        "level": tag.level,
    }


@router.post("/resolve", response_model=dict[str, Any])
async def resolve_tag(
    name: str = Query(..., min_length=1, max_length=50, description="标签名"),
    level: int = Query(2, ge=0, le=2, description="标签级别"),
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Resolve tag: get existing or create new.
    
    Used by frontend when adding tags to images.
    Returns tag info for caching, without modifying image associations.
    
    - Level 0/1: Must exist (only admin can create)
    - Level 2: Auto-create if not exists
    """

    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="标签名不能为空")

    # 先查询是否存在
    existing = await tag_repository.get_by_name(session, name)
    if existing:
        return {
            "id": existing.id,
            "name": existing.name,
            "level": existing.level,
            "source": existing.source,
            "is_new": False,
        }

    # 不存在时的处理
    if level in (0, 1):
        # Level 0/1 不能自动创建
        raise HTTPException(
            status_code=404, 
            detail=f"{'主分类' if level == 0 else '分辨率'}标签 '{name}' 不存在"
        )

    # Level 2: 自动创建（处理并发情况）
    try:
        new_tag = await tag_repository.create(
            session,
            name=name,
            level=2,
            source="user",
        )

        return {
            "id": new_tag.id,
            "name": new_tag.name,
            "level": new_tag.level,
            "source": new_tag.source,
            "is_new": True,
        }
    except IntegrityError:
        # 并发情况下可能已被其他请求创建，重新查询
        await session.rollback()
        existing = await tag_repository.get_by_name(session, name)
        if existing:
            return {
                "id": existing.id,
                "name": existing.name,
                "level": existing.level,
                "source": existing.source,
                "is_new": False,
            }
        raise HTTPException(status_code=500, detail="创建标签失败")


# ============= Update (Level-based permissions) =============


@router.put("/id/{tag_id}", response_model=dict[str, Any])
async def rename_tag_by_id(
    tag_id: int,
    tag_update: TagUpdate,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update tag by ID.
    
    - Level 0/1: Admin only (supports name, code, prompt)
    - Level 2: Any authenticated user (name only)
    """
    tag = await tag_repository.get_by_id(session, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    # 权限检查
    if tag.level in (0, 1) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可修改主分类和分辨率标签")

    updated_fields = {}
    
    # Update name if provided
    if tag_update.name and tag_update.name.strip():
        new_name = tag_update.name.strip()
        if tag.name != new_name:
            if await tag_repository.exists(session, new_name):
                raise HTTPException(status_code=409, detail=f"标签 '{new_name}' 已存在")
            updated_fields["old_name"] = tag.name
            tag.name = new_name
            updated_fields["new_name"] = new_name
    
    # Update code if provided (level=0 only)
    if tag_update.code is not None and tag.level == 0:
        tag.code = tag_update.code or None
        updated_fields["code"] = tag.code
    
    # Update prompt if provided (level=0 only)
    if tag_update.prompt is not None and tag.level == 0:
        tag.prompt = tag_update.prompt or None
        updated_fields["prompt"] = "已更新" if tag.prompt else "已清空"
    
    if not updated_fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    
    await session.flush()
    
    # Invalidate category cache if level=0 tag was updated
    if tag.level == 0:
        from imgtag.core.category_cache import invalidate_category_cache
        invalidate_category_cache(tag_id)
        logger.info(f"已刷新分类缓存: {tag_id}")

    return {
        "message": f"标签 '{tag.name}' 更新成功",
        "id": tag_id,
        **updated_fields,
    }


# ============= Delete (Level-based permissions) =============


@router.delete("/id/{tag_id}", response_model=dict[str, Any])
async def delete_tag_by_id(
    tag_id: int,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete tag by ID.
    
    - Level 0/1: Admin only (and checks for usage)
    - Level 2: Any authenticated user
    """
    tag = await tag_repository.get_by_id(session, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在")

    # 权限检查
    if tag.level in (0, 1) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可删除主分类和分辨率标签")

    # Level 0/1 检查是否在使用中
    if tag.level in (0, 1):
        success, message = await tag_repository.delete_category(session, tag_id)
        if not success:
            raise HTTPException(status_code=400, detail=message)
        return {"message": message, "id": tag_id, "name": tag.name}

    # Level 2 直接删除
    await tag_repository.delete(session, tag)
    return {
        "message": f"标签 '{tag.name}' 已删除",
        "id": tag_id,
        "name": tag.name,
    }


# ============= Legacy endpoints (for compatibility) =============


@router.delete("/{tag_name}", response_model=dict[str, Any])
async def delete_tag_by_name(
    tag_name: str,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete tag by name (admin only, deprecated)."""
    tag = await tag_repository.get_by_name(session, tag_name)
    if not tag:
        raise HTTPException(status_code=404, detail=f"标签 '{tag_name}' 不存在")

    await tag_repository.delete(session, tag)
    return {"message": f"标签 '{tag_name}' 已删除", "deleted_name": tag_name}


@router.post("/sync", response_model=dict[str, Any])
async def sync_tags(
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Sync all tag usage counts (admin only).
    
    Recalculates usage_count for all tags from image_tags table.
    Use this if triggers are out of sync or after bulk operations.
    """
    import time
    start = time.time()
    
    count = await tag_repository.sync_usage_counts(session)
    
    elapsed = time.time() - start
    logger.info(f"标签使用计数同步完成: {count} 个标签, 耗时 {elapsed:.3f}s")
    
    return {
        "message": f"标签使用计数同步完成",
        "count": count,
        "elapsed_ms": round(elapsed * 1000, 2),
    }

