#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""External API endpoints.

Third-party integration using API key authentication.
"""

import asyncio
import hashlib
import time
from datetime import datetime, timezone as tz
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.dependencies import require_api_key
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.core.storage_constants import StorageProvider
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    image_location_repository,
    image_repository,
    image_tag_repository,
    storage_endpoint_repository,
)
from imgtag.services.storage_service import storage_service
from imgtag.services.task_queue import task_queue
from imgtag.services.upload_service import upload_service

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()


class ExternalImageCreate(BaseModel):
    """External API image create request."""

    image_url: str
    tags: list[str] = []
    description: str = ""
    auto_analyze: bool = True



@router.get("/random")
async def random_images(
    tags: list[str] = Query([], description="标签列表（AND 关系）"),
    count: int = Query(1, ge=1, le=50, description="返回数量"),
    include_full_url: bool = Query(True, description="是否返回完整 URL"),
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Get random images by tags.

    Single query with JOIN for performance.

    Args:
        tags: Tag filter (AND logic).
        count: Number of images.
        include_full_url: Whether to include full URL.
        api_user: API user.
        session: Database session.

    Returns:
        Random images list.
    """
    start_time = time.time()
    username = api_user.get("username")
    logger.info(f"[外部API] 随机图片请求: tags={tags}, count={count}, user={username}")

    try:
        # Single query with optional tag filter
        result = await image_repository.get_random_by_tags(session, tags, count)

        # Process URLs - format determined by endpoint's public_url_prefix
        images = []
        for img in result:
            images.append({
                "id": img["id"],
                "url": img["image_url"],
                "description": img["description"],
                "tags": img["tags"],
            })

        process_time = time.time() - start_time
        perf_logger.info(f"[外部API] 随机图片查询耗时: {process_time:.4f}秒")

        return {"images": images, "count": len(images)}
    except Exception as e:
        logger.error(f"[外部API] 随机图片查询失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")


@router.post("/add-image")
async def analyze_image_from_url(
    request: ExternalImageCreate,
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Add and analyze image from URL.

    Downloads image, saves locally, queues for analysis.

    Args:
        request: Image URL and options.
        api_user: API user.
        session: Database session.

    Returns:
        Created image info.
    """
    start_time = time.time()
    username = api_user.get("username")
    logger.info(f"[外部API] 添加图片: {request.image_url}, user={username}")

    try:
        # Download and save image
        file_path, local_url, content = await upload_service.save_remote_image(
            request.image_url
        )

        # Calculate hash and size
        file_hash = await asyncio.to_thread(lambda: hashlib.md5(content).hexdigest())
        file_size = round(len(content) / (1024 * 1024), 2)

        # Create image record (without legacy fields)
        new_image = await image_repository.create_image(
            session,
            file_hash=file_hash,
            file_size=file_size,
            description=request.description,
            original_url=request.image_url,
            embedding=None,
            uploaded_by=api_user.get("id"),
        )
        
        # Create local ImageLocation record
        local_endpoint = await storage_endpoint_repository.get_by_name(session, StorageProvider.LOCAL)
        if local_endpoint:
            local_object_key = file_path.replace("\\", "/").lstrip("/")
            if local_object_key.startswith("uploads/"):
                local_object_key = local_object_key[8:]
            
            await image_location_repository.create(
                session,
                image_id=new_image.id,
                endpoint_id=local_endpoint.id,
                object_key=local_object_key,
                is_primary=True,
                sync_status="synced",
                synced_at=datetime.now(tz),
            )

        # Set tags if provided
        if request.tags:
            await image_tag_repository.set_image_tags(
                session,
                new_image.id,
                request.tags,
                source="user",
                added_by=api_user.get("id"),
            )

        # Queue for analysis if requested
        if request.auto_analyze:
            await task_queue.add_tasks([new_image.id])

        process_time = time.time() - start_time
        
        # Get display URL from storage service
        display_url = await storage_service.get_read_url(new_image) or ""

        return {
            "id": new_image.id,
            "image_url": display_url,
            "original_url": request.image_url,
            "tags": request.tags,
            "description": request.description,
            "process_time": f"{process_time:.4f}秒",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[外部API] 添加图片失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加失败: {e}")


@router.get("/image/{image_id}")
async def get_image_info(
    image_id: int,
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Get image details.

    Args:
        image_id: Image ID.
        api_user: API user.
        session: Database session.

    Returns:
        Image details.
    """
    username = api_user.get("username")
    logger.info(f"[外部API] 获取图片: id={image_id}, user={username}")

    image = await image_repository.get_with_tags(session, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")

    # Get display URL from storage service
    display_url = await storage_service.get_read_url(image) or ""

    return {
        "id": image.id,
        "url": display_url,
        "description": image.description or "",
        "tags": [t.name for t in image.tags if t.level == 2],
        "created_at": image.created_at,
    }


@router.get("/search")
async def search_images(
    keyword: str = Query(None, description="关键词搜索"),
    tags: list[str] = Query([], description="标签筛选"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Search images.

    Uses existing search_images Repository method.

    Args:
        keyword: Keyword search.
        tags: Tag filter.
        limit: Max results.
        offset: Pagination offset.
        api_user: API user.
        session: Database session.

    Returns:
        Search results.
    """
    username = api_user.get("username")
    logger.info(f"[外部API] 搜索图片: keyword={keyword}, tags={tags}, user={username}")

    try:
        result = await image_repository.search_images(
            session,
            tags=tags if tags else None,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )

        # Batch get URLs from storage service
        result_images = result["images"]
        urls = await storage_service.get_read_urls(result_images)
        
        # Process results - URL format determined by endpoint config
        images = []
        for img in result_images:
            images.append({
                "id": img.id,
                "image_url": urls.get(img.id, ""),
                "description": img.description or "",
                "tags": [t.name for t in img.tags] if hasattr(img, "tags") else [],
                "created_at": img.created_at,
            })

        return {
            "images": images,
            "total": result["total"],
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"[外部API] 搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")
