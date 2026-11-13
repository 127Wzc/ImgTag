"""Storage unlink service for endpoint cleanup.

Handles background unlinking of endpoint locations with optional
file deletion. Images without remaining locations are removed only when deleting files.
"""

from dataclasses import dataclass
from typing import Any

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import BATCH_CONFIG, StorageTaskType
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
)
from imgtag.services.base_storage_task import BaseStorageTaskService
from imgtag.services.storage_service import storage_service
from imgtag.services.storage_task_control import load_endpoint_snapshot

logger = get_logger(__name__)


@dataclass
class UnlinkContext:
    """Context for unlink task."""
    endpoint_id: int
    endpoint: Any  # StorageEndpoint model
    delete_files: bool
    initiated_by: str


class StorageUnlinkService(BaseStorageTaskService[UnlinkContext]):
    """Background storage unlink service.
    
    Handles endpoint unlinking with:
    - Optional physical file deletion
    - Per-item location cleanup, removing images with no copies when deleting files
    - Batch processing with progress tracking
    """
    
    TASK_TYPE = StorageTaskType.UNLINK
    
    async def start_unlink(
        self,
        endpoint_id: int,
        delete_files: bool = False,
        initiated_by: str = "system",
    ) -> str:
        """Start unlink task for an endpoint.
        
        Args:
            endpoint_id: Endpoint to unlink.
            delete_files: Whether to delete physical files.
            initiated_by: Username who initiated the operation.
            
        Returns:
            Task ID for tracking progress.
        """
        async with async_session_maker() as session:
            # Validate endpoint
            endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
            if not endpoint:
                raise ValueError(f"Endpoint {endpoint_id} not found")
            
            # Count total locations
            total_count = await image_location_repository.count_by_endpoint(
                session, endpoint_id
            )
            
            # Create task via base class
            return await self.create_task(
                payload={
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint.name,
                    "delete_files": delete_files,
                    "total_count": total_count,
                },
                initiated_by=initiated_by,
            )
    
    async def build_context(
        self, 
        task_id: str, 
        payload: dict,
    ) -> UnlinkContext:
        """Build unlink context from payload."""
        endpoint_id = payload["endpoint_id"]
        
        async with async_session_maker() as session:
            endpoint = await load_endpoint_snapshot(session, payload.get("endpoint_snapshot"), endpoint_id)
            if not endpoint:
                raise ValueError("端点不存在")

        return UnlinkContext(
            endpoint_id=endpoint_id,
            endpoint=endpoint,
            delete_files=payload.get("delete_files", False),
            initiated_by=payload.get("initiated_by", "system"),
        )
    
    async def get_items_to_process(self, context: UnlinkContext) -> list[Any]:
        """Get all locations for unlinking.
        
        Collects stable location IDs and object keys.
        """
        items = []
        async with async_session_maker() as session:
            async for loc in image_location_repository.iter_by_endpoint(
                session, context.endpoint_id, batch_size=BATCH_CONFIG.batch_size
            ):
                items.append({
                    "location_id": loc.id,
                    "image_id": loc.image_id,
                    "object_key": loc.object_key,
                    "category_code": loc.category_code,
                })
        return items
    
    async def process_single_item(
        self,
        item: dict,
        context: UnlinkContext,
    ) -> tuple[bool, str | None]:
        """Process a single location: optionally delete file.
        
        File deletion happens here if delete_files is True.
        The base runner commits location removal only after this item succeeds.
        """
        if not context.delete_files:
            # No file deletion needed, just mark as success
            return (True, None)
        
        try:
            async with async_session_maker() as session:
                references = await image_location_repository.count_by_object_key(
                    session, context.endpoint_id, item["object_key"]
                )
            if references > 1:
                return (True, None)
            # Use delete_from_endpoint for both local and S3 endpoints
            # This method correctly handles path_prefix for all provider types
            success = await storage_service.delete_from_endpoint(
                item["object_key"], context.endpoint
            )
            if not success:
                return (False, f"Delete returned false for {item['object_key']}")
            
            return (True, None)
        except Exception as e:
            logger.error(f"Failed to delete {item['object_key']}: {e}")
            return (False, str(e))
    
    async def get_unlink_progress(self, task_id: str) -> dict:
        """Get unlink task progress."""
        result = await self.get_progress(task_id)
        
        if "error" in result:
            return result
        
        payload = result.get("payload", {})
        return {
            "task_id": task_id,
            "status": result["status"],
            "endpoint_id": payload.get("endpoint_id"),
            "endpoint_name": payload.get("endpoint_name"),
            "delete_files": payload.get("delete_files", False),
            "total_count": result["total_count"],
            "success_count": result["success_count"],
            "failed_count": result["failed_count"],
            "progress_percent": result["progress_percent"],
        }


# Singleton instance
storage_unlink_service = StorageUnlinkService()
