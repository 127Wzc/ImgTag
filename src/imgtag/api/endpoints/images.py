#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Image API endpoints.

Handles image CRUD, upload, search, and batch operations.
"""

import asyncio
import hashlib
import io
import os
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import get_current_user, require_admin
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository, image_tag_repository, tag_repository
from imgtag.models.image import Image
from imgtag.schemas import (
    ImageCreateByUrl,
    ImageCreateManual,
    ImageResponse,
    ImageSearchRequest,
    ImageSearchResponse,
    ImageUpdate,
    ImageWithSimilarity,
    SimilarSearchRequest,
    SimilarSearchResponse,
    UploadAnalyzeResponse,
)
from imgtag.services import embedding_service, upload_service
from imgtag.services.task_queue import task_queue

logger = get_logger(__name__)
perf_logger = get_perf_logger()


def get_owner_filter(user: dict) -> Optional[int]:
    """获取权限过滤的 owner_id。
    
    管理员返回 None (不过滤)，普通用户返回自己的 ID。
    """
    return None if user.get("role") == "admin" else user.get("id")


def check_image_permission(image: Image, user: dict, action: str = "操作") -> None:
    """检查用户是否有权限操作指定图片。"""
    if user.get("role") != "admin" and image.uploaded_by != user.get("id"):
        raise HTTPException(status_code=403, detail=f"无权{action}此图片")

router = APIRouter()


async def _get_display_url(image: Image) -> str:
    """根据 image_url_priority 配置返回正确的显示 URL。
    
    Args:
        image: Image model instance.
        
    Returns:
        str: 应该显示的图片 URL。
    """
    from imgtag.core.config_cache import config_cache
    from imgtag.services.s3_service import s3_service
    
    priority = await config_cache.get("image_url_priority", "auto")
    
    # 如果配置为 S3 优先 且有 S3 路径
    if priority == "s3" and image.s3_path and await s3_service.is_enabled():
        return await s3_service.get_public_url(image.s3_path)
    
    # 如果配置为 auto（S3 启用时优先 S3）
    if priority == "auto" and image.s3_path and await s3_service.is_enabled():
        return await s3_service.get_public_url(image.s3_path)
    
    # 默认返回本地 URL
    return image.image_url or ""


async def _image_to_response(
    image: Image,
    tags_with_source: list[dict] | None = None,
) -> ImageResponse:
    """Convert Image model to response schema.

    Args:
        image: Image model instance.
        tags_with_source: Optional tags with source info.

    Returns:
        ImageResponse schema.
    """
    display_url = await _get_display_url(image)
    
    return ImageResponse(
        id=image.id,
        image_url=display_url,
        file_path=image.file_path,
        file_hash=image.file_hash,
        file_type=image.file_type,
        file_size=float(image.file_size) if image.file_size else None,
        width=image.width,
        height=image.height,
        storage_type=image.storage_type,
        s3_path=image.s3_path,
        local_exists=image.local_exists,
        original_url=image.original_url,
        description=image.description,
        tags=tags_with_source or [],
        created_at=image.created_at,
        updated_at=image.updated_at,
        uploaded_by=image.uploaded_by,
    )


@router.post("/", response_model=dict[str, Any], status_code=201)
async def create_image_manual(
    image: ImageCreateManual,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Create image record manually (requires login).

    Args:
        image: Image creation data.
        user: Current user.
        session: Database session.

    Returns:
        Created image ID and process time.
    """
    start_time = time.time()
    logger.info(f"创建图像: {image.image_url}")

    try:
        # Generate vector embedding
        embedding_vector = await embedding_service.get_embedding_combined(
            image.description,
            image.tags,
        )

        # Create image record
        new_image = await image_repository.create_image(
            session,
            image_url=image.image_url,
            description=image.description,
            original_url=image.image_url,
            embedding=embedding_vector,
            uploaded_by=user.get("id"),
        )

        # Set tags
        if image.tags:
            await image_tag_repository.set_image_tags(
                session,
                new_image.id,
                image.tags,
                source="user",
                added_by=user.get("id"),
            )

        total_time = time.time() - start_time
        perf_logger.info(f"图像创建总耗时: {total_time:.4f}秒")

        return {
            "id": new_image.id,
            "message": "图像创建成功",
            "process_time": f"{total_time:.4f}秒",
        }
    except Exception as e:
        logger.error(f"创建图像失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建图像失败: {e}")


