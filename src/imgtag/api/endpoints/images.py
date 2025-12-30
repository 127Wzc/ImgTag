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
from imgtag.core.storage_constants import StorageProvider
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    image_location_repository,
    image_repository,
    image_tag_repository,
    storage_endpoint_repository,
    tag_repository,
)
from imgtag.models.image import Image
from imgtag.models.tag import Tag
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
from imgtag.services import embedding_service, storage_service, upload_service
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
        
        # 计算文件哈希和大小 (线程池执行避免阻塞)
        file_hash = await asyncio.to_thread(lambda: hashlib.md5(file_content).hexdigest())
        file_size = round(len(file_content) / (1024 * 1024), 2)
        
        # 获取文件类型
        file_type = file_path.split(".")[-1] if "." in file_path else "jpg"

        # Create initial record (without legacy storage fields)
        new_image = await image_repository.create_image(
            session,
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
                synced_at=datetime.now(timezone.utc),
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

        # Set category if provided (与手动上传保持一致)
        if request.category_id:
            await image_tag_repository.add_tag_to_image(
                session,
                new_image.id,
                request.category_id,
                source="user",
                sort_order=0,
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


async def _post_upload_process(
    image_id: int,
    user_id: int | None,
    tags: list[str],
    category_id: int | None,
    width: int | None,
    height: int | None,
    auto_analyze: bool,
    log: logging.Logger,
) -> None:
    """后台异步处理上传后的标签、分辨率、AI分析任务。
    
    此函数在响应返回后异步执行，不阻塞上传响应。
    使用独立的数据库会话，确保事务独立性。
    
    Args:
        image_id: 图片 ID
        user_id: 上传用户 ID
        tags: 用户指定的标签列表
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
            
            # 4. 添加 AI 分析任务
            if auto_analyze:
                t4 = time.time()
                await task_queue.add_tasks([image_id])
                perf_logger.debug(f"[Async] 添加AI分析任务耗时: {time.time() - t4:.4f}秒")
                if not task_queue._running:
                    asyncio.create_task(task_queue.start_processing())
            
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
        file_content = await file.read()

        # Calculate hash early for object key generation
        file_hash = await asyncio.to_thread(lambda: hashlib.md5(file_content).hexdigest())
        file_size = round(len(file_content) / (1024 * 1024), 2)
        
        # Get file extension
        ext = file.filename.split(".")[-1].lower() if "." in file.filename else "jpg"

        # Get target endpoint (use specified or default)
        if endpoint_id:
            target_endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
            if not target_endpoint or not target_endpoint.is_enabled:
                raise HTTPException(400, f"存储端点 {endpoint_id} 不可用")
            # Check if backup endpoint (not allowed for direct upload)
            from imgtag.core.storage_constants import EndpointRole
            if target_endpoint.role == EndpointRole.BACKUP.value:
                raise HTTPException(400, "不能直接上传到备份端点")
        else:
            target_endpoint = await storage_endpoint_repository.get_default_upload(session)
        
        # Get category code for subdirectory (if category specified)
        category_code = None
        if category_id:
            from imgtag.core.category_cache import get_category_code_cached
            category_code = await get_category_code_cached(session, category_id)
        
        # Generate object key (hash-based path without category)
        object_key = storage_service.generate_object_key(file_hash, ext)
        
        # Build full key with category prefix for actual upload
        full_object_key = storage_service.get_full_object_key(object_key, category_code)
        
        # 获取本地默认端点（如果没有指定或指定的是本地）
        local_endpoint = await storage_endpoint_repository.get_by_id(session, 1)  # id=1 是本地端点
        is_local_endpoint = target_endpoint and target_endpoint.provider == StorageProvider.LOCAL
        
        # 提取图片信息（统一处理，避免重复代码）
        width, height = upload_service.extract_image_dimensions(file_content)
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

        final_tags = [t.strip() for t in tags.split(",") if t.strip()]
        final_description = description

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
                category_id=category_id,
                width=width,
                height=height,
                auto_analyze=auto_analyze and not skip_analyze,
                log=logger,
            )
        )
        
        # 触发自动备份到备份端点
        from imgtag.services.backup_service import trigger_backup_for_image
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
        
        # Query local endpoint ONCE before the loop (optimization)
        local_endpoint = await storage_endpoint_repository.get_by_name(session, StorageProvider.LOCAL)

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
                    file_hash = await asyncio.to_thread(lambda c=file_content: hashlib.md5(c).hexdigest())

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
                    
                    # Create local ImageLocation record (no DB query in loop)
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

        # Convert to response with batch URL retrieval
        images = await _images_to_responses(results["images"], tags_map)

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

        # Convert to response with batch URL retrieval
        images = await _images_to_responses(results["images"], tags_map)

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
            description=image_update.description,
            embedding=embedding_vector,
            original_url=image_update.original_url,
            is_public=image_update.is_public,
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
    failed = 0
    
    async with async_session_maker() as session:
        for file_info in files:
            try:
                endpoint = await storage_endpoint_repository.get_by_id(
                    session, file_info["endpoint_id"]
                )
                if not endpoint:
                    continue
                
                # 使用 delete_from_endpoint 统一删除（同时支持本地和远程）
                success = await storage_service.delete_from_endpoint(
                    object_key=file_info["object_key"],
                    endpoint=endpoint,
                )
                if success:
                    deleted += 1
                else:
                    failed += 1
            except Exception as e:
                failed += 1
                log.warning(f"删除文件失败: {file_info['object_key']}, 错误: {e}")
    
    log.info(f"后台删除文件完成: 成功 {deleted}, 失败 {failed}")


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
