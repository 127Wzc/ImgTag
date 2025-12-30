"""Storage unlink service for endpoint cleanup.

Handles background unlinking of endpoint locations with optional
file deletion and orphan metadata cleanup.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import BATCH_CONFIG, StorageTaskType
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    image_repository,
    storage_endpoint_repository,
)
from imgtag.services.base_storage_task import BaseStorageTaskService, TaskProgress
from imgtag.services.storage_service import storage_service

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
    - Orphan metadata cleanup (images with no other locations)
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
            endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
            if not endpoint:
                raise ValueError(f"Endpoint {endpoint_id} not found")
        
        return UnlinkContext(
            endpoint_id=endpoint_id,
            endpoint=endpoint,
            delete_files=payload.get("delete_files", False),
            initiated_by=payload.get("initiated_by", "system"),
        )
    
    async def get_items_to_process(self, context: UnlinkContext) -> list[Any]:
        """Get all locations for unlinking.
        
        Collects location info and determines which images will become orphans.
        """
        items = []
        async with async_session_maker() as session:
            async for loc in image_location_repository.iter_by_endpoint(
                session, context.endpoint_id, batch_size=BATCH_CONFIG.batch_size
            ):
                # Check if this image will become orphan
                loc_count = await image_location_repository.count_by_image(
                    session, loc.image_id
                )
                is_orphan = loc_count == 1  # Only this location exists
                
                items.append({
                    "location_id": loc.id,
                    "image_id": loc.image_id,
                    "object_key": loc.object_key,
                    "category_code": loc.category_code,
                    "is_orphan": is_orphan,
                })
        return items
    
    async def process_single_item(
        self,
        item: dict,
        context: UnlinkContext,
    ) -> tuple[bool, str | None]:
        """Process a single location: optionally delete file.
        
        File deletion happens here if delete_files is True.
        Location and orphan image deletion happens in on_task_complete.
        """
        if not context.delete_files:
            # No file deletion needed, just mark as success
            return (True, None)
        
        try:
            import os
            
            full_key = storage_service.get_full_object_key(
                item["object_key"], item.get("category_code")
            )
            
            if context.endpoint.provider != "local":
                success = await storage_service.delete_from_endpoint(
                    full_key, context.endpoint
                )
                if not success:
                    return (False, f"Delete returned false for {full_key}")
            else:
                # Local file deletion
                local_path = storage_service.get_local_path(item["object_key"])
                if local_path and os.path.exists(local_path):
                    os.remove(local_path)
            
            return (True, None)
        except Exception as e:
            logger.error(f"Failed to delete {item['object_key']}: {e}")
            return (False, str(e))
    
    async def on_task_complete(
        self,
        progress: TaskProgress,
        context: UnlinkContext,
    ) -> None:
        """Clean up location and orphan image records after processing."""
        async with async_session_maker() as session:
            # Delete all location records for this endpoint
            deleted_locations = await image_location_repository.delete_by_endpoint(
                session, context.endpoint_id
            )
            
            # Delete orphan images if we were deleting files
            deleted_images = 0
            if context.delete_files and progress.extra.get("orphan_image_ids"):
                orphan_ids = progress.extra["orphan_image_ids"]
                deleted_images, _ = await image_repository.delete_by_ids(session, orphan_ids)
            
            await session.commit()
            
            logger.info(
                f"Unlink complete for endpoint {context.endpoint_id}: "
                f"locations={deleted_locations}, images={deleted_images}"
            )
    
    async def run_task(self, task_id: str) -> None:
        """Override to collect orphan image IDs during processing."""
        # Build context first
        async with async_session_maker() as session:
            task = await self._get_task(session, task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return
        
        context = await self.build_context(task_id, task.payload)
        items = await self.get_items_to_process(context)
        
        progress = TaskProgress(
            task_id=task_id,
            task_type=self.TASK_TYPE,
            total_count=len(items),
        )
        
        # Collect orphan image IDs
        orphan_image_ids = [item["image_id"] for item in items if item.get("is_orphan")]
        progress.extra["orphan_image_ids"] = orphan_image_ids
        
        # Call parent's batch processing
        await self._process_items(items, context, progress)
        
        # Complete task
        await self.on_task_complete(progress, context)
    
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
