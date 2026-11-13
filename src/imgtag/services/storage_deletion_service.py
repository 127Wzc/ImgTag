"""Storage deletion service for background file deletion.

Handles background deletion of files from storage endpoints
with checkpoint support and batch processing.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import BATCH_CONFIG, StorageTaskType
from imgtag.core.storage_runtime import notify_storage_tasks
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    image_repository,
    storage_endpoint_repository,
)
from imgtag.services.base_storage_task import BaseStorageTaskService
from imgtag.services.storage_service import storage_service
from imgtag.services.storage_task_control import load_endpoint_snapshot

logger = get_logger(__name__)


@dataclass
class DeletionContext:
    """Context for deletion task."""
    endpoint_id: int
    endpoint: Any  # StorageEndpoint model
    initiated_by: str
    object_keys: list[str] | None = None


class StorageDeletionService(BaseStorageTaskService[DeletionContext]):
    """Background storage deletion service.
    
    Deletes files from storage endpoints with:
    - Batch processing with configurable size
    - Per-file progress checkpoints
    - Endpoint-wide or selected object deletion with shared-reference checks
    """
    
    TASK_TYPE = StorageTaskType.DELETE
    # Use unified BATCH_CONFIG from constants

    async def delete_images(
        self, session, image_ids: list[int], *, owner_id: int | None,
        delete_files: bool, initiated_by: str,
    ) -> dict:
        """图片记录删除与文件清理任务在同一事务提交，冲突时全部回滚。"""
        files_by_endpoint: dict[int, set[str]] = defaultdict(set)
        task_ids = []
        if delete_files:
            await storage_endpoint_repository.lock_all(session)
            files = await image_location_repository.get_files_for_images(session, image_ids, owner_id)
            for endpoint_id, object_key in files:
                files_by_endpoint[endpoint_id].add(object_key)
            for endpoint_id, object_keys in sorted(files_by_endpoint.items()):
                task_ids.append(await self.enqueue_task(session, {
                    "endpoint_id": endpoint_id, "object_keys": sorted(object_keys),
                }, initiated_by))
        deleted_count, _ = await image_repository.delete_by_ids(session, image_ids, owner_id=owner_id)
        await session.commit()
        if task_ids:
            notify_storage_tasks()
        return {"deleted_count": deleted_count, "task_ids": task_ids,
                "files_scheduled": sum(len(keys) for keys in files_by_endpoint.values())}
    
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
            endpoint = await load_endpoint_snapshot(session, payload.get("endpoint_snapshot"), endpoint_id)
            if not endpoint:
                raise ValueError("端点不存在")

        return DeletionContext(
            endpoint_id=endpoint_id,
            endpoint=endpoint,
            initiated_by=payload.get("initiated_by", "system"),
            object_keys=payload.get("object_keys"),
        )
    
    async def get_items_to_process(self, context: DeletionContext) -> list[Any]:
        """Get all locations for deletion."""
        if context.object_keys is not None:
            return [{"object_key": key} for key in context.object_keys]
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
            full_key = item["object_key"]
            # 相同对象可由多张图片引用；逐条提交解除关联，最后一条才删文件。
            async with async_session_maker() as session:
                references = await image_location_repository.count_by_object_key(
                    session, context.endpoint_id, full_key
                )
            if references > (0 if context.object_keys is not None else 1):
                return (True, None)
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
