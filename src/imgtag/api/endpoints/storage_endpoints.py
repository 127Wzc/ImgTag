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
from imgtag.services.storage_management_service import storage_management_service
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
    ForceCleanupRequest,
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
    logger.debug("查询存储端点: user_id=%s enabled_only=%s", current_user["id"], enabled_only)
    
    if enabled_only:
        endpoints = await storage_endpoint_repository.get_enabled(session)
    else:
        endpoints = await storage_endpoint_repository.get_all(session)
    
    result = []
    for ep in endpoints:
        count = await image_location_repository.count_by_endpoint(session, ep.id)
        
        # 查询活动任务
        active_task_info = None
        active_tasks = await task_repository.get_active_storage_for_endpoint(session, ep.id)
        active_task = active_tasks[0] if active_tasks else None
        if active_task:
            # 计算进度
            payload = active_task.payload or {}
            result_data = active_task.result or {}
            total = payload.get("total_count", payload.get("batch_size", 0))
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
            public_url_include_bucket=ep.public_url_include_bucket,
            path_prefix=ep.path_prefix,
            role=ep.role,
            is_enabled=ep.is_enabled,
            is_default_upload=ep.is_default_upload,
            auto_sync_enabled=ep.auto_sync_enabled,
            sync_from_endpoint_id=ep.sync_from_endpoint_id,
            read_priority=ep.read_priority,
            read_weight=ep.read_weight,
            is_healthy=ep.is_healthy,
            last_health_check=ep.last_health_check,
            health_check_error=ep.health_check_error,
            has_active_sync=any(task.type == StorageTaskType.SYNC.value for task in active_tasks),
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
    logger.info("创建存储端点: user_id=%s name=%s", current_user["id"], data.name)
    
    # Check if name exists
    existing = await storage_endpoint_repository.get_by_name(session, data.name)
    if existing:
        raise HTTPException(400, f"Endpoint name '{data.name}' already exists")
    
    await storage_management_service.validate_create(session, data)

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
        public_url_include_bucket=data.public_url_include_bucket,
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
        public_url_include_bucket=endpoint.public_url_include_bucket,
        path_prefix=endpoint.path_prefix,
        role=endpoint.role,
        is_enabled=endpoint.is_enabled,
        is_default_upload=endpoint.is_default_upload,
        auto_sync_enabled=endpoint.auto_sync_enabled,
        sync_from_endpoint_id=endpoint.sync_from_endpoint_id,
        read_priority=endpoint.read_priority,
        read_weight=endpoint.read_weight,
        is_healthy=endpoint.is_healthy,
        last_health_check=endpoint.last_health_check,
        health_check_error=endpoint.health_check_error,
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
        public_url_include_bucket=endpoint.public_url_include_bucket,
        path_prefix=endpoint.path_prefix,
        role=endpoint.role,
        is_enabled=endpoint.is_enabled,
        is_default_upload=endpoint.is_default_upload,
        auto_sync_enabled=endpoint.auto_sync_enabled,
        sync_from_endpoint_id=endpoint.sync_from_endpoint_id,
        read_priority=endpoint.read_priority,
        read_weight=endpoint.read_weight,
        is_healthy=endpoint.is_healthy,
        last_health_check=endpoint.last_health_check,
        health_check_error=endpoint.health_check_error,
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
    logger.info("更新存储端点: user_id=%s endpoint_id=%s", current_user["id"], endpoint_id)
    
    endpoint = await storage_management_service.update(session, endpoint_id, data.model_dump(exclude_unset=True))

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
        public_url_include_bucket=endpoint.public_url_include_bucket,
        path_prefix=endpoint.path_prefix,
        role=endpoint.role,
        is_enabled=endpoint.is_enabled,
        is_default_upload=endpoint.is_default_upload,
        auto_sync_enabled=endpoint.auto_sync_enabled,
        sync_from_endpoint_id=endpoint.sync_from_endpoint_id,
        read_priority=endpoint.read_priority,
        read_weight=endpoint.read_weight,
        is_healthy=endpoint.is_healthy,
        last_health_check=endpoint.last_health_check,
        health_check_error=endpoint.health_check_error,
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
    logger.info("删除存储端点: user_id=%s endpoint_id=%s", current_user["id"], endpoint_id)
    
    return await storage_management_service.force_cleanup(
        session, endpoint_id, remove_endpoint=True, require_empty=not force, initiated_by=current_user["username"],
    )


@router.post("/endpoints/{endpoint_id}/force-cleanup")
async def force_cleanup_endpoint(
    endpoint_id: int, data: ForceCleanupRequest,
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    if not data.confirm:
        raise HTTPException(400, "请确认清理操作")
    logger.info("强制清理端点本地关联: user_id=%s endpoint_id=%s remove_endpoint=%s",
                current_user["id"], endpoint_id, data.remove_endpoint)
    return await storage_management_service.force_cleanup(
        session, endpoint_id, remove_endpoint=data.remove_endpoint, expected_name=data.endpoint_name, initiated_by=current_user["username"],
    )


@router.post("/endpoints/{endpoint_id}/cancel-tasks")
async def cancel_endpoint_tasks(
    endpoint_id: int, current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    if not await storage_endpoint_repository.get_by_id(session, endpoint_id):
        raise HTTPException(404, "端点不存在")
    ids = await storage_management_service.cancel(session, endpoint_id)
    logger.info("中断端点任务: user_id=%s endpoint_id=%s tasks=%s", current_user["id"], endpoint_id, len(ids))
    return {"cancelled_task_ids": ids, "message": f"已中断 {len(ids)} 个任务"}


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
    - 成功项逐项清理；删除文件后无其他位置的图片一并删除图库记录
    
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
    
    logger.info(
        "启动存储解绑任务: user_id=%s endpoint_id=%s delete_files=%s",
        current_user["id"], endpoint_id, data.delete_files,
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
    total = payload.get("total_count", payload.get("batch_size", 0))
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
    
    logger.info(
        "启动存储硬删除任务: user_id=%s endpoint_id=%s",
        current_user["id"], endpoint_id,
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
    await storage_management_service.update(session, endpoint_id, {"is_default_upload": True})
    await session.commit()
    return {"message": "默认上传端点已更新"}


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
        "启动存储同步: user_id=%s source_endpoint_id=%s target_endpoint_id=%s",
        current_user["id"], data.source_endpoint_id, data.target_endpoint_id,
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
    
    try:
        task_ids = await storage_sync_service.start_batch_sync(
            source_endpoint_id=data.source_endpoint_id, target_endpoint_id=data.target_endpoint_id,
            image_ids=data.image_ids, force_overwrite=data.force_overwrite,
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from error

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
    
    撤销执行资格并通知执行器中断；已发送到远程的请求可能仍会完成。
    Requires admin access.
    """
    await storage_management_service.cancel_sync(session, task_id)
    return {"message": "同步任务已中断"}
