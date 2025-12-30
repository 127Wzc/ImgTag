"""Storage deletion service for background file deletion.

Handles background deletion of files from storage endpoints
with checkpoint support and batch processing.
"""

import asyncio
from dataclasses import dataclass
from typing import Any

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import BATCH_CONFIG, StorageTaskType
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
)
from imgtag.services.base_storage_task import BaseStorageTaskService, TaskProgress
from imgtag.services.storage_service import storage_service

logger = get_logger(__name__)


@dataclass
class DeletionContext:
    """Context for deletion task."""
    endpoint_id: int
    endpoint: Any  # StorageEndpoint model
    initiated_by: str


class StorageDeletionService(BaseStorageTaskService[DeletionContext]):
    """Background storage deletion service.
    
    Deletes files from storage endpoints with:
    - Batch processing with configurable size
    - Checkpoint updates every N files
    - Concurrent deletion within batches
    """
    
    TASK_TYPE = StorageTaskType.DELETE
    # Use unified BATCH_CONFIG from constants
    
    async def start_hard_delete(
        self,
        endpoint_id: int,
        initiated_by: str = "system",
    ) -> str:
        """Start hard deletion task for an endpoint.
        
        Args:
            endpoint_id: Endpoint to delete files from.
            initiated_by: Username who initiated the deletion.
            
        Returns:
            Task ID for tracking progress.
        """
        async with async_session_maker() as session:
            # Validate endpoint
            endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
            if not endpoint:
                raise ValueError(f"Endpoint {endpoint_id} not found")
            
            # Count total files
            total_count = await image_location_repository.count_by_endpoint(
                session, endpoint_id
            )
            
            # Create task via base class
            return await self.create_task(
                payload={
                    "endpoint_id": endpoint_id,
                    "endpoint_name": endpoint.name,
                    "total_count": total_count,
                },
                initiated_by=initiated_by,
            )
    
    async def build_context(
        self, 
        task_id: str, 
        payload: dict,
    ) -> DeletionContext:
        """Build deletion context from payload."""
        endpoint_id = payload["endpoint_id"]
        
        async with async_session_maker() as session:
            endpoint = await storage_endpoint_repository.get_by_id(session, endpoint_id)
            if not endpoint:
                raise ValueError(f"Endpoint {endpoint_id} not found")
        
        return DeletionContext(
            endpoint_id=endpoint_id,
            endpoint=endpoint,
            initiated_by=payload.get("initiated_by", "system"),
        )
    
    async def get_items_to_process(self, context: DeletionContext) -> list[Any]:
        """Get all locations for deletion."""
        items = []
        async with async_session_maker() as session:
            async for loc in image_location_repository.iter_by_endpoint(
                session, context.endpoint_id, batch_size=BATCH_CONFIG.batch_size
            ):
                # 只存储需要的字段，避免 session 问题
                items.append({
                    "id": loc.id,
                    "object_key": loc.object_key,
                    "category_code": loc.category_code,
                })
        return items
    
    async def process_single_item(
        self,
        item: dict,
        context: DeletionContext,
    ) -> tuple[bool, str | None]:
        """Delete a single file from endpoint."""
        try:
            full_key = storage_service.get_full_object_key(
                item["object_key"], item.get("category_code")
            )
            success = await storage_service.delete_from_endpoint(
                full_key, context.endpoint
            )
            if success:
                return (True, None)
            else:
                return (False, f"Delete returned false for {full_key}")
        except Exception as e:
            logger.error(f"Failed to delete {item['object_key']}: {e}")
            return (False, str(e))
    
    async def on_task_complete(
        self,
        progress: TaskProgress,
        context: DeletionContext,
    ) -> None:
        """Clean up location records after deletion."""
        # Only delete records if task completed successfully
        if progress.status.value == "completed":
            async with async_session_maker() as session:
                await image_location_repository.delete_by_endpoint(
                    session, context.endpoint_id
                )
                await session.commit()
                logger.info(
                    f"Deleted location records for endpoint {context.endpoint_id}"
                )
    
    async def get_deletion_progress(self, task_id: str) -> dict:
        """Get deletion task progress (legacy interface)."""
        result = await self.get_progress(task_id)
        
        if "error" in result:
            return result
        
        # Adapt to legacy field names
        payload = result.get("payload", {})
        return {
            "task_id": task_id,
            "status": result["status"],
            "endpoint_id": payload.get("endpoint_id"),
            "endpoint_name": payload.get("endpoint_name"),
            "total_count": result["total_count"],
            "deleted_count": result["success_count"],
            "failed_count": result["failed_count"],
            "progress_percent": result["progress_percent"],
        }


# Singleton instance
storage_deletion_service = StorageDeletionService()