@router.post("/analyze-url", response_model=UploadAnalyzeResponse, status_code=201)
async def analyze_and_create_from_url(
    request: ImageCreateByUrl,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Analyze and create image from URL (requires login).

    Args:
        request: URL and analysis options.
        background_tasks: FastAPI background tasks.
        user: Current user.
        session: Database session.

    Returns:
        Created image response.
    """
    start_time = time.time()
    logger.info(f"添加远程图像任务: {request.image_url}")

    try:
        tags = request.tags or []
        description = request.description or ""

        # 下载远程图片到本地
        file_path, access_url, file_content = await upload_service.save_remote_image(request.image_url)
        
        # 提取图片尺寸
        width, height = upload_service.extract_image_dimensions(file_content)
        
        # 计算文件哈希和大小
        file_hash = hashlib.md5(file_content).hexdigest()
        file_size = round(len(file_content) / (1024 * 1024), 2)
        
        # 获取文件类型
        file_type = file_path.split(".")[-1] if "." in file_path else "jpg"

        # Create initial record with local path
        new_image = await image_repository.create_image(
            session,
            image_url=access_url,  # 本地访问路径
            file_path=file_path,    # 本地文件路径
            original_url=request.image_url,  # 原始 URL
            file_hash=file_hash,
            file_type=file_type,
            file_size=file_size,
            width=width,
            height=height,
            description=description,
            embedding=None,  # Pending analysis
            uploaded_by=user.get("id"),
        )

        # Set initial tags
        if tags:
            await image_tag_repository.set_image_tags(
                session,
                new_image.id,
                tags,
                source="user",
                added_by=user.get("id"),
            )

        # Queue for analysis
        if request.auto_analyze:
            await task_queue.add_tasks([new_image.id])
            if not task_queue._running:
                background_tasks.add_task(task_queue.start_processing)

        total_time = time.time() - start_time
        perf_logger.info(f"URL 图像添加任务耗时: {total_time:.4f}秒")

        return UploadAnalyzeResponse(
            id=new_image.id,
            image_url=access_url,  # 返回本地路径
            tags=tags,
            description=description,
            process_time=f"{total_time:.4f}秒",
        )
    except Exception as e:
        logger.error(f"添加图像任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加任务失败: {e}")


@router.post("/upload", response_model=UploadAnalyzeResponse, status_code=201)
async def upload_and_analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的图片文件"),
    auto_analyze: bool = Form(default=True, description="是否自动分析"),
    skip_analyze: bool = Form(default=False, description="跳过分析，只上传"),
    tags: str = Form(default="", description="手动标签，逗号分隔"),
    description: str = Form(default="", description="手动描述"),
    category_id: Optional[int] = Form(default=None, description="主分类ID"),
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Upload and analyze image file (requires login).

    Args:
        background_tasks: FastAPI background tasks.
        file: Uploaded image file.
        auto_analyze: Whether to auto-analyze.
        skip_analyze: Skip analysis, upload only.
        tags: Manual tags (comma-separated).
        description: Manual description.
        category_id: Category ID (level=0).
        user: Current user.
        session: Database session.

    Returns:
        Upload response with image ID.
    """
    start_time = time.time()
    logger.info(
        f"上传文件: {file.filename}, auto_analyze={auto_analyze}, "
        f"category_id={category_id}"
    )

    try:
        file_content = await file.read()

        # Save file
        file_path, access_url, file_type, width, height = (
            await upload_service.save_uploaded_file(file_content, file.filename)
        )

        final_tags = [t.strip() for t in tags.split(",") if t.strip()]
        final_description = description

        # Calculate hash and size
        file_hash = hashlib.md5(file_content).hexdigest()
        file_size = round(len(file_content) / (1024 * 1024), 2)

        # Create image record
        t1 = time.time()
        new_image = await image_repository.create_image(
            session,
            image_url=access_url,
            file_path=file_path,
            file_hash=file_hash,
            file_type=file_type,
            file_size=file_size,
            width=width,
            height=height,
            description=final_description,
            embedding=None,  # Pending analysis
            uploaded_by=user.get("id"),
        )
        perf_logger.debug(f"创建图片记录耗时: {time.time() - t1:.4f}秒")

        # Set initial tags
        if final_tags:
            t2 = time.time()
            await image_tag_repository.set_image_tags(
                session,
                new_image.id,
                final_tags,
                source="user",
                added_by=user.get("id"),
            )
            perf_logger.info(f"设置用户标签耗时: {time.time() - t2:.4f}秒")

        # Set category if provided
        if category_id:
            t3 = time.time()
            await image_tag_repository.add_tag_to_image(
                session,
                new_image.id,
                category_id,
                source="user",
                sort_order=0,
                added_by=user.get("id"),  # 添加用户ID
            )
            perf_logger.info(f"设置分类标签耗时: {time.time() - t3:.4f}秒")
        
        # Auto-set resolution tag based on image dimensions
        if width and height:
            resolution_name = upload_service.get_resolution_level(width, height)
            logger.info(f"分辨率判断: {width}x{height} -> {resolution_name}")
            if resolution_name != "unknown":
                t4 = time.time()
                # Get or create resolution tag (level=1)
                resolution_tag = await tag_repository.get_or_create(
                    session, resolution_name, source="system", level=1
                )
                logger.info(f"分辨率标签: id={resolution_tag.id}, name={resolution_tag.name}, level={resolution_tag.level}")
                perf_logger.info(f"获取/创建分辨率标签耗时: {time.time() - t4:.4f}秒")
                
                t5 = time.time()
                # Add to image
                await image_tag_repository.add_tag_to_image(
                    session,
                    new_image.id,
                    resolution_tag.id,
                    source="system",
                    sort_order=1,
                )
                perf_logger.info(f"关联分辨率标签耗时: {time.time() - t5:.4f}秒")

        # Queue for analysis
        if auto_analyze and not skip_analyze:
            t6 = time.time()
            await task_queue.add_tasks([new_image.id])
            perf_logger.info(f"添加队列任务耗时: {time.time() - t6:.4f}秒")
            if not task_queue._running:
                background_tasks.add_task(task_queue.start_processing)

        total_time = time.time() - start_time
        perf_logger.info(f"上传并添加任务耗时: {total_time:.4f}秒")

        return UploadAnalyzeResponse(
            id=new_image.id,
            image_url=access_url,
            tags=final_tags,
            description=final_description,
            process_time=f"{total_time:.4f}秒",
        )
    except Exception as e:
        logger.error(f"上传和添加任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.post("/upload-zip", response_model=dict[str, Any], status_code=201)
async def upload_zip(
    file: UploadFile = File(..., description="ZIP 压缩包"),
    category_id: Optional[int] = Form(default=None, description="主分类ID"),
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Upload ZIP file with images (requires login).

    Args:
        file: ZIP file.
        category_id: Category ID for all images.
        user: Current user.
        session: Database session.

    Returns:
        Upload results summary.
    """
    start_time = time.time()
    logger.info(f"上传 ZIP 文件: {file.filename}, category_id={category_id}")

    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="只支持 .zip 格式文件")

    try:
        zip_content = await file.read()
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

        uploaded_ids = []
        failed_files = []

        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as zf:
            for zip_info in zf.infolist():
                if zip_info.is_dir():
                    continue

                filename = os.path.basename(zip_info.filename)
                if filename.startswith(".") or filename.startswith("__"):
                    continue

                ext = os.path.splitext(filename)[1].lower()
                if ext not in image_extensions:
                    continue

                try:
                    file_content = zf.read(zip_info.filename)

                    file_path, access_url, file_type, width, height = (
                        await upload_service.save_uploaded_file(file_content, filename)
                    )

                    file_size = round(len(file_content) / (1024 * 1024), 2)
                    file_hash = hashlib.md5(file_content).hexdigest()

                    new_image = await image_repository.create_image(
                        session,
                        image_url=access_url,
                        file_path=file_path,
                        file_hash=file_hash,
                        file_type=file_type,
                        file_size=file_size,
                        width=width,
                        height=height,
                        embedding=None,
                        uploaded_by=user.get("id"),
                    )

                    if category_id:
                        await image_tag_repository.add_tag_to_image(
                            session,
                            new_image.id,
                            category_id,
                            source="user",
                            sort_order=0,
                        )

                    uploaded_ids.append(new_image.id)

                except Exception as e:
                    logger.error(f"处理 ZIP 内文件 {filename} 失败: {e}")
                    failed_files.append(filename)

        total_time = time.time() - start_time
        perf_logger.info(
            f"ZIP 上传处理耗时: {total_time:.4f}秒, "
            f"成功: {len(uploaded_ids)}, 失败: {len(failed_files)}"
        )

        return {
            "message": f"ZIP 解压完成: 成功 {len(uploaded_ids)} 张，"
            f"失败 {len(failed_files)} 张",
            "uploaded_count": len(uploaded_ids),
            "uploaded_ids": uploaded_ids,
            "failed_count": len(failed_files),
            "failed_files": failed_files[:10],
            "process_time": f"{total_time:.4f}秒",
        }
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的 ZIP 文件")
    except Exception as e:
        logger.error(f"处理 ZIP 文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理 ZIP 失败: {e}")


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: int,
    session: AsyncSession = Depends(get_async_session),
):
    """Get single image information.

    Args:
        image_id: Image ID.
        session: Database session.

    Returns:
        ImageResponse.
    """
    start_time = time.time()
    logger.info(f"获取图像: ID {image_id}")

    try:
        image = await image_repository.get_with_tags(session, image_id)

        if not image:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")

        tags_with_source = await image_repository.get_image_tags_with_source(
            session, image_id
        )

        process_time = time.time() - start_time
        perf_logger.info(f"获取图像耗时: {process_time:.4f}秒")

        return await _image_to_response(image, tags_with_source)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图像失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图像失败: {e}")


@router.post("/search", response_model=ImageSearchResponse)
async def search_images(
    request: ImageSearchRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Advanced image search.

    Args:
        request: Search filters.
        session: Database session.

    Returns:
        ImageSearchResponse with results.
    """
    start_time = time.time()
    logger.info(f"高级图像搜索: {request.model_dump()}")

    try:
        results = await image_repository.search_images(
            session,
            tags=request.tags,
            keyword=request.keyword,
            category_id=request.category_id,
            resolution_id=request.resolution_id,
            pending_only=request.pending_only,
            duplicates_only=request.duplicates_only,
            limit=request.limit,
            offset=request.offset,
            sort_by=request.sort_by,
            sort_desc=request.sort_desc,
        )

        # 批量获取标签信息（包含 level 和 source）
        image_ids = [img.id for img in results["images"]]
        tags_map = await image_repository.get_batch_image_tags_with_source(
            session, image_ids
        )

        # Convert to response with tags_with_source
        images = await asyncio.gather(*[
            _image_to_response(img, tags_with_source=tags_map.get(img.id, []))
            for img in results["images"]
        ])

        response = ImageSearchResponse(
            images=images,
            total=results["total"],
            limit=results["limit"],
            offset=results["offset"],
        )

        process_time = time.time() - start_time
        perf_logger.info(f"高级搜索耗时: {process_time:.4f}秒")

        return response
    except Exception as e:
        logger.error(f"高级搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")


@router.post("/smart-search", response_model=SimilarSearchResponse)
async def smart_search(
    request: SimilarSearchRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Smart vector search with similarity scores.

    Uses hybrid search combining vector similarity and tag matching.

    Args:
        request: Search parameters with text query.
        session: Database session.

    Returns:
        SimilarSearchResponse with similarity scores.
    """
    start_time = time.time()
    logger.info(f"智能向量搜索: '{request.text[:50] if request.text else ''}...'")

    try:
        # Generate query vector
        if request.tags:
            query_vector = await embedding_service.get_embedding_combined(
                request.text,
                request.tags,
            )
        else:
            query_vector = await embedding_service.get_embedding(request.text)

        # Execute hybrid search
        results = await image_repository.hybrid_search(
            session,
            query_vector=query_vector,
            query_text=request.text,
            limit=request.limit,
            threshold=request.threshold,
            vector_weight=request.vector_weight,
            tag_weight=request.tag_weight,
            category_id=request.category_id,
            resolution_id=request.resolution_id,
        )

        # Convert to response model
        images = [ImageWithSimilarity(**img) for img in results]

        response = SimilarSearchResponse(
            images=images,
            total=len(images),
        )

        process_time = time.time() - start_time
        perf_logger.info(f"智能向量搜索耗时: {process_time:.4f}秒")

        return response
    except Exception as e:
        logger.error(f"智能向量搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")


@router.post("/my", response_model=ImageSearchResponse)
async def get_my_images(
    request: ImageSearchRequest,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Get current user's uploaded images (requires login).

    Automatically filters by the current user's ID.
    Admin users can optionally use the all_users query param to see all images.

    Args:
        request: Search filters.
        user: Current user (injected from token).
        session: Database session.

    Returns:
        ImageSearchResponse with user's images.
    """
    start_time = time.time()
    current_user_id = user.get("id")
    is_admin = user.get("role") == "admin"
    
    logger.info(f"获取用户图片: user_id={current_user_id}, is_admin={is_admin}")

    try:
        # For non-admin users, always filter by their own user_id
        # For admin users, also filter by their own user_id (admin can use /search for all)
        results = await image_repository.search_images(
            session,
            tags=request.tags,
            keyword=request.keyword,
            category_id=request.category_id,
            resolution_id=request.resolution_id,
            user_id=current_user_id,  # Always filter by current user
            pending_only=request.pending_only,
            duplicates_only=request.duplicates_only,
            limit=request.limit,
            offset=request.offset,
            sort_by=request.sort_by,
            sort_desc=request.sort_desc,
        )

        # 批量获取标签信息
        image_ids = [img.id for img in results["images"]]
        tags_map = await image_repository.get_batch_image_tags_with_source(
            session, image_ids
        )

        images = await asyncio.gather(*[
            _image_to_response(img, tags_with_source=tags_map.get(img.id, []))
            for img in results["images"]
        ])

        response = ImageSearchResponse(
            images=images,
            total=results["total"],
            limit=results["limit"],
            offset=results["offset"],
        )

        process_time = time.time() - start_time
        perf_logger.info(f"获取用户图片耗时: {process_time:.4f}秒")

        return response
    except Exception as e:
        logger.error(f"获取用户图片失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取用户图片失败: {e}")


@router.put("/{image_id}", response_model=dict[str, Any])
async def update_image(
    image_id: int,
    image_update: ImageUpdate,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Update image information (requires login).

    Args:
        image_id: Image ID.
        image_update: Update data.
        current_user: Current user.
        session: Database session.

    Returns:
        Update confirmation.
    """
    start_time = time.time()
    logger.info(f"更新图像: ID {image_id}")

    try:
        image = await image_repository.get_by_id(session, image_id)
        if not image:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")

        check_image_permission(image, current_user, "编辑")

        # 判断是否有标签更新
        has_tag_update = image_update.tag_ids is not None or image_update.tags is not None
        has_desc_update = image_update.description is not None
        
        # 获取标签名列表用于计算 embedding
        tag_names_for_embedding: list[str] = []
        tag_ids_to_set: list[int] | None = None
        
        if image_update.tag_ids is not None:
            # 优先使用 tag_ids（新流程）
            tag_ids_to_set = image_update.tag_ids
            # 查询标签名用于 embedding
            if tag_ids_to_set:
                from sqlalchemy import select
                from imgtag.models.tag import Tag
                stmt = select(Tag.name).where(Tag.id.in_(tag_ids_to_set))
                result = await session.execute(stmt)
                tag_names_for_embedding = [row.name for row in result]
        elif image_update.tags is not None:
            # 兼容旧流程（按标签名）
            tag_names_for_embedding = image_update.tags

        # Recalculate embedding if tags or description changed
        embedding_vector = None
        if has_tag_update or has_desc_update:
            description = (
                image_update.description
                if image_update.description is not None
                else (image.description or "")
            )
            
            # 如果没有标签更新，查询当前标签
            if not has_tag_update:
                current_tag_objs = await image_tag_repository.get_image_tags(session, image_id)
                tag_names_for_embedding = [t.name for t in current_tag_objs]

            embedding_vector = await embedding_service.get_embedding_combined(
                description, tag_names_for_embedding
            )

        # Update image basic info
        await image_repository.update_image(
            session,
            image,
            image_url=image_update.image_url,
            description=image_update.description,
            embedding=embedding_vector,
            original_url=image_update.original_url,
        )

        # Update tags
        if tag_ids_to_set is not None:
            # 新流程：按 ID 更新标签关联
            logger.info(f"更新标签关联: image_id={image_id}, tag_ids={tag_ids_to_set}")
            changes = await image_tag_repository.set_image_tags_by_ids(
                session,
                image_id,
                tag_ids_to_set,
                source="user",
                added_by=current_user.get("id"),
            )
            logger.info(f"标签关联更新完成: changes={changes}")
        elif image_update.tags is not None:
            # 旧流程：按名称更新（兼容）
            await image_tag_repository.set_image_tags(
                session,
                image_id,
                image_update.tags,
                source="user",
                added_by=current_user.get("id"),
            )

        process_time = time.time() - start_time
        perf_logger.info(f"图像更新总耗时: {process_time:.4f}秒")

        return {
            "message": "图像更新成功",
            "process_time": f"{process_time:.4f}秒",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新图像失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新图像失败: {e}")


@router.delete("/{image_id}", response_model=dict[str, Any])
async def delete_image(
    image_id: int,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete image (requires login).

    Args:
        image_id: Image ID.
        user: Current user.
        session: Database session.

    Returns:
        Delete confirmation.
    """
    start_time = time.time()
    logger.info(f"删除图像: ID {image_id}")

    try:
        image = await image_repository.get_by_id(session, image_id)

        if not image:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")

        check_image_permission(image, user, "删除")

        # Delete local file
        file_path = image.file_path
        file_deleted = False

        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                file_deleted = True
                logger.info(f"已删除本地文件: {file_path}")
            except Exception as e:
                logger.warning(f"删除本地文件失败: {file_path}, 错误: {e}")

        # Delete database record
        await image_repository.delete(session, image)

        process_time = time.time() - start_time
        perf_logger.info(f"删除图像耗时: {process_time:.4f}秒")

        msg = f"图像 ID:{image_id} 删除成功"
        if file_deleted:
            msg += " (含本地文件)"

        return {
            "message": msg,
            "file_deleted": file_deleted,
            "process_time": f"{process_time:.4f}秒",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除图像失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除图像失败: {e}")


@router.post("/batch/delete", response_model=dict[str, Any])
async def batch_delete_images(
    image_ids: list[int],
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Batch delete images (requires login).

    Uses bulk WHERE IN() query instead of N individual queries.

    Args:
        image_ids: List of image IDs.
        user: Current user.
        session: Database session.

    Returns:
        Deletion results.
    """
    start_time = time.time()
    logger.info(f"批量删除图像: {len(image_ids)} 张")

    if not image_ids:
        return {
            "message": "未提供图片ID",
            "success_count": 0,
            "fail_count": 0,
            "process_time": "0秒",
        }

    try:
        # Bulk delete with permission filter (SQL 层过滤)
        deleted_count, file_paths = await image_repository.delete_by_ids(
            session, image_ids, owner_id=get_owner_filter(user)
        )

        # Delete local files (after DB transaction commits)
        files_deleted = 0
        for file_path in file_paths:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    files_deleted += 1
                except Exception:
                    pass

        process_time = time.time() - start_time
        perf_logger.info(f"批量删除耗时: {process_time:.4f}秒")

        fail_count = len(image_ids) - deleted_count

        return {
            "message": f"批量删除完成: 成功 {deleted_count} 张，失败 {fail_count} 张",
            "success_count": deleted_count,
            "fail_count": fail_count,
            "files_deleted": files_deleted,
            "process_time": f"{process_time:.4f}秒",
        }
    except Exception as e:
        logger.error(f"批量删除失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量删除失败: {e}")


class BatchUpdateTagsRequest(BaseModel):
    """Request for batch tag update."""

    image_ids: list[int]
    tags: list[str]
    mode: str = "add"  # add: append, replace: replace


@router.post("/batch/update-tags", response_model=dict[str, Any])
async def batch_update_tags(
    request: BatchUpdateTagsRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Batch update image tags (requires login).

    Uses bulk WHERE IN() operations instead of N loops.

    Args:
        request: Batch update request.
        current_user: Current user.
        session: Database session.

    Returns:
        Update results.
    """
    start_time = time.time()
    user_id = current_user.get("id")
    logger.info(
        f"批量更新标签: {len(request.image_ids)} 张, "
        f"模式: {request.mode}, 用户: {user_id}"
    )

    if not request.image_ids:
        return {
            "message": "未提供图片ID",
            "success_count": 0,
            "fail_count": 0,
            "process_time": "0秒",
        }

    try:
        # Bulk tag operation with permission filter (SQL 层过滤)
        owner_id = get_owner_filter(current_user)
        
        if request.mode == "add":
            updated = await image_tag_repository.batch_add_tags_to_images(
                session,
                request.image_ids,
                request.tags,
                source="user",
                added_by=user_id,
                owner_id=owner_id,
            )
        else:
            updated = await image_tag_repository.batch_replace_tags_for_images(
                session,
                request.image_ids,
                request.tags,
                source="user",
                added_by=user_id,
                owner_id=owner_id,
            )

        process_time = time.time() - start_time
        perf_logger.info(f"批量更新标签耗时: {process_time:.4f}秒")

        # 计算实际更新的数量
        success_count = len(request.image_ids) if owner_id is None else updated

        return {
            "message": f"批量更新完成: {success_count} 张图片",
            "success_count": success_count,
            "fail_count": 0,
            "tags_updated": updated,
            "process_time": f"{process_time:.4f}秒",
        }
    except Exception as e:
        logger.error(f"批量更新标签失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量更新标签失败: {e}")


class BatchSetCategoryRequest(BaseModel):
    """Request for batch category update."""

    image_ids: list[int]
    category_id: int  # Target category tag_id (level=0)


@router.post("/batch/set-category", response_model=dict[str, Any])
async def batch_set_category(
    request: BatchSetCategoryRequest,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Batch set image category (admin only).

    Uses bulk WHERE IN() operations instead of N loops.

    Args:
        request: Batch category request.
        admin: Admin user.
        session: Database session.

    Returns:
        Update results.
    """
    start_time = time.time()
    logger.info(
        f"批量设置主分类: {len(request.image_ids)} 张图片 -> "
        f"分类ID {request.category_id}"
    )

    # Verify category exists and is level=0
    category = await tag_repository.get_by_id(session, request.category_id)
    if not category:
        raise HTTPException(status_code=404, detail="目标分类不存在")
    if category.level != 0:
        raise HTTPException(status_code=400, detail="目标标签不是主分类 (level=0)")

    if not request.image_ids:
        return {
            "message": "未提供图片ID",
            "success_count": 0,
            "fail_count": 0,
            "process_time": "0秒",
        }

    try:
        # Bulk delete old level=0 tags: O(1) query
        del_stmt = (
            sa_delete(ImageTag)
            .where(
                ImageTag.image_id.in_(request.image_ids),
                ImageTag.tag_id.in_(select(Tag.id).where(Tag.level == 0)),
            )
        )
        await session.execute(del_stmt)

        # Bulk insert new category: O(1) query
        now = datetime.now(timezone.utc)
        insert_data = [
            {
                "image_id": image_id,
                "tag_id": request.category_id,
                "source": "user",
                "sort_order": 0,
                "added_at": now,
            }
            for image_id in request.image_ids
        ]

        insert_stmt = pg_insert(ImageTag).values(insert_data)
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=["image_id", "tag_id"]
        )
        await session.execute(insert_stmt)
        await session.flush()

        process_time = time.time() - start_time
        perf_logger.info(f"批量设置分类耗时: {process_time:.4f}秒")

        return {
            "message": f"批量设置主分类完成: {len(request.image_ids)} 张图片",
            "success_count": len(request.image_ids),
            "fail_count": 0,
            "category_name": category.name,
            "process_time": f"{process_time:.4f}秒",
        }
    except Exception as e:
        logger.error(f"批量设置分类失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量设置分类失败: {e}")


# Import Tag model for subquery
from imgtag.models.tag import Tag, ImageTag
from sqlalchemy import select
