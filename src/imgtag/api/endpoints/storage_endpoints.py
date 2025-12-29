"""Storage endpoint management API endpoints.

Admin-only endpoints for managing storage backends (S3, R2, local, etc.).
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
    task_repository,
)
from imgtag.models.user import User
from imgtag.services import storage_service, storage_sync_service

logger = get_logger(__name__)

router = APIRouter()


# === Request/Response Models ===


class EndpointCreate(BaseModel):
    """Request model for creating a storage endpoint."""

    name: str = Field(..., min_length=1, max_length=50)
    provider: str = Field(..., pattern="^(local|s3)$")
    endpoint_url: Optional[str] = None
    region: Optional[str] = "auto"
    bucket_name: Optional[str] = None
    path_style: bool = True  # True = path style, False = virtual-hosted
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    public_url_prefix: Optional[str] = None
    path_prefix: str = ""
    role: str = "primary"
    is_enabled: bool = True
    is_default_upload: bool = False
    auto_sync_enabled: bool = False
    sync_from_endpoint_id: Optional[int] = None
    read_priority: int = 100
    read_weight: int = 1


class EndpointUpdate(BaseModel):
    """Request model for updating a storage endpoint."""

    name: Optional[str] = None
    provider: Optional[str] = None
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_name: Optional[str] = None
    path_style: Optional[bool] = None
    access_key_id: Optional[str] = None
    secret_access_key: Optional[str] = None
    public_url_prefix: Optional[str] = None
    path_prefix: Optional[str] = None
    role: Optional[str] = None
    is_enabled: Optional[bool] = None
    is_default_upload: Optional[bool] = None
    auto_sync_enabled: Optional[bool] = None
    sync_from_endpoint_id: Optional[int] = None
    read_priority: Optional[int] = None
    read_weight: Optional[int] = None


class EndpointResponse(BaseModel):
    """Response model for storage endpoint."""

    id: int
    name: str
    provider: str
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_name: Optional[str] = None
    path_style: bool = True
    has_credentials: bool = False
    public_url_prefix: Optional[str] = None
    path_prefix: str = ""
    role: str
    is_enabled: bool
    is_default_upload: bool
    auto_sync_enabled: bool
    sync_from_endpoint_id: Optional[int] = None
    read_priority: int
    read_weight: int
    is_healthy: bool
    location_count: int = 0

    class Config:
        from_attributes = True


class SyncStartRequest(BaseModel):
    """Request to start a sync task."""

    source_endpoint_id: int
    target_endpoint_id: int
    image_ids: Optional[list[int]] = None
    force_overwrite: bool = False


class SyncProgressResponse(BaseModel):
    """Response for sync task progress."""

    task_id: str
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    progress_percent: float
    batch_index: Optional[int] = None
    total_batches: Optional[int] = None


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
    
    result = []
    for ep in endpoints:
        count = await image_location_repository.count_by_endpoint(session, ep.id)
        result.append(EndpointResponse(
            id=ep.id,
            name=ep.name,
            provider=ep.provider,
            endpoint_url=ep.endpoint_url,
            region=ep.region,
            bucket_name=ep.bucket_name,
            path_style=ep.path_style,
            has_credentials=ep.has_credentials,
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
    
    # Restrict default local endpoint (id=1) to storage and read strategy fields
    if endpoint_id == 1:
        allowed_fields = {"bucket_name", "public_url_prefix", "read_priority", "read_weight"}
        restricted_fields = set(update_data.keys()) - allowed_fields
        if restricted_fields:
            raise HTTPException(
                400,
                f"Default local endpoint can only modify: bucket_name, public_url_prefix, read_priority, read_weight. "
                f"Cannot modify: {', '.join(restricted_fields)}"
            )
    
    # Handle credentials separately (encrypted)
    access_key = update_data.pop("access_key_id", None)
    secret_key = update_data.pop("secret_access_key", None)
    
    if update_data:
        await storage_endpoint_repository.update(session, endpoint, **update_data)
    
    if access_key is not None:
        endpoint.access_key_id = access_key
    if secret_key is not None:
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
    current_user: User = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Delete a storage endpoint.
    
    Fails if endpoint has associated image locations (RESTRICT).
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
    if count > 0:
        raise HTTPException(
            400,
            f"Cannot delete endpoint: {count} images are stored here. "
            "Please migrate them first."
        )
    
    await storage_endpoint_repository.delete(session, endpoint)
    await session.commit()
    
    return {"message": "Endpoint deleted"}


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
        from imgtag.core.storage_constants import StorageProvider
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
    
    # Currently only support local -> S3 sync
    if source.provider != "local":
        raise HTTPException(
            400, 
            "目前仅支持从本地端点同步到 S3。S3 → Local 功能开发中。"
        )
    if target.provider == "local":
        raise HTTPException(
            400, 
            "目前仅支持同步到 S3 端点。S3 → Local 功能开发中。"
        )
    
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
