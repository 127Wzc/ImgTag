#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Collection API endpoints.

Handles collection CRUD and image associations.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import get_current_user
from imgtag.core.logging_config import get_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    collection_repository,
    image_collection_repository,
)
from imgtag.schemas import (
    Collection,
    CollectionCreate,
    CollectionImageAdd,
    CollectionUpdate,
)

logger = get_logger(__name__)

router = APIRouter()


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_collection(
    collection: CollectionCreate,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create collection (requires login).

    Args:
        collection: Collection creation data.
        user: Current user.
        session: Database session.

    Returns:
        Created collection ID.
    """
    logger.info(f"创建收藏夹: {collection.name}")

    try:
        new_coll = await collection_repository.create_collection(
            session,
            name=collection.name,
            description=collection.description,
            parent_id=collection.parent_id,
            created_by=user.get("id"),
        )

        return {"id": new_coll.id, "message": "收藏夹创建成功"}

    except Exception as e:
        logger.error(f"创建收藏夹失败: {e}")
        raise HTTPException(status_code=500, detail="创建收藏夹失败")


@router.get("/", response_model=list[Collection])
async def get_collections(
    session: AsyncSession = Depends(get_async_session),
):
    """Get all collections.

    Args:
        session: Database session.

    Returns:
        List of collections.
    """
    return await collection_repository.get_all_with_counts(session)


@router.get("/{collection_id}", response_model=Collection)
async def get_collection(
    collection_id: int,
    session: AsyncSession = Depends(get_async_session),
):
    """Get single collection details.

    Args:
        collection_id: Collection ID.
        session: Database session.

    Returns:
        Collection details.
    """
    coll = await collection_repository.get_by_id(session, collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    return {
        "id": coll.id,
        "name": coll.name,
        "description": coll.description,
        "parent_id": coll.parent_id,
        "cover_image_id": coll.cover_image_id,
        "sort_order": coll.sort_order or 0,
        "is_public": coll.is_public if coll.is_public is not None else True,
        "created_at": coll.created_at,
        "updated_at": coll.updated_at,
        "image_count": 0,  # Would need extra query
    }


@router.put("/{collection_id}", response_model=dict[str, Any])
async def update_collection(
    collection_id: int,
    collection: CollectionUpdate,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update collection (requires login).

    Args:
        collection_id: Collection ID.
        collection: Update data.
        user: Current user.
        session: Database session.

    Returns:
        Update confirmation.
    """
    coll = await collection_repository.get_by_id(session, collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    await collection_repository.update_collection(
        session,
        coll,
        name=collection.name,
        description=collection.description,
        cover_image_id=collection.cover_image_id,
    )

    return {"message": "收藏夹更新成功"}


@router.delete("/{collection_id}", response_model=dict[str, Any])
async def delete_collection(
    collection_id: int,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete collection (requires login).

    Args:
        collection_id: Collection ID.
        user: Current user.
        session: Database session.

    Returns:
        Delete confirmation.
    """
    coll = await collection_repository.get_by_id(session, collection_id)
    if not coll:
        raise HTTPException(status_code=404, detail="收藏夹不存在")

    await collection_repository.delete(session, coll)

    return {"message": "收藏夹删除成功"}


@router.post("/{collection_id}/images", response_model=dict[str, Any])
async def add_image_to_collection(
    collection_id: int,
    image_data: CollectionImageAdd,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Add image to collection (requires login).

    Args:
        collection_id: Collection ID.
        image_data: Image to add.
        user: Current user.
        session: Database session.

    Returns:
        Add confirmation.
    """
    try:
        await image_collection_repository.add_image(
            session,
            collection_id,
            image_data.image_id,
        )

        return {"message": "已添加到收藏夹"}

    except Exception as e:
        logger.error(f"添加图片到收藏夹失败: {e}")
        raise HTTPException(status_code=500, detail="添加图片到收藏夹失败")


@router.delete("/{collection_id}/images/{image_id}", response_model=dict[str, Any])
async def remove_image_from_collection(
    collection_id: int,
    image_id: int,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Remove image from collection (requires login).

    Args:
        collection_id: Collection ID.
        image_id: Image ID.
        user: Current user.
        session: Database session.

    Returns:
        Remove confirmation.
    """
    success = await image_collection_repository.remove_image(
        session,
        collection_id,
        image_id,
    )

    if not success:
        raise HTTPException(status_code=404, detail="图片不在该收藏夹中")

    return {"message": "已从收藏夹移除"}


@router.get("/{collection_id}/images", response_model=dict[str, Any])
async def get_collection_images(
    collection_id: int,
    page: int = 1,
    size: int = 20,
    session: AsyncSession = Depends(get_async_session),
):
    """Get images in collection.

    Args:
        collection_id: Collection ID.
        page: Page number (from 1).
        size: Page size.
        session: Database session.

    Returns:
        Collection images with pagination.
    """
    return await image_collection_repository.get_collection_images(
        session,
        collection_id,
        limit=size,
        offset=(page - 1) * size,
    )


@router.get("/{collection_id}/random", response_model=dict[str, Any])
async def get_random_image(
    collection_id: int,
    tags: Optional[list[str]] = None,
    include_children: bool = False,
    session: AsyncSession = Depends(get_async_session),
):
    """Get random image from collection.

    Args:
        collection_id: Collection ID.
        tags: Optional tag filter.
        include_children: Include child collection images.
        session: Database session.

    Returns:
        Random image data.
    """
    image = await image_collection_repository.get_random_image(
        session,
        collection_id,
        tags=tags,
        include_children=include_children,
    )

    if not image:
        raise HTTPException(status_code=404, detail="未找到符合条件的图片")

    return image
