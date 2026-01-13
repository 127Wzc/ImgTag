"""Storage endpoint management API endpoints.

Admin-only endpoints for managing storage backends (S3, R2, local, etc.).
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import EndpointRole, StorageProvider, StorageTaskType
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
    task_repository,
)
from imgtag.models.image_location import ImageLocation
from imgtag.models.user import User
from imgtag.services import storage_service, storage_sync_service
from imgtag.services.storage_deletion_service import storage_deletion_service
from imgtag.schemas.storage import (
    ActiveTaskInfo,
    EndpointCreate,
    EndpointUpdate,
    EndpointResponse,
    SyncStartRequest,
    SyncProgressResponse,
    DeletionImpactResponse,
    SoftDeleteRequest,
    HardDeleteRequest,
)

logger = get_logger(__name__)

router = APIRouter()

# === Endpoint Management APIs ===


@router.get("/endpoints", response_model=list[EndpointResponse])
async def list_endpoints(
    enabled_only: bool = False,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """List all storage endpoints.
    
    Requires admin access.
    """
    logger.info(f"[Admin:{current_user['username']}] Listing storage endpoints")
    
    if enabled_only:
        endpoints = await storage_endpoint_repository.get_enabled(session)
    else:
        endpoints = await storage_endpoint_repository.get_all(session)
    
    # 定义存储任务类型
    # 使用枚举常量而非硬编码
    storage_task_types = StorageTaskType.all_values()
    
    result = []
    for ep in endpoints:
        count = await image_location_repository.count_by_endpoint(session, ep.id)
        
        # 查询活动任务
        active_task_info = None
        active_task = await task_repository.get_active_for_endpoint(
            session, ep.id, storage_task_types
        )
        if active_task:
            # 计算进度
            payload = active_task.payload or {}
            result_data = active_task.result or {}
            total = payload.get("total_count", 0)
            success = result_data.get("success_count", 0)
            failed = result_data.get("failed_count", 0)
            progress = ((success + failed) / total * 100) if total > 0 else 0
            
            active_task_info = ActiveTaskInfo(
                task_id=active_task.id,
                task_type=active_task.type,
                status=active_task.status,
                progress_percent=round(progress, 1),
                success_count=success,
                failed_count=failed,
                total_count=total,
            )
        
        result.append(EndpointResponse(
            id=ep.id,
            name=ep.name,
            provider=ep.provider,
            endpoint_url=ep.endpoint_url,
            region=ep.region,
            bucket_name=ep.bucket_name,
            path_style=ep.path_style,
            has_credentials=ep.has_credentials,
            access_key_id=ep.access_key_id,
            secret_access_key=ep.secret_access_key,
            public_url_prefix=ep.public_url_prefix,
            path_prefix=ep.path_prefix,
            role=ep.role,
            is_enabled=ep.is_enabled,
            is_default_upload=ep.is_default_upload,
            auto_sync_enabled=ep.auto_sync_enabled,
            sync_from_endpoint_id=ep.sync_from_endpoint_id,
            read_priority=ep.read_priority,
            read_weight=ep.read_weight,
            is_healthy=ep.is_healthy,
            location_count=count,
            active_task=active_task_info,
        ))
    
    return result


@router.post("/endpoints", response_model=EndpointResponse)
async def create_endpoint(
    data: EndpointCreate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new storage endpoint.
    
    Requires admin access.
    """
    logger.warning(f"[Admin:{current_user['username']}] Creating storage endpoint: {data.name}")
    
    # Check if name exists
    existing = await storage_endpoint_repository.get_by_name(session, data.name)
    if existing:
        raise HTTPException(400, f"Endpoint name '{data.name}' already exists")
    
    # 检查备份端点唯一性：只允许一个备份端点
    if data.role == EndpointRole.BACKUP.value:
        backup_eps = await storage_endpoint_repository.get_backup_endpoints(session)
        if backup_eps:
            raise HTTPException(400, f"已存在备份端点 '{backup_eps[0].name}'，系统只允许一个备份端点")
    
    # Create endpoint
    endpoint = await storage_endpoint_repository.create(
        session,
        name=data.name,
        provider=data.provider,
        endpoint_url=data.endpoint_url,
        region=data.region,
        bucket_name=data.bucket_name,
        path_style=data.path_style,
        public_url_prefix=data.public_url_prefix,
        path_prefix=data.path_prefix,
        role=data.role,
        is_enabled=data.is_enabled,
        is_default_upload=data.is_default_upload,
        auto_sync_enabled=data.auto_sync_enabled,
        sync_from_endpoint_id=data.sync_from_endpoint_id,
        read_priority=data.read_priority,
        read_weight=data.read_weight,
    )
    
    # Set credentials via properties (encrypted)
    if data.access_key_id:
        endpoint.access_key_id = data.access_key_id
    if data.secret_access_key:
        endpoint.secret_access_key = data.secret_access_key
    
    # Handle default upload
    if data.is_default_upload:
        await storage_endpoint_repository.set_default_upload(session, endpoint.id)
    
    await session.commit()
    await session.refresh(endpoint)
    
    return EndpointResponse(
        id=endpoint.id,
        name=endpoint.name,
        provider=endpoint.provider,
        endpoint_url=endpoint.endpoint_url,
        region=endpoint.region,
        bucket_name=endpoint.bucket_name,
        path_style=endpoint.path_style,
        has_credentials=endpoint.has_credentials,
        access_key_id=endpoint.access_key_id,
        secret_access_key=endpoint.secret_access_key,
        public_url_prefix=endpoint.public_url_prefix,
        path_prefix=endpoint.path_prefix,
        role=endpoint.role,
        is_enabled=endpoint.is_enabled,
        is_default_upload=endpoint.is_default_upload,
        auto_sync_enabled=endpoint.auto_sync_enabled,
        sync_from_endpoint_id=endpoint.sync_from_endpoint_id,
        read_priority=endpoint.read_priority,
        read_weight=endpoint.read_weight,
        is_healthy=endpoint.is_healthy,
        location_count=0,
    )


