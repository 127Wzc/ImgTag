#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""External API endpoints.

Third-party integration using API key authentication.
"""

import asyncio
import hashlib
import time
from datetime import datetime, timezone as tz
from math import ceil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.dependencies import require_api_key
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.api.permission_guards import ensure_create_tags_if_missing, ensure_permission
from imgtag.core.permissions import Permission
from imgtag.core.storage_constants import StorageProvider
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    image_location_repository,
    image_repository,
    image_tag_repository,
    storage_endpoint_repository,
    tag_repository,
)
from imgtag.core.category_cache import get_category_code_cached
from imgtag.services import embedding_service
from imgtag.services.backup_service import trigger_backup_for_image
from imgtag.services.storage_service import storage_service
from imgtag.services.task_queue import task_queue
from imgtag.services.upload_service import upload_service

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()


class ExternalImageCreate(BaseModel):
    """External API image create request.
    
    标签处理逻辑：
    - 若同时提供 tags 和 description，跳过 AI 分析，只生成向量嵌入
    - 若只提供 tags，先保存为用户标签(source=user)，再进行 AI 分析
    - AI 分析的标签会与用户标签合并，重名标签优先保留用户标签
    - 若都不指定，正常进行 AI 分析
    """

    image_url: str = Field(..., description="图片URL")
    tags: list[str] = Field(default=[], description="用户自定义标签列表")
    description: str = Field(default="", description="用户提供的描述")
    category_id: int | None = Field(default=None, description="主分类ID")
    endpoint_id: int | None = Field(default=None, description="目标存储端点ID")
    auto_analyze: bool = Field(default=True, description="是否启用 AI 分析")
    callback_url: str | None = Field(default=None, description="分析完成后的回调URL")
    is_public: bool = Field(default=True, description="是否公开可见")



@router.get("/images/random")
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


@router.post("/images")
async def analyze_image_from_url(
    request: ExternalImageCreate,
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Add and analyze image from URL.

    Downloads image, saves to specified endpoint (or local), queues for analysis.

    Args:
        request: Image URL and options.
        api_user: API user.
        session: Database session.

    Returns:
        Created image info. If wait_for_result=True, includes AI-generated tags and description.
    """
    
    start_time = time.time()
    username = api_user.get("username")
    logger.info(f"[外部API] 添加图片: {request.image_url}, user={username}")

    try:
        await ensure_create_tags_if_missing(session, api_user, request.tags)

        # 权限校验需在上传/落库前完成，避免产生副作用
        skip_analyze = not request.auto_analyze  # 绝对优先级
        has_valid_tags = bool([t for t in request.tags if t and t.strip()])
        has_valid_description = bool(request.description and request.description.strip())
        user_provided_full = has_valid_tags and has_valid_description
        need_analysis = request.auto_analyze and not user_provided_full
        if need_analysis:
            ensure_permission(api_user, Permission.AI_ANALYZE)

        # 获取目标端点
        target_endpoint, err = await storage_endpoint_repository.resolve_upload_endpoint(
            session, request.endpoint_id
        )
        if err:
            raise HTTPException(400, err)
        
        # Download and save image
        file_path, local_url, content = await upload_service.save_remote_image(
            request.image_url
        )

        # Calculate hash and size
        file_hash = await asyncio.to_thread(lambda: hashlib.md5(content).hexdigest())
        file_size = round(len(content) / (1024 * 1024), 2)
        
        # 提取图片尺寸（PIL 操作移至线程池，避免阻塞）
        width, height = await asyncio.to_thread(
            upload_service.extract_image_dimensions, content
        )
        file_type = file_path.split(".")[-1] if "." in file_path else "jpg"

        new_image = await image_repository.create_image(
            session,
            file_hash=file_hash,
            file_type=file_type,
            file_size=file_size,
            width=width,
            height=height,
            description=request.description,
            original_url=request.image_url,
            embedding=None,
            uploaded_by=api_user.get("id"),
            is_public=request.is_public,
        )
        
        # 生成统一的 object_key
        object_key = storage_service.generate_object_key(file_hash, file_type)
        
        # 获取分类代码（如果指定了分类）
        category_code = None
        if request.category_id:
            category_code = await get_category_code_cached(session, request.category_id)
        
        full_object_key = storage_service.get_full_object_key(object_key, category_code)
        
        # 上传到目标端点
        upload_success = await storage_service.upload_to_endpoint(
            content, full_object_key, target_endpoint
        )
        if not upload_success:
            raise HTTPException(500, f"上传到端点 {target_endpoint.name} 失败")
        
        # 创建 ImageLocation 记录
        await image_location_repository.create(
            session,
            image_id=new_image.id,
            endpoint_id=target_endpoint.id,
            object_key=full_object_key,
            category_code=category_code,
            is_primary=True,
            sync_status="synced",
            synced_at=datetime.now(tz.utc),
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
        
        # Set category tag if provided
        if request.category_id:
            await image_tag_repository.add_tag_to_image(
                session,
                new_image.id,
                request.category_id,
                source="user",
                sort_order=0,
                added_by=api_user.get("id"),
            )
        
        # Set resolution tag
        if width and height:
            resolution_name = upload_service.get_resolution_level(width, height)
            if resolution_name != "unknown":
                resolution_tag = await tag_repository.get_or_create(
                    session, resolution_name, source="system", level=1
                )
                await image_tag_repository.add_tag_to_image(
                    session, new_image.id, resolution_tag.id, source="system", sort_order=1
                )
        
        await session.commit()
        
        # 触发自动备份到备份端点（必须在 commit 之后）
        asyncio.create_task(
            trigger_backup_for_image(new_image.id, target_endpoint.id)
        )

        # 判断是否需要 AI 分析
        if need_analysis:
            # 加入 AI 分析任务队列
            # - 如果用户提供了部分标签，AI 会补充并合并
            await task_queue.add_tasks(
                [new_image.id], 
                callback_url=request.callback_url,
            )
        elif user_provided_full:
            # 用户已提供完整内容，只需生成向量（后台执行）
            asyncio.create_task(
                embedding_service.save_embedding_for_image(
                    new_image.id, request.description, request.tags
                )
            )

        process_time = time.time() - start_time
        
        display_url = await storage_service.get_read_url(new_image) or ""
        
        # 获取当前标签（用户标签 + 分类 + 分辨率）
        final_tags = await image_repository.get_image_tags_with_source(session, new_image.id)

        return {
            "id": new_image.id,
            "image_url": display_url,
            "original_url": request.image_url,
            "tags": final_tags,
            "description": new_image.description or request.description,
            "width": width,
            "height": height,
            "skip_analyze": skip_analyze,
            "process_time": f"{process_time:.4f}秒",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[外部API] 添加图片失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加失败: {e}")


@router.get("/images/search")
async def search_images(
    keyword: str = Query(None, description="关键词搜索"),
    tags: list[str] = Query([], description="标签筛选"),
    page: int = Query(1, ge=1, description="页码 (从 1 开始)"),
    size: int = Query(20, ge=1, le=100, description="每页数量"),
    threshold: float = Query(0.7, ge=0.0, le=1.0, description="相似度阈值（用于向量搜索）"),
    api_user: dict = Depends(require_api_key),
    session: AsyncSession = Depends(get_async_session),
):
    """Search images.

    Uses existing search_images Repository method.

    Args:
        keyword: Keyword search.
        tags: Tag filter.
        page: Page number (from 1).
        size: Page size.
        api_user: API user.
        session: Database session.

    Returns:
        Search results.
    """
    username = api_user.get("username")
    logger.info(f"[外部API] 搜索图片: keyword={keyword}, tags={tags}, user={username}")

    try:
        offset = (page - 1) * size
        result = await image_repository.search_images(
            session,
            tags=tags if tags else None,
            keyword=keyword,
            limit=size,
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
                "created_at": img.created_at.isoformat() if img.created_at else None,
            })

        total = result["total"]
        pages = ceil(total / size) if size > 0 else 0
        
        return {
            "data": images,
            "total": total,
            "page": page,
            "size": size,
            "pages": pages,
            "has_next": page < pages,
            "has_prev": page > 1,
        }
    except Exception as e:
        logger.error(f"[外部API] 搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")


@router.get("/images/{image_id}")
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
        "created_at": image.created_at.isoformat() if image.created_at else None,
    }
