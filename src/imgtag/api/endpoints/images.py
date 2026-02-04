#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Image API endpoints.

Handles image CRUD, upload, search, and batch operations.
"""

import asyncio
import hashlib
import io
import logging
import os
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy import and_, delete as sa_delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import get_current_user, get_current_user_optional, require_admin, require_permission
from imgtag.api.permission_guards import ensure_create_tags_if_missing, ensure_permission
from imgtag.core.permissions import Permission
from imgtag.core.category_cache import get_category_code_cached
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.core.storage_constants import (
    StorageProvider,
    get_extension_from_mime,
    SUPPORTED_IMAGE_EXTENSIONS,
)
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    image_location_repository,
    image_repository,
    image_tag_repository,
    storage_endpoint_repository,
    tag_repository,
)
from imgtag.models.image import Image
from imgtag.models.tag import Tag, ImageTag
from imgtag.schemas import (
    ImageCreateByUrl,
    ImageCreateManual,
    ImageResponse,
    ImageSearchRequest,
    ImageSearchResponse,
    ImageUpdate,
    ImageUpdateSuggestion,
    ImageWithSimilarity,
    SimilarSearchRequest,
    SimilarSearchResponse,
    UploadAnalyzeResponse,
    PaginatedResponse,
)
from imgtag.services import embedding_service, storage_service, upload_service
from imgtag.services.suggestion_service import suggestion_service
from imgtag.services.backup_service import trigger_backup_for_image
from imgtag.services.task_queue import task_queue
from imgtag.utils.pagination import PageParams

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
    """从存储端点获取图片访问 URL。
    
    URL 格式由端点的 public_url_prefix 和 bucket_name 决定。
    
    Args:
        image: Image model instance.
        
    Returns:
        str: 图片访问 URL。
    """
    try:
        return await storage_service.get_read_url(image) or ""
    except Exception:
        return ""




async def _image_to_response(
    image: Image,
    tags_with_source: list[dict] | None = None,
    display_url: str | None = None,
) -> ImageResponse:
    """Convert Image model to response schema.

    Args:
        image: Image model instance.
        tags_with_source: Optional tags with source info.
        display_url: Pre-computed display URL (for batch optimization).

    Returns:
        ImageResponse schema.
    """
    if display_url is None:
        display_url = await _get_display_url(image)
    
    return ImageResponse(
        id=image.id,
        image_url=display_url,
        file_hash=image.file_hash,
        file_type=image.file_type,
        file_size=float(image.file_size) if image.file_size else None,
        width=image.width,
        height=image.height,
        original_url=image.original_url,
        description=image.description,
        tags=tags_with_source or [],
        is_public=image.is_public,
        created_at=str(image.created_at) if image.created_at else None,
        updated_at=str(image.updated_at) if image.updated_at else None,
        uploaded_by=image.uploaded_by,
        uploaded_by_username=image.uploader.username if image.uploader else None,
    )



async def _images_to_responses(
    images: list[Image],
    tags_map: dict[int, list[dict]],
) -> list[ImageResponse]:
    """Convert multiple Image models to response schemas efficiently.
    
    Batches URL retrieval to avoid N+1 queries.
    URLs are fully managed by storage_service based on endpoint configuration.

    Args:
        images: List of Image model instances.
        tags_map: Dictionary mapping image_id to tags with source info.

    Returns:
        List of ImageResponse schemas.
    """
    if not images:
        return []
    
    # Batch get URLs from storage endpoints
    # URL format is determined by each endpoint's public_url_prefix or default path
    urls = await storage_service.get_read_urls(images)
    
    # Build responses
    responses = []
    for img in images:
        display_url = urls.get(img.id, "")
        
        responses.append(ImageResponse(
            id=img.id,
            image_url=display_url,
            file_hash=img.file_hash,
            file_type=img.file_type,
            file_size=float(img.file_size) if img.file_size else None,
            width=img.width,
            height=img.height,
            original_url=img.original_url,
            description=img.description,
            tags=tags_map.get(img.id, []),
            is_public=img.is_public,
            created_at=str(img.created_at) if img.created_at else None,
            updated_at=str(img.updated_at) if img.updated_at else None,
            uploaded_by=img.uploaded_by,
            uploaded_by_username=img.uploader.username if img.uploader else None,
        ))
    
    return responses




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
        await ensure_create_tags_if_missing(session, user, image.tags)

        # Generate vector embedding
        embedding_vector = await embedding_service.get_embedding_combined(
            image.description,
            image.tags,
        )

        # Create image record (without legacy fields)
        new_image = await image_repository.create_image(
            session,
            description=image.description,
            original_url=image.image_url,  # Store provided URL as original_url
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建图像失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建图像失败: {e}")


@router.post("/analyze-url", response_model=UploadAnalyzeResponse, status_code=201)
async def analyze_and_create_from_url(
    request: ImageCreateByUrl,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Analyze and create image from URL (admin only).

    Supports specifying target storage endpoint or using system default.
    Category subdirectory is automatically applied if category_id is provided.

    Args:
        request: URL and upload options.
        background_tasks: FastAPI background tasks.
        user: Current user.
        session: Database session.

    Returns:
        Created image response.
    """
    start_time = time.time()
    logger.info(
        f"添加远程图像: {request.image_url}, endpoint_id={request.endpoint_id}, "
        f"category_id={request.category_id}, is_public={request.is_public}"
    )

    try:
        tags = request.tags or []
        description = request.description or ""

        # 下载远程图片（流式获取内容，不保存中间文件）
        file_content, mime_type = await upload_service.fetch_remote_image(request.image_url)
        
        # 计算文件哈希和大小 (线程池执行避免阻塞)
        file_hash = await asyncio.to_thread(lambda: hashlib.md5(file_content).hexdigest())
        file_size = round(len(file_content) / (1024 * 1024), 2)
        
        # 根据 MIME 类型确定扩展名（使用统一常量）
        file_type = get_extension_from_mime(mime_type)
        
        # 提取图片尺寸（PIL 操作移至线程池，避免阻塞）
        width, height = await asyncio.to_thread(
            upload_service.extract_image_dimensions, file_content
        )

        # Get target endpoint (use specified or default)
        target_endpoint, err = await storage_endpoint_repository.resolve_upload_endpoint(
            session, request.endpoint_id
        )
        if err:
            raise HTTPException(400, err)

        # Get category code for subdirectory (if category specified)
        category_code = None
        if request.category_id:
            category_code = await get_category_code_cached(session, request.category_id)
        
        # Generate object key (hash-based path)
        object_key = storage_service.generate_object_key(file_hash, file_type)
        full_object_key = storage_service.get_full_object_key(object_key, category_code)
        
        # Upload to target endpoint
        upload_success = await storage_service.upload_to_endpoint(
            file_content, full_object_key, target_endpoint
        )
        
        # Fallback to local if remote upload fails
        if not upload_success:
            logger.warning(f"上传到端点 {target_endpoint.name} 失败，尝试本地存储")
            local_endpoint = await storage_endpoint_repository.get_by_name(session, StorageProvider.LOCAL)
            if local_endpoint:
                target_endpoint = local_endpoint
                upload_success = await storage_service.upload_to_endpoint(
                    file_content, full_object_key, target_endpoint
                )
        
        if not upload_success:
            raise HTTPException(status_code=500, detail="文件保存失败")
        
        # Build access URL (only for local endpoints)
        access_url = None
        if target_endpoint.provider == StorageProvider.LOCAL:
            access_url = f"/uploads/{full_object_key}"

        # Create image record
        new_image = await image_repository.create_image(
            session,
            original_url=request.image_url,
            file_hash=file_hash,
            file_type=file_type,
            file_size=file_size,
            width=width,
            height=height,
            description=description,
            embedding=None,
            uploaded_by=user.get("id"),
            is_public=request.is_public,
        )
        
        # Create ImageLocation record
        await image_location_repository.create(
            session,
            image_id=new_image.id,
            endpoint_id=target_endpoint.id,
            object_key=full_object_key,
            category_code=category_code,
            is_primary=True,
            sync_status="synced",
            synced_at=datetime.now(timezone.utc),
        )

        # Commit core data
        await session.commit()

        # Background: set tags and queue for analysis
        asyncio.create_task(
            _post_upload_process(
                image_id=new_image.id,
                user_id=user.get("id"),
                tags=tags,
                description=description,
                category_id=request.category_id,
                width=width,
                height=height,
                auto_analyze=request.auto_analyze,
                log=logger,
            )
        )
        
        # Trigger backup to backup endpoints
        asyncio.create_task(trigger_backup_for_image(new_image.id, target_endpoint.id))

        total_time = time.time() - start_time
        perf_logger.info(f"URL 图像上传耗时: {total_time:.4f}秒")

        return UploadAnalyzeResponse(
            id=new_image.id,
            image_url=access_url,
            tags=tags,
            description=description,
            process_time=f"{total_time:.4f}秒",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加图像任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加任务失败: {e}")


async def _post_upload_process(
    image_id: int,
    user_id: int | None,
    tags: list[str],
    description: str,
    category_id: int | None,
    width: int | None,
    height: int | None,
    auto_analyze: bool,
    log: logging.Logger,
) -> None:
    """后台异步处理上传后的标签、分辨率、AI分析任务。
    
    此函数在响应返回后异步执行，不阻塞上传响应。
    使用独立的数据库会话，确保事务独立性。
    
    标签处理逻辑：
    - 若同时提供 tags 和 description，跳过 AI 分析，只生成向量
    - 若只提供 tags，AI 分析会补充标签并合并（优先用户标签）
    - 若都不提供，完整 AI 分析
    
    Args:
        image_id: 图片 ID
        user_id: 上传用户 ID
        tags: 用户指定的标签列表
        description: 用户指定的描述
        category_id: 分类 ID
        width: 图片宽度
        height: 图片高度  
        auto_analyze: 是否启用 AI 分析
        log: 日志记录器
    """
    from imgtag.db.database import async_session_maker
    
    try:
        async with async_session_maker() as session:
            # 1. 设置用户标签
            if tags:
                t1 = time.time()
                await image_tag_repository.set_image_tags(
                    session, image_id, tags, source="user", added_by=user_id
                )
                perf_logger.debug(f"[Async] 设置用户标签耗时: {time.time() - t1:.4f}秒")
            
            # 2. 设置分类标签
            if category_id:
                t2 = time.time()
                await image_tag_repository.add_tag_to_image(
                    session, image_id, category_id, source="user", sort_order=0, added_by=user_id
                )
                perf_logger.debug(f"[Async] 设置分类标签耗时: {time.time() - t2:.4f}秒")
            
            # 3. 设置分辨率标签
            if width and height:
                resolution_name = upload_service.get_resolution_level(width, height)
                if resolution_name != "unknown":
                    t3 = time.time()
                    resolution_tag = await tag_repository.get_or_create(
                        session, resolution_name, source="system", level=1
                    )
                    await image_tag_repository.add_tag_to_image(
                        session, image_id, resolution_tag.id, source="system", sort_order=1
                    )
                    perf_logger.debug(f"[Async] 设置分辨率标签耗时: {time.time() - t3:.4f}秒")
            
            # 提交标签事务
            await session.commit()
            
            # 4. 判断是否需要 AI 分析
            # - 若用户提供了 tags + description，无需 AI 分析，只生成向量
            # - 若只提供 tags，需要 AI 分析补充并合并
            # - 若都不提供，需要完整 AI 分析
            # 注意：空字符串和空白字符串都不算有效值
            has_valid_tags = bool([t for t in tags if t and t.strip()])
            has_valid_description = bool(description and description.strip())
            user_provided_full = has_valid_tags and has_valid_description
            need_analysis = auto_analyze and not user_provided_full
            
            if need_analysis:
                # 加入 AI 分析任务队列
                t4 = time.time()
                await task_queue.add_tasks([image_id])
                perf_logger.debug(f"[Async] 添加AI分析任务耗时: {time.time() - t4:.4f}秒")
                if not task_queue._running:
                    asyncio.create_task(task_queue.start_processing())
            elif user_provided_full:
                # 用户已提供完整内容，只需生成向量
                t4 = time.time()
                await embedding_service.save_embedding_for_image(
                    image_id, description, tags
                )
                perf_logger.debug(f"[Async] 生成向量耗时: {time.time() - t4:.4f}秒")
            
            log.info(f"[Async] 后台处理完成: image_id={image_id}")
    except Exception as e:
        log.error(f"[Async] 后台处理失败: image_id={image_id}, error={e}")


@router.post("/upload", response_model=UploadAnalyzeResponse, status_code=201)
async def upload_and_analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="上传的图片文件"),
    auto_analyze: bool = Form(default=True, description="是否自动分析"),
    skip_analyze: bool = Form(default=False, description="跳过分析，只上传"),
    tags: str = Form(default="", description="手动标签，逗号分隔"),
    description: str = Form(default="", description="手动描述"),
    category_id: Optional[int] = Form(default=None, description="主分类ID"),
    is_public: bool = Form(default=True, description="是否公开可见"),
    endpoint_id: Optional[int] = Form(default=None, description="目标存储端点ID"),
    user: dict = Depends(require_permission(Permission.UPLOAD_IMAGE)),
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
        is_public: Whether image is publicly visible (default True).
        endpoint_id: Target storage endpoint ID (uses default if None).
        user: Current user.
        session: Database session.

    Returns:
        Upload response with image ID.
    """
    # storage_service and repositories imported at top level
    
    start_time = time.time()
    logger.info(
        f"上传文件: {file.filename}, auto_analyze={auto_analyze}, "
        f"category_id={category_id}, is_public={is_public}, endpoint_id={endpoint_id}"
    )

    try:
        # 权限校验需在上传/落库前完成，避免产生副作用
        final_tags = [t.strip() for t in tags.split(",") if t.strip()]
        final_description = description

        await ensure_create_tags_if_missing(session, user, final_tags)

        requested_analysis = auto_analyze and not skip_analyze
        if requested_analysis:
            has_valid_tags = bool([t for t in final_tags if t and t.strip()])
            has_valid_description = bool(final_description and final_description.strip())
            user_provided_full = has_valid_tags and has_valid_description
            if not user_provided_full:
                ensure_permission(user, Permission.AI_ANALYZE)

        file_content = await file.read()

        # Calculate hash early for object key generation
        file_hash = await asyncio.to_thread(lambda: hashlib.md5(file_content).hexdigest())
        file_size = round(len(file_content) / (1024 * 1024), 2)
        
        # Get file extension
        ext = file.filename.split(".")[-1].lower() if "." in file.filename else "jpg"

        # Get target endpoint (use specified or default)
        target_endpoint, err = await storage_endpoint_repository.resolve_upload_endpoint(
            session, endpoint_id
        )
        if err:
            raise HTTPException(400, err)
        
        # Get category code for subdirectory (if category specified)
        category_code = None
        if category_id:
            category_code = await get_category_code_cached(session, category_id)
        
        # Generate object key (hash-based path without category)
        object_key = storage_service.generate_object_key(file_hash, ext)
        
        # Build full key with category prefix for actual upload
        full_object_key = storage_service.get_full_object_key(object_key, category_code)
        
        # 获取本地默认端点（如果没有指定或指定的是本地）
        local_endpoint = await storage_endpoint_repository.get_by_id(session, 1)  # id=1 是本地端点
        is_local_endpoint = target_endpoint and target_endpoint.provider == StorageProvider.LOCAL
        
        # 提取图片信息（PIL 是 CPU 密集型操作，移至线程池避免阻塞）
        width, height = await asyncio.to_thread(
            upload_service.extract_image_dimensions, file_content
        )
        file_type = ext
        
        if is_local_endpoint or not target_endpoint:
            # 本地端点：使用统一的 upload_to_endpoint 处理（会创建子目录）
            actual_endpoint = target_endpoint or local_endpoint
            # 本地也使用 full_object_key（含 category 前缀，如果有的话）
            upload_success = await storage_service.upload_to_endpoint(
                file_content, full_object_key, actual_endpoint
            )
            if not upload_success:
                raise HTTPException(status_code=500, detail="文件保存失败")
            
            location_object_key = full_object_key
            access_url = f"/uploads/{full_object_key}"
        else:
            # 远程端点：上传到远程
            upload_success = await storage_service.upload_to_endpoint(
                file_content, full_object_key, target_endpoint
            )
            if not upload_success:
                # 上传失败，改用本地存储
                logger.warning(f"上传到端点 {target_endpoint.name} 失败，改用本地存储")
                
                # Fallback 到本地
                target_endpoint = local_endpoint
                is_local_endpoint = True
                await storage_service.upload_to_endpoint(
                    file_content, full_object_key, target_endpoint
                )
                location_object_key = full_object_key
                access_url = f"/uploads/{full_object_key}"
            else:
                # 远程上传成功
                location_object_key = full_object_key
                access_url = None  # 远程端点无本地访问 URL

        # Create image record (without legacy storage fields)
        t1 = time.time()
        new_image = await image_repository.create_image(
            session,
            file_hash=file_hash,
            file_type=file_type,
            file_size=file_size,
            width=width,
            height=height,
            description=final_description,
            embedding=None,  # Pending analysis
            uploaded_by=user.get("id"),
            is_public=is_public,
        )
        perf_logger.debug(f"创建图片记录耗时: {time.time() - t1:.4f}秒")

        # Create image_location record for the storage
        # 注意：如果 target_endpoint 为 None（fallback 失败），使用本地端点
        actual_endpoint_id = target_endpoint.id if target_endpoint else 1
        await image_location_repository.create(
            session,
            image_id=new_image.id,
            endpoint_id=actual_endpoint_id,
            object_key=location_object_key,
            category_code=category_code,
            is_primary=True,
            sync_status="synced",
            synced_at=datetime.now(timezone.utc),
        )
        logger.info(
            f"创建存储位置记录: image_id={new_image.id}, "
            f"endpoint={target_endpoint.name if target_endpoint else 'local'}, "
            f"object_key={location_object_key}, category={category_code}"
        )

        # 立即提交核心数据（image + location）
        await session.commit()
        
        total_time = time.time() - start_time
        perf_logger.info(f"上传核心数据耗时: {total_time:.4f}秒")
        
        # 后台异步处理标签、分辨率、AI分析（不阻塞响应）
        asyncio.create_task(
            _post_upload_process(
                image_id=new_image.id,
                user_id=user.get("id"),
                tags=final_tags,
                description=final_description,
                category_id=category_id,
                width=width,
                height=height,
                auto_analyze=auto_analyze and not skip_analyze,
                log=logger,
            )
        )
        
        # 触发自动备份到备份端点
        asyncio.create_task(
            trigger_backup_for_image(new_image.id, actual_endpoint_id)
        )

        return UploadAnalyzeResponse(
            id=new_image.id,
            image_url=access_url,
            tags=final_tags,
            description=final_description,
            process_time=f"{total_time:.4f}秒",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传和添加任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {e}")


@router.post("/upload-zip", response_model=dict[str, Any], status_code=201)
async def upload_zip(
    file: UploadFile = File(..., description="ZIP 压缩包"),
    category_id: Optional[int] = Form(default=None, description="主分类ID"),
    endpoint_id: Optional[int] = Form(default=None, description="目标存储端点ID (默认使用系统默认端点)"),
    user: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Upload ZIP file with images (admin only).

    Supports specifying target storage endpoint or using system default.

    Args:
        file: ZIP file.
        category_id: Category ID for all images.
        endpoint_id: Target storage endpoint ID.
        user: Current user.
        session: Database session.

    Returns:
        Upload results summary.
    """
    start_time = time.time()
    logger.info(f"上传 ZIP 文件: {file.filename}, category_id={category_id}, endpoint_id={endpoint_id}")

    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="只支持 .zip 格式文件")

    try:
        zip_content = await file.read()

        uploaded_ids = []
        failed_files = []
        
        # Get target endpoint (use specified or default)
        target_endpoint, err = await storage_endpoint_repository.resolve_upload_endpoint(
            session, endpoint_id
        )
        if err:
            raise HTTPException(400, err)
        
        # Get category code for subdirectory
        category_code = None
        if category_id:
            category_code = await get_category_code_cached(session, category_id)

        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as zf:
            for zip_info in zf.infolist():
                if zip_info.is_dir():
                    continue

                filename = os.path.basename(zip_info.filename)
                if filename.startswith(".") or filename.startswith("__"):
                    continue

                ext = os.path.splitext(filename)[1].lower()
                if ext not in SUPPORTED_IMAGE_EXTENSIONS:
                    continue

                try:
                    file_content = zf.read(zip_info.filename)
                    
                    # 计算哈希和大小
                    file_size = round(len(file_content) / (1024 * 1024), 2)
                    file_hash = await asyncio.to_thread(lambda c=file_content: hashlib.md5(c).hexdigest())
                    
                    # 提取图片尺寸和格式（PIL 操作移至线程池）
                    width, height = await asyncio.to_thread(
                        upload_service.extract_image_dimensions, file_content
                    )
                    file_type = ext.lstrip(".")
                    
                    # Generate object key with category prefix
                    object_key = storage_service.generate_object_key(file_hash, file_type)
                    full_object_key = storage_service.get_full_object_key(object_key, category_code)
                    
                    # Upload to target endpoint
                    await storage_service.upload_to_endpoint(
                        file_content, full_object_key, target_endpoint
                    )

                    new_image = await image_repository.create_image(
                        session,
                        file_hash=file_hash,
                        file_type=file_type,
                        file_size=file_size,
                        width=width,
                        height=height,
                        embedding=None,
                        uploaded_by=user.get("id"),
                    )
                    
                    # Create ImageLocation record
                    await image_location_repository.create(
                        session,
                        image_id=new_image.id,
                        endpoint_id=target_endpoint.id,
                        object_key=full_object_key,
                        category_code=category_code,
                        is_primary=True,
                        sync_status="synced",
                        synced_at=datetime.now(timezone.utc),
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

        # Commit all in one transaction
        await session.commit()

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
    except HTTPException:
        raise
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
    current_user: dict | None = Depends(get_current_user_optional),
):
    """Advanced image search.

    Public images are always visible. If logged in, user's own images are also visible.

    Args:
        request: Search filters.
        session: Database session.
        current_user: Current user (optional).

    Returns:
        ImageSearchResponse with results.
    """
    start_time = time.time()
    logger.info(f"高级图像搜索: {request.model_dump()}")

    try:
        # Visibility filter:
        # - Admin: skip_visibility_filter=True (see all)
        # - Logged in user: visible_to_user_id=user_id (see public + own)
        # - Anonymous: visible_to_user_id=None, skip=False (see public only)
        is_admin = current_user.get("role") == "admin" if current_user else False
        skip_visibility_filter = is_admin
        visible_to_user_id = current_user.get("id") if current_user and not is_admin else None
        
        results = await image_repository.search_images(
            session,
            tags=request.tags,
            keyword=request.keyword,
            category_id=request.category_id,
            resolution_id=request.resolution_id,
            visible_to_user_id=visible_to_user_id,
            skip_visibility_filter=skip_visibility_filter,
            pending_only=request.pending_only,
            duplicates_only=request.duplicates_only,
            limit=request.size,
            offset=(request.page - 1) * request.size,
            sort_by=request.sort_by,
            sort_desc=request.sort_desc,
        )

        # 批量获取标签信息（包含 level 和 source）
        image_ids = [img.id for img in results["images"]]
        tags_map = await image_repository.get_batch_image_tags_with_source(
            session, image_ids
        )

        # Convert to response with batch URL retrieval
        images = await _images_to_responses(results["images"], tags_map)

        # 使用通用分页响应
        # 分页响应 (已移至顶部 import)
        response = PaginatedResponse.create(
            items=images,
            total=results["total"],
            page=request.page,
            size=request.size,
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
    current_user: dict | None = Depends(get_current_user_optional),
):
    """Smart vector search with similarity scores.

    Uses hybrid search combining vector similarity and tag matching.
    Public images are always visible. If logged in, user's own images are also visible.

    Args:
        request: Search parameters with text query.
        session: Database session.
        current_user: Current user (optional).

    Returns:
        SimilarSearchResponse with similarity scores.
    """
    start_time = time.time()
    logger.info(f"智能向量搜索: '{request.text[:50] if request.text else ''}...'")

    try:
        # Visibility filter:
        # - Admin: skip_visibility_filter=True (see all)
        # - Logged in user: visible_to_user_id=user_id (see public + own)
        # - Anonymous: visible_to_user_id=None, skip=False (see public only)
        is_admin = current_user.get("role") == "admin" if current_user else False
        skip_visibility_filter = is_admin
        visible_to_user_id = current_user.get("id") if current_user and not is_admin else None
        
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
            limit=request.size,
            threshold=request.threshold,
            vector_weight=request.vector_weight,
            tag_weight=request.tag_weight,
            category_id=request.category_id,
            resolution_id=request.resolution_id,
            visible_to_user_id=visible_to_user_id,
            skip_visibility_filter=skip_visibility_filter,
        )

        # Convert to response model
        images = [ImageWithSimilarity(**img) for img in results]

        # 使用通用分页响应
        # 分页响应 (已移至顶部 import)
        response = PaginatedResponse.create(
            items=images,
            total=len(images),
            page=request.page,
            size=request.size,
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
            limit=request.size,
            offset=(request.page - 1) * request.size,
            sort_by=request.sort_by,
            sort_desc=request.sort_desc,
        )

        # 批量获取标签信息
        image_ids = [img.id for img in results["images"]]
        tags_map = await image_repository.get_batch_image_tags_with_source(
            session, image_ids
        )

        # Convert to response with batch URL retrieval
        images = await _images_to_responses(results["images"], tags_map)

        # 使用通用分页响应
        # 分页响应 (已移至顶部 import)
        response = PaginatedResponse.create(
            items=images,
            total=results["total"],
            page=request.page,
            size=request.size,
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
        
        # 解析标签（新流程：tag_ids 只负责 level=0/1/2 的选择；真正写入时：
        # - level=0 主分类：走 set_image_category（保证唯一）
        # - level=2 普通标签：走 set_image_tags_by_ids（语义收敛为仅 level=2）
        tag_ids_input: list[int] | None = None
        new_category_id: int | None = None
        new_category_name: str | None = None
        new_normal_tag_ids: list[int] = []
        new_normal_tag_names: list[str] = []
        
        if image_update.tag_ids is not None:
            tag_ids_input = image_update.tag_ids or []
            if tag_ids_input:
                # 查询标签的 level/name，用于：
                # 1) 解析主分类与普通标签
                # 2) 计算 embedding（排除分辨率 level=1）
                stmt = select(Tag.id, Tag.name, Tag.level).where(Tag.id.in_(tag_ids_input))
                result = await session.execute(stmt)
                meta = {row.id: (row.name, row.level) for row in result.fetchall()}

                for tid in tag_ids_input:
                    m = meta.get(tid)
                    if not m:
                        continue
                    name, level = m
                    if level == 0:
                        if new_category_id is not None and new_category_id != tid:
                            raise HTTPException(status_code=400, detail="只能选择一个主分类（level=0）")
                        new_category_id = tid
                        new_category_name = name
                    elif level == 2:
                        new_normal_tag_ids.append(tid)
                        new_normal_tag_names.append(name)
                    else:
                        # level=1 分辨率标签由系统维护，忽略客户端输入
                        continue
        elif image_update.tags is not None:
            # 兼容旧流程（按标签名）
            new_normal_tag_names = image_update.tags

        # Recalculate embedding if tags or description changed
        embedding_vector = None
        if has_tag_update or has_desc_update:
            description = (
                image_update.description
                if image_update.description is not None
                else (image.description or "")
            )
            
            tag_names_for_embedding: list[str] = []

            # 若是新流程（tag_ids），使用解析结果；否则回退到查询当前标签
            if image_update.tag_ids is not None:
                if new_category_name:
                    tag_names_for_embedding.append(new_category_name)
                tag_names_for_embedding.extend(new_normal_tag_names)
            elif image_update.tags is not None:
                # 旧流程：补上当前主分类（若有），再叠加普通标签名
                current_tag_objs = await image_tag_repository.get_image_tags(session, image_id)
                current_category = next((t.name for t in current_tag_objs if t.level == 0), None)
                if current_category:
                    tag_names_for_embedding.append(current_category)
                tag_names_for_embedding.extend(new_normal_tag_names)
            else:
                # 仅更新描述：查询当前标签（排除分辨率）
                current_tag_objs = await image_tag_repository.get_image_tags(session, image_id)
                current_category = next((t.name for t in current_tag_objs if t.level == 0), None)
                if current_category:
                    tag_names_for_embedding.append(current_category)
                tag_names_for_embedding.extend([t.name for t in current_tag_objs if t.level == 2])

            embedding_vector = await embedding_service.get_embedding_combined(
                description, tag_names_for_embedding
            )

        # Update image basic info
        await image_repository.update_image(
            session,
            image,
            description=image_update.description,
            embedding=embedding_vector,
            original_url=image_update.original_url,
            is_public=image_update.is_public,
        )

        # Update tags
        if tag_ids_input is not None:
            # 新流程：主分类与普通标签分开处理，避免主分类残留
            logger.info(
                f"更新标签关联(tag_ids): image_id={image_id}, "
                f"category_id={new_category_id}, normal_tag_ids={len(new_normal_tag_ids)}"
            )

            await image_tag_repository.set_image_category(
                session,
                image_id,
                new_category_id,
                source="user",
                added_by=current_user.get("id"),
            )
            changes = await image_tag_repository.set_image_tags_by_ids(
                session,
                image_id,
                new_normal_tag_ids,
                source="user",
                added_by=current_user.get("id"),
            )
            logger.info(f"普通标签关联更新完成: changes={changes}")
        elif image_update.tags is not None:
            # 旧流程：按名称更新（兼容）
            await ensure_create_tags_if_missing(session, current_user, image_update.tags)
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


@router.post("/{image_id}/suggest", response_model=dict[str, Any], status_code=201)
async def suggest_image_update(
    image_id: int,
    suggestion: ImageUpdateSuggestion,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """提交图片元信息修改建议（需登录）。

    适用场景：普通成员对“非自己上传”的图片提交修改建议，由管理员审批后落地。

    规则：
    - 上传者/管理员拥有直接编辑权限，不应走建议流程
    - 仅允许对“当前用户可见”的图片提交建议（public 或 owner/admin）
    - 普通成员需要 SUGGEST_CHANGES 权限
    """
    try:
        image = await image_repository.get_by_id(session, image_id)
        if not image:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")

        # 上传者/管理员直接编辑即可（避免绕过审计语义）
        if current_user.get("role") == "admin" or image.uploaded_by == current_user.get("id"):
            raise HTTPException(status_code=400, detail="你有编辑权限，请直接编辑该图片")

        # 权限校验（fail-fast）
        ensure_permission(current_user, Permission.SUGGEST_CHANGES)

        # 可见性校验：非公开图片仅 owner/admin 可见
        if not getattr(image, "is_public", True):
            raise HTTPException(status_code=403, detail="无权对该图片提交建议")

        approval = await suggestion_service.create_image_update_suggestion(
            session,
            image_id=image_id,
            requester_id=int(current_user.get("id")),
            description=suggestion.description,
            category_id=suggestion.category_id,
            normal_tag_ids=suggestion.normal_tag_ids,
            comment=suggestion.comment,
        )

        return {
            "message": "修改建议已提交，等待管理员审批",
            "approval_id": approval.id,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"提交修改建议失败: {e}")
        raise HTTPException(status_code=500, detail=f"提交修改建议失败: {e}")


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

        # Delete database record (ImageLocations deleted via CASCADE)
        # Physical files on storage endpoints should be cleaned separately if needed
        await image_repository.delete(session, image)

        process_time = time.time() - start_time
        perf_logger.info(f"删除图像耗时: {process_time:.4f}秒")

        return {
            "message": f"图像 ID:{image_id} 删除成功",
            "process_time": f"{process_time:.4f}秒",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除图像失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除图像失败: {e}")


@router.post("/{image_id}/tags", response_model=dict[str, Any])
async def add_tag_to_image(
    image_id: int,
    tag_id: Optional[int] = Query(default=None, description="标签ID（与tag_name二选一）"),
    tag_name: Optional[str] = Query(default=None, description="标签名称（与tag_id二选一，不存在则创建）"),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Add a single tag to an image (requires login).

    Supports adding by tag_id or tag_name.
    If tag_name is provided and doesn't exist, creates a new level=2 tag.

    Args:
        image_id: Image ID.
        tag_id: Tag ID to add (optional).
        tag_name: Tag name to add (optional, will create if not exists).
        current_user: Current user.
        session: Database session.

    Returns:
        Success confirmation with tag info.
    """
    if not tag_id and not tag_name:
        raise HTTPException(status_code=400, detail="请提供 tag_id 或 tag_name 参数")

    logger.info(f"添加标签: image_id={image_id}, tag_id={tag_id}, tag_name={tag_name}")

    try:
        image = await image_repository.get_by_id(session, image_id)
        if not image:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")

        check_image_permission(image, current_user, "编辑")

        resolved_tag = None
        is_new = False

        if tag_id:
            # 按 ID 查找
            resolved_tag = await tag_repository.get_by_id(session, tag_id)
            if not resolved_tag:
                raise HTTPException(status_code=404, detail=f"未找到 ID 为 {tag_id} 的标签")
            if resolved_tag.level != 2:
                raise HTTPException(status_code=400, detail="该接口仅支持添加普通标签（level=2）")
        else:
            # 按名称查找；不存在时才允许创建 level=2 普通标签
            tag_name = (tag_name or "").strip()
            if not tag_name:
                raise HTTPException(status_code=400, detail="标签名不能为空")

            existing = await tag_repository.get_by_name(session, tag_name)
            if existing:
                if existing.level != 2:
                    raise HTTPException(
                        status_code=409,
                        detail="标签名已被主分类/分辨率占用，不能作为普通标签使用",
                    )
                resolved_tag = existing
            else:
                # 仅当确实需要创建新标签时才要求 CREATE_TAGS 权限
                ensure_permission(current_user, Permission.CREATE_TAGS)
                try:
                    resolved_tag = await tag_repository.create(
                        session,
                        name=tag_name,
                        level=2,
                        source="user",
                    )
                    is_new = True
                    logger.info(f"创建新标签: id={resolved_tag.id}, name={tag_name}")
                except IntegrityError:
                    # 并发情况下可能已被其他请求创建，回滚后重新查询
                    await session.rollback()
                    existing = await tag_repository.get_by_name(session, tag_name)
                    if not existing:
                        raise HTTPException(status_code=500, detail="创建标签失败")
                    if existing.level != 2:
                        raise HTTPException(
                            status_code=409,
                            detail="标签名已被主分类/分辨率占用，不能作为普通标签使用",
                        )
                    resolved_tag = existing

        # 使用 upsert 避免先查询再插入
        stmt = pg_insert(ImageTag).values(
            image_id=image_id,
            tag_id=resolved_tag.id,
            source="user",
            added_by=current_user.get("id"),
            sort_order=99,
            added_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(index_elements=["image_id", "tag_id"])
        
        result = await session.execute(stmt)
        await session.flush()
        
        # rowcount=0 表示已存在
        already_exists = result.rowcount == 0

        return {
            "message": "标签已存在" if already_exists else "标签添加成功",
            "tag_id": resolved_tag.id,
            "tag_name": resolved_tag.name,
            "is_new": is_new and not already_exists,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加标签失败: {e}")
        raise HTTPException(status_code=500, detail=f"添加标签失败: {e}")



@router.delete("/{image_id}/tags/{tag_id}", response_model=dict[str, Any])
async def remove_tag_from_image(
    image_id: int,
    tag_id: int,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Remove a single tag from an image (requires login).

    Only level=2 (normal) tags can be removed.

    Args:
        image_id: Image ID.
        tag_id: Tag ID to remove.
        current_user: Current user.
        session: Database session.

    Returns:
        Success confirmation.
    """
    logger.info(f"删除标签: image_id={image_id}, tag_id={tag_id}")

    try:
        image = await image_repository.get_by_id(session, image_id)
        if not image:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {image_id} 的图像")

        check_image_permission(image, current_user, "编辑")

        # Check if tag exists and is level=2
        tag = await tag_repository.get_by_id(session, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail=f"未找到 ID 为 {tag_id} 的标签")
        if tag.level != 2:
            raise HTTPException(status_code=400, detail="只能删除普通标签 (level=2)")

        # Remove tag
        removed = await image_tag_repository.remove_tag_from_image(
            session,
            image_id=image_id,
            tag_id=tag_id,
        )

        if not removed:
            raise HTTPException(status_code=404, detail="该图片没有此标签")

        return {"message": "标签删除成功", "tag_id": tag_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除标签失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除标签失败: {e}")

class BatchDeleteRequest(BaseModel):
    """Request body for batch delete."""
    image_ids: list[int]
    delete_files: bool = False


@router.post("/batch/delete", response_model=dict[str, Any])
async def batch_delete_images(
    request: BatchDeleteRequest,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Batch delete images (requires login).

    Uses bulk WHERE IN() query instead of N individual queries.
    Optionally deletes physical files from storage endpoints.

    Args:
        request: Request body with image_ids and delete_files flag.
        user: Current user.
        session: Database session.

    Returns:
        Deletion results.
    """
    start_time = time.time()
    image_ids = request.image_ids
    delete_files = request.delete_files
    logger.info(f"批量删除图像: {len(image_ids)} 张, delete_files={delete_files}")

    if not image_ids:
        return {
            "message": "未提供图片ID",
            "success_count": 0,
            "fail_count": 0,
            "process_time": "0秒",
        }

    # 收集需要删除的文件信息（在事务前完成）
    files_to_delete: list[dict] = []
    
    try:
        # 权限过滤
        owner_id = get_owner_filter(user)
        
        # 如果需要删除物理文件，先收集文件位置信息
        if delete_files:
            from sqlalchemy.orm import selectinload
            
            stmt = select(Image).where(
                Image.id.in_(image_ids)
            ).options(selectinload(Image.locations))
            
            if owner_id is not None:
                stmt = stmt.where(Image.uploaded_by == owner_id)
            
            result = await session.execute(stmt)
            images = result.scalars().all()
            
            for image in images:
                for location in image.locations:
                    files_to_delete.append({
                        "endpoint_id": location.endpoint_id,
                        "object_key": location.object_key,
                    })

        # 事务内删除元数据（ImageLocations 通过 CASCADE 自动删除）
        deleted_count, _ = await image_repository.delete_by_ids(
            session, image_ids, owner_id=owner_id
        )
        
        # 提交事务
        await session.commit()

        # 后台异步删除物理文件（不阻塞响应）
        if files_to_delete:
            asyncio.create_task(
                _delete_files_async(files_to_delete, logger)
            )

        process_time = time.time() - start_time
        perf_logger.info(f"批量删除耗时: {process_time:.4f}秒")

        fail_count = len(image_ids) - deleted_count

        return {
            "message": f"批量删除完成: 成功 {deleted_count} 张，失败 {fail_count} 张",
            "success_count": deleted_count,
            "fail_count": fail_count,
            "files_scheduled": len(files_to_delete) if delete_files else 0,
            "process_time": f"{process_time:.4f}秒",
        }
    except Exception as e:
        await session.rollback()
        logger.error(f"批量删除失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量删除失败: {e}")


async def _delete_files_async(
    files: list[dict],
    log: Any,
) -> None:
    """后台异步删除物理文件。
    
    Args:
        files: 文件位置列表 [{"endpoint_id": int, "object_key": str}, ...]
        log: Logger instance.
    """
    from imgtag.db.database import async_session_maker
    
    deleted = 0
    skipped = 0
    failed = 0
    
    # 按 endpoint_id 分组，并去重相同的 object_key
    # （批量删除重复图片时可能有多个相同的 object_key）
    files_by_endpoint: dict[int, set[str]] = defaultdict(set)
    for f in files:
        files_by_endpoint[f["endpoint_id"]].add(f["object_key"])
    
    async with async_session_maker() as session:
        # 批量查询每个 endpoint 的引用计数
        ref_counts_cache: dict[tuple[int, str], int] = {}
        for endpoint_id, object_keys in files_by_endpoint.items():
            counts = await image_location_repository.batch_count_by_object_keys(
                session, endpoint_id, object_keys
            )
            for obj_key, count in counts.items():
                ref_counts_cache[(endpoint_id, obj_key)] = count
        
        # 缓存 endpoint 对象
        endpoint_cache: dict[int, Any] = {}
        
        # 迭代去重后的文件集合
        for endpoint_id, object_keys in files_by_endpoint.items():
            # 从缓存获取 endpoint
            if endpoint_id not in endpoint_cache:
                endpoint_cache[endpoint_id] = await storage_endpoint_repository.get_by_id(
                    session, endpoint_id
                )
            endpoint = endpoint_cache[endpoint_id]
            
            if not endpoint:
                continue
            
            for object_key in object_keys:
                try:
                    # 从缓存获取引用计数
                    ref_count = ref_counts_cache.get((endpoint_id, object_key), 0)
                    if ref_count > 0:
                        log.debug(
                            f"跳过删除文件 {object_key}: 仍有 {ref_count} 个 location 引用"
                        )
                        skipped += 1
                        continue
                    
                    # 使用 delete_from_endpoint 统一删除（同时支持本地和远程）
                    success = await storage_service.delete_from_endpoint(
                        object_key=object_key,
                        endpoint=endpoint,
                    )
                    if success:
                        deleted += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    log.warning(f"删除文件失败: {object_key}, 错误: {e}")
    
    log.info(f"后台删除文件完成: 成功 {deleted}, 跳过 {skipped}, 失败 {failed}")


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
        # 无 CREATE_TAGS 权限时，禁止隐式创建新标签
        await ensure_create_tags_if_missing(session, current_user, request.tags)

        # 权限兜底：非管理员只能操作自己上传的图片
        owner_id = get_owner_filter(current_user)
        effective_image_ids = request.image_ids
        if owner_id is not None:
            stmt = select(Image.id).where(
                and_(Image.id.in_(request.image_ids), Image.uploaded_by == owner_id)
            )
            result = await session.execute(stmt)
            effective_image_ids = [row.id for row in result]

        if not effective_image_ids:
            return {
                "message": "无可操作图片（仅允许修改自己上传的图片）",
                "success_count": 0,
                "fail_count": len(request.image_ids),
                "process_time": f"{(time.time() - start_time):.4f}秒",
            }

        # Bulk tag operation（此处 owner 已在 SQL 层过滤，仓库不再重复过滤）
        if request.mode == "add":
            updated = await image_tag_repository.batch_add_tags_to_images(
                session,
                effective_image_ids,
                request.tags,
                source="user",
                added_by=user_id,
                owner_id=None,
            )
        else:
            updated = await image_tag_repository.batch_replace_tags_for_images(
                session,
                effective_image_ids,
                request.tags,
                source="user",
                added_by=user_id,
                owner_id=None,
            )

        # 提交后再触发向量重建，避免读到旧数据
        await session.commit()
        try:
            asyncio.create_task(
                task_queue.add_tasks(effective_image_ids, task_type="rebuild_vector")
            )
        except Exception as e:
            logger.warning(f"批量更新后触发向量重建失败: {e}")

        process_time = time.time() - start_time
        perf_logger.info(f"批量更新标签耗时: {process_time:.4f}秒")

        fail_count = max(0, len(request.image_ids) - len(effective_image_ids))

        return {
            "message": f"批量更新完成: {len(effective_image_ids)} 张图片",
            "success_count": len(effective_image_ids),
            "fail_count": fail_count,
            "tags_updated": updated,
            "rebuild_scheduled": len(effective_image_ids),
            "process_time": f"{process_time:.4f}秒",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量更新标签失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量更新标签失败: {e}")


class BatchSetCategoryRequest(BaseModel):
    """批量设置主分类请求。"""

    image_ids: list[int]
    category_id: int  # 目标主分类 tag_id（level=0）


@router.post("/batch/set-category", response_model=dict[str, Any])
async def batch_set_category(
    request: BatchSetCategoryRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """批量设置主分类（谁上传谁管理，管理员不限制）。

    使用 bulk WHERE IN() 操作，避免 N 次循环查询/更新。

    Args:
        request: Batch category request.
        current_user: Current user.
        session: Database session.

    Returns:
        Update results.
    """
    start_time = time.time()
    logger.info(
        f"批量设置主分类: {len(request.image_ids)} 张图片 -> "
        f"分类ID {request.category_id}"
    )

    # 校验分类存在且为 level=0
    category = await tag_repository.get_by_id(session, request.category_id)
    if not category:
        raise HTTPException(status_code=404, detail="目标分类不存在")
    if category.level != 0:
        raise HTTPException(status_code=400, detail="目标标签不是主分类（level=0）")

    if not request.image_ids:
        return {
            "message": "未提供图片ID",
            "success_count": 0,
            "fail_count": 0,
            "process_time": "0秒",
        }

    try:
        # 非管理员只能修改自己上传的图片；管理员不受限制
        owner_id = get_owner_filter(current_user)
        image_ids = request.image_ids
        if owner_id is not None:
            from imgtag.models.image import Image

            owner_stmt = select(Image.id).where(
                and_(
                    Image.id.in_(request.image_ids),
                    Image.uploaded_by == owner_id,
                )
            )
            owner_result = await session.execute(owner_stmt)
            image_ids = [row.id for row in owner_result]

        if not image_ids:
            return {
                "message": "无可操作图片（仅允许修改自己上传的图片）",
                "success_count": 0,
                "fail_count": len(request.image_ids),
                "process_time": f"{(time.time() - start_time):.4f}秒",
            }

        # 批量删除旧的 level=0 分类标签（O(1) query）
        del_stmt = (
            sa_delete(ImageTag)
            .where(
                ImageTag.image_id.in_(image_ids),
                ImageTag.tag_id.in_(select(Tag.id).where(Tag.level == 0)),
            )
        )
        await session.execute(del_stmt)

        # 批量插入新的分类标签（O(1) query）
        now = datetime.now(timezone.utc)
        insert_data = [
            {
                "image_id": image_id,
                "tag_id": request.category_id,
                "source": "user",
                "added_by": current_user.get("id"),
                "sort_order": 0,
                "added_at": now,
            }
            for image_id in image_ids
        ]

        insert_stmt = pg_insert(ImageTag).values(insert_data)
        insert_stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=["image_id", "tag_id"]
        )
        await session.execute(insert_stmt)
        await session.flush()

        # 提交后再触发向量重建，避免读到旧数据
        await session.commit()
        try:
            asyncio.create_task(
                task_queue.add_tasks(image_ids, task_type="rebuild_vector")
            )
        except Exception as e:
            logger.warning(f"批量设置分类后触发向量重建失败: {e}")

        process_time = time.time() - start_time
        perf_logger.info(f"批量设置分类耗时: {process_time:.4f}秒")

        return {
            "message": f"批量设置主分类完成: {len(image_ids)} 张图片",
            "success_count": len(image_ids),
            "fail_count": max(0, len(request.image_ids) - len(image_ids)),
            "category_name": category.name,
            "rebuild_scheduled": len(image_ids),
            "process_time": f"{process_time:.4f}秒",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量设置分类失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量设置分类失败: {e}")