@router.get("/endpoints/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(
    endpoint_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get a specific storage endpoint.
    
    Requires admin access.
    """
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    count = await image_location_repository.count_by_endpoint(session, endpoint_id)
    
    return EndpointResponse(
        id=endpoint.id,
        name=endpoint.name,
        provider=endpoint.provider,
        endpoint_url=endpoint.endpoint_url,
        region=endpoint.region,
        bucket_name=endpoint.bucket_name,
        path_style=endpoint.path_style,
        has_credentials=endpoint.has_credentials,
        access_key_id=endpoint.access_key_id,
        secret_access_key=endpoint.secret_access_key,
        public_url_prefix=endpoint.public_url_prefix,
        path_prefix=endpoint.path_prefix,
        role=endpoint.role,
        is_enabled=endpoint.is_enabled,
        is_default_upload=endpoint.is_default_upload,
        auto_sync_enabled=endpoint.auto_sync_enabled,
        sync_from_endpoint_id=endpoint.sync_from_endpoint_id,
        read_priority=endpoint.read_priority,
        read_weight=endpoint.read_weight,
        is_healthy=endpoint.is_healthy,
        location_count=count,
    )



@router.put("/endpoints/{endpoint_id}", response_model=EndpointResponse)
async def update_endpoint(
    endpoint_id: int,
    data: EndpointUpdate,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Update a storage endpoint.
    
    Requires admin access.
    """
    logger.warning(f"[Admin:{current_user['username']}] Updating storage endpoint: {endpoint_id}")
    
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    
    # Check if trying to modify bucket_name or path_prefix when endpoint has images
    # These fields affect file paths, so changing them would break existing images
    location_count = await image_location_repository.count_by_endpoint(session, endpoint_id)
    
    new_bucket = update_data.get("bucket_name")
    if new_bucket is not None and new_bucket != endpoint.bucket_name:
        if location_count > 0:
            raise HTTPException(
                400,
                f"无法修改存储目录：该端点有 {location_count} 张关联图片。请先解绑或迁移图片。"
            )
    
    new_path_prefix = update_data.get("path_prefix")
    if new_path_prefix is not None and new_path_prefix != endpoint.path_prefix:
        if location_count > 0:
            raise HTTPException(
                400,
                f"无法修改路径前缀：该端点有 {location_count} 张关联图片。请先解绑或迁移图片。"
            )
    
    # Restrict default local endpoint (id=1) to storage and read strategy fields
    if endpoint_id == 1:
        allowed_fields = {"bucket_name", "public_url_prefix", "read_priority", "read_weight", "is_default_upload"}
        # Filter to only allowed fields instead of rejecting
        update_data = {k: v for k, v in update_data.items() if k in allowed_fields}
    
    # 检查备份端点唯一性：只允许一个备份端点
    new_role = update_data.get("role")
    if new_role == EndpointRole.BACKUP.value and endpoint.role != EndpointRole.BACKUP.value:
        backup_eps = await storage_endpoint_repository.get_backup_endpoints(session)
        if backup_eps:
            raise HTTPException(400, f"已存在备份端点 '{backup_eps[0].name}'，系统只允许一个备份端点")
    
    # Handle credentials separately (encrypted)
    # Only update if a non-empty value is provided (preserve existing on empty/null)
    access_key = update_data.pop("access_key_id", None)
    secret_key = update_data.pop("secret_access_key", None)
    
    if update_data:
        await storage_endpoint_repository.update(session, endpoint, **update_data)
    
    # Only update credentials if non-empty value provided
    if access_key:  # Truthy check: not None and not empty string
        endpoint.access_key_id = access_key
    if secret_key:  # Truthy check: not None and not empty string
        endpoint.secret_access_key = secret_key
    
    # Handle default upload
    if data.is_default_upload:
        await storage_endpoint_repository.set_default_upload(session, endpoint_id)
    
    await session.commit()
    await session.refresh(endpoint)
    
    count = await image_location_repository.count_by_endpoint(session, endpoint_id)
    
    return EndpointResponse(
        id=endpoint.id,
        name=endpoint.name,
        provider=endpoint.provider,
        endpoint_url=endpoint.endpoint_url,
        region=endpoint.region,
        bucket_name=endpoint.bucket_name,
        path_style=endpoint.path_style,
        has_credentials=endpoint.has_credentials,
        access_key_id=endpoint.access_key_id,
        secret_access_key=endpoint.secret_access_key,
        public_url_prefix=endpoint.public_url_prefix,
        path_prefix=endpoint.path_prefix,
        role=endpoint.role,
        is_enabled=endpoint.is_enabled,
        is_default_upload=endpoint.is_default_upload,
        auto_sync_enabled=endpoint.auto_sync_enabled,
        sync_from_endpoint_id=endpoint.sync_from_endpoint_id,
        read_priority=endpoint.read_priority,
        read_weight=endpoint.read_weight,
        is_healthy=endpoint.is_healthy,
        location_count=count,
    )


@router.delete("/endpoints/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: int,
    force: bool = False,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a storage endpoint configuration.
    
    Fails if endpoint has associated image locations unless force=True.
    Use /endpoints/{id}/locations or /endpoints/{id}/files first to clean up data.
    Requires admin access.
    """
    logger.warning(f"[Admin:{current_user['username']}] Deleting storage endpoint: {endpoint_id}")
    
    # Protect default local endpoint
    if endpoint_id == 1:
        raise HTTPException(400, "Cannot delete the default local endpoint")
    
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    # Check for associated locations
    count = await image_location_repository.count_by_endpoint(session, endpoint_id)
    if count > 0 and not force:
        raise HTTPException(
            400,
            f"Cannot delete endpoint: {count} images are stored here. "
            "Use /endpoints/{id}/locations to remove associations first, "
            "or pass force=true to force delete."
        )
    
    # If force=True and has locations, delete them first
    if count > 0:
        await image_location_repository.delete_by_endpoint(session, endpoint_id)
    
    await storage_endpoint_repository.delete(session, endpoint)
    await session.commit()
    
    return {"message": "Endpoint deleted", "locations_removed": count}




@router.get("/endpoints/{endpoint_id}/deletion-impact", response_model=DeletionImpactResponse)
async def get_deletion_impact(
    endpoint_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get deletion impact analysis for an endpoint.
    
    Shows how many images would be affected by deletion.
    Requires admin access.
    """
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    # Count total locations
    total_locations = await image_location_repository.count_by_endpoint(session, endpoint_id)
    
    # Images only on this endpoint (subquery for efficiency)
    unique_subq = (
        select(ImageLocation.image_id)
        .group_by(ImageLocation.image_id)
        .having(func.count(ImageLocation.endpoint_id) == 1)
        .subquery()
    )
    unique_stmt = (
        select(func.count())
        .select_from(ImageLocation)
        .where(ImageLocation.endpoint_id == endpoint_id)
        .where(ImageLocation.image_id.in_(select(unique_subq.c.image_id)))
    )
    unique_result = await session.execute(unique_stmt)
    unique_images = unique_result.scalar() or 0
    
    shared_images = total_locations - unique_images
    
    # Estimate file size (simplified)
    total_file_size_mb = 0.0
    
    warnings = []
    if unique_images > 0:
        warnings.append(f"{unique_images} 张图片仅存储在此端点，删除后将无法访问")
    
    if endpoint_id == 1:
        warnings.append("这是默认本地端点，不可删除")
    
    return DeletionImpactResponse(
        endpoint_id=endpoint_id,
        endpoint_name=endpoint.name,
        total_locations=total_locations,
        unique_images=unique_images,
        shared_images=shared_images,
        total_file_size_mb=total_file_size_mb,
        can_soft_delete=endpoint_id != 1,
        can_hard_delete=endpoint_id != 1 and endpoint.provider != "local",
        warnings=warnings,
    )




@router.delete("/endpoints/{endpoint_id}/locations")
async def soft_delete_endpoint_locations(
    endpoint_id: int,
    data: SoftDeleteRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Unlink all ImageLocation records for an endpoint.
    
    Starts a background task for batch processing with:
    - Progress tracking via task system
    - Optional physical file deletion
    - Orphan metadata cleanup
    
    Requires admin access with confirmation.
    """
    if not data.confirm:
        raise HTTPException(400, "Must confirm deletion with confirm=true")
    
    if endpoint_id == 1:
        raise HTTPException(400, "Cannot delete locations from the default local endpoint")
    
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    # 检查是否有进行中的任务
    # 检查是否有进行中的任务（使用枚举常量）
    active_task = await task_repository.get_active_for_endpoint(
        session, endpoint_id, StorageTaskType.all_values()
    )
    if active_task:
        raise HTTPException(
            409,
            f"该端点有进行中的任务 ({active_task.type})，请等待完成后再操作"
        )
    
    logger.warning(
        f"[Admin:{current_user['username']}] Starting unlink task for endpoint: "
        f"{endpoint.name}, delete_files={data.delete_files}"
    )
    
    # Start background task via service
    from imgtag.services.storage_unlink_service import storage_unlink_service
    
    try:
        task_id = await storage_unlink_service.start_unlink(
            endpoint_id=endpoint_id,
            delete_files=data.delete_files,
            initiated_by=current_user["username"],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    
    # Get initial status
    location_count = await image_location_repository.count_by_endpoint(session, endpoint_id)
    
    return {
        "message": f"已启动解绑任务，共 {location_count} 条位置记录",
        "task_id": task_id,
        "location_count": location_count,
        "delete_files": data.delete_files,
    }


@router.get("/endpoints/{endpoint_id}/unlink-progress/{task_id}")
async def get_unlink_progress(
    endpoint_id: int,
    task_id: str,
    current_user: User = Depends(require_admin),
):
    """Get unlink task progress.
    
    Args:
        endpoint_id: Endpoint ID (for validation).
        task_id: Task ID returned by unlink API.
        
    Returns:
        Progress information including status, counts, and percentage.
    """
    from imgtag.services.storage_unlink_service import storage_unlink_service
    
    progress = await storage_unlink_service.get_unlink_progress(task_id)
    
    if "error" in progress:
        raise HTTPException(404, progress["error"])
    
    # Verify endpoint matches
    if progress.get("endpoint_id") != endpoint_id:
        raise HTTPException(400, "Task does not belong to this endpoint")
    
    return progress


@router.get("/endpoints/{endpoint_id}/task")
async def get_endpoint_active_task(
    endpoint_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get active task for an endpoint (unified progress API).
    
    Returns the currently running task (sync/delete/unlink) for the endpoint,
    or null if no task is running.
    """
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    # 使用枚举常量
    active_task = await task_repository.get_active_for_endpoint(
        session, endpoint_id, StorageTaskType.all_values()
    )
    
    if not active_task:
        return {"active_task": None}
    
    # Calculate progress
    payload = active_task.payload or {}
    result_data = active_task.result or {}
    total = payload.get("total_count", 0)
    success = result_data.get("success_count", 0)
    failed = result_data.get("failed_count", 0)
    progress = ((success + failed) / total * 100) if total > 0 else 0
    
    return {
        "active_task": ActiveTaskInfo(
            task_id=active_task.id,
            task_type=active_task.type,
            status=active_task.status,
            progress_percent=round(progress, 1),
            success_count=success,
            failed_count=failed,
            total_count=total,
        )
    }


@router.delete("/endpoints/{endpoint_id}/files")
async def hard_delete_endpoint_files(
    endpoint_id: int,
    data: HardDeleteRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Hard delete: Start background task to delete physical files.
    
    ⚠️ This is a destructive operation! Files at this endpoint will be permanently deleted.
    Only works for S3-compatible endpoints (not local).
    Requires admin access with confirmation text.
    
    Returns a task_id to track deletion progress.
    """
    if not data.confirm or data.confirm_text != "删除所有文件":
        raise HTTPException(
            400, 
            "Must confirm with confirm=true and confirm_text='删除所有文件'"
        )
    
    if endpoint_id == 1:
        raise HTTPException(400, "Cannot delete files from the default local endpoint")
    
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    # Only allow hard delete for S3 endpoints
    if endpoint.provider == "local":
        raise HTTPException(400, "硬删除仅支持 S3 兼容端点，本地端点请手动管理文件")
    
    logger.warning(
        f"[Admin:{current_user['username']}] Starting HARD DELETE task for endpoint: {endpoint.name}"
    )
    
    # Start background deletion task
    task_id = await storage_deletion_service.start_hard_delete(
        endpoint_id=endpoint_id,
        initiated_by=current_user["username"],
    )
    
    return {
        "message": "删除任务已启动",
        "task_id": task_id,
        "endpoint_id": endpoint_id,
        "endpoint_name": endpoint.name,
    }


@router.get("/endpoints/{endpoint_id}/deletion-progress/{task_id}")
async def get_deletion_progress(
    endpoint_id: int,
    task_id: str,
    current_user: User = Depends(require_admin),
):
    """Get deletion task progress.
    
    Returns current deletion task status and counts.
    """
    progress = await storage_deletion_service.get_deletion_progress(task_id)
    
    if "error" in progress:
        raise HTTPException(404, progress["error"])
    
    # Verify endpoint matches
    if progress.get("endpoint_id") != endpoint_id:
        raise HTTPException(400, "Task does not belong to this endpoint")
    
    return progress


@router.post("/endpoints/{endpoint_id}/test")
async def test_endpoint_connection(
    endpoint_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Test storage endpoint connection.
    
    Requires admin access.
    """
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    try:
        if endpoint.provider == StorageProvider.LOCAL:
            bucket = endpoint.bucket_name or "uploads"
            project_root = settings.get_upload_path().parent
            path = str(project_root / bucket) if not os.path.isabs(bucket) else bucket
            exists = os.path.isdir(path)
            writable = os.access(path, os.W_OK) if exists else False
            
            is_healthy = exists and writable
            error = None if is_healthy else f"Path not accessible: {path}"
        else:
            # Test S3 connection
            test_key = f"__test_connection_{endpoint_id}__"
            success = await storage_service.upload_to_endpoint(
                b"test", test_key, endpoint
            )
            if success:
                await storage_service.delete_from_endpoint(test_key, endpoint)
            is_healthy = success
            error = None if success else "Upload test failed"
        
        # Update health status
        await storage_endpoint_repository.update_health(
            session, endpoint_id, is_healthy, error
        )
        await session.commit()
        
        return {
            "success": is_healthy,
            "message": "Connection successful" if is_healthy else error,
        }
    except Exception as e:
        logger.error(f"Endpoint connection test failed: {e}")
        await storage_endpoint_repository.update_health(
            session, endpoint_id, False, str(e)
        )
        await session.commit()
        return {"success": False, "message": str(e)}


@router.post("/endpoints/{endpoint_id}/set-default")
async def set_default_endpoint(
    endpoint_id: int,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Set endpoint as default for uploads.
    
    Requires admin access.
    """
    endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")
    
    await storage_endpoint_repository.set_default_upload(session, endpoint_id)
    await session.commit()
    
    logger.info(f"[Admin:{current_user['username']}] Set default upload endpoint: {endpoint.name}")
    
    return {"message": f"Default upload endpoint set to: {endpoint.name}"}


# === Sync APIs ===


@router.post("/sync/start")
async def start_sync(
    data: SyncStartRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Start a sync task between endpoints.
    
    Requires admin access.
    """
    logger.info(
        f"[Admin:{current_user['username']}] Starting sync: "
        f"{data.source_endpoint_id} -> {data.target_endpoint_id}"
    )
    
    # Validate endpoints
    source = await storage_endpoint_repository.get_by_id(session, data.source_endpoint_id)
    target = await storage_endpoint_repository.get_by_id(session, data.target_endpoint_id)
    
    if not source:
        raise HTTPException(400, "Source endpoint not found")
    if not target:
        raise HTTPException(400, "Target endpoint not found")
    if source.id == target.id:
        raise HTTPException(400, "Source and target cannot be the same")
    
    # 双向同步已支持：Local ↔ S3
    
    task_ids = await storage_sync_service.start_batch_sync(
        source_endpoint_id=data.source_endpoint_id,
        target_endpoint_id=data.target_endpoint_id,
        image_ids=data.image_ids,
        force_overwrite=data.force_overwrite,
    )
    
    return {
        "message": f"Started {len(task_ids)} sync task(s)",
        "task_ids": task_ids,
    }


@router.get("/sync/{task_id}", response_model=SyncProgressResponse)
async def get_sync_progress(
    task_id: str,
    _: User = Depends(require_admin),
):
    """Get sync task progress.
    
    Requires admin access.
    """
    progress = await storage_sync_service.get_sync_progress(task_id)
    
    if "error" in progress:
        raise HTTPException(404, progress["error"])
    
    return SyncProgressResponse(**progress)


@router.post("/sync/{task_id}/cancel")
async def cancel_sync(
    task_id: str,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Cancel a sync task.
    
    Note: Only marks task as cancelled, running operations complete.
    Requires admin access.
    """
    # task_repository imported at top level
    
    task = await task_repository.get_by_id(session, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    
    if task.status in ("completed", "failed"):
        raise HTTPException(400, f"Task already {task.status}")
    
    await task_repository.update_status(session, task_id, "cancelled")
    await session.commit()
    
    logger.info(f"[Admin:{current_user['username']}] Cancelled sync task: {task_id}")
    
    return {"message": "Task cancelled"}
