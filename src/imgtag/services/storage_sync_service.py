"""Storage synchronization service for background file sync.

Handles background synchronization of files between storage endpoints
with checkpoint support and batch processing.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from imgtag.core.logging_config import get_logger
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
    task_repository,
)
from imgtag.services.storage_service import storage_service

logger = get_logger(__name__)


class StorageSyncService:
    """Background storage synchronization service.
    
    Manages sync tasks between storage endpoints with:
    - Batch processing with configurable size
    - Checkpoint updates every N images
    - Retry support
    - Force overwrite option
    """

    BATCH_SIZE = 500  # Max images per task
    CHECKPOINT_INTERVAL = 100  # Update DB every N images
    MAX_CONCURRENT_SYNCS = 2  # Concurrent sync operations
    SYNC_INTERVAL_SECONDS = 1.0  # Delay between sync operations

    def __init__(self):
        self._running = False
        self._sync_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_SYNCS)

    async def start_batch_sync(
        self,
        source_endpoint_id: int,
        target_endpoint_id: int,
        image_ids: Optional[list[int]] = None,
        force_overwrite: bool = False,
    ) -> list[str]:
        """Start batch synchronization task(s).
        
        Automatically splits into multiple tasks if > BATCH_SIZE images.
        
        Args:
            source_endpoint_id: Source endpoint ID.
            target_endpoint_id: Target endpoint ID.
            image_ids: Optional list of image IDs. If None, syncs all from source.
            force_overwrite: Whether to overwrite existing files.
            
        Returns:
            List of task IDs created.
        """
        task_ids = []
        
        async with async_session_maker() as session:
            # If no image_ids provided, stream from source endpoint
            if image_ids is None:
                # Stream image IDs in batches to avoid memory issues with large datasets
                image_ids = []
                async for loc in image_location_repository.iter_by_endpoint(
                    session, source_endpoint_id, batch_size=self.BATCH_SIZE
                ):
                    image_ids.append(loc.image_id)
                    
                    # Create task for each complete batch
                    if len(image_ids) >= self.BATCH_SIZE:
                        batch_index = len(task_ids)
                        task_id = str(uuid.uuid4())
                        await task_repository.create_task(
                            session,
                            task_id=task_id,
                            task_type="storage_sync",
                            payload={
                                "sync_type": "batch",
                                "source_endpoint_id": source_endpoint_id,
                                "target_endpoint_id": target_endpoint_id,
                                "image_ids": image_ids.copy(),
                                "batch_size": len(image_ids),
                                "batch_index": batch_index,
                                "force_overwrite": force_overwrite,
                            },
                        )
                        task_ids.append(task_id)
                        image_ids.clear()
                
                # Handle remaining images
                if image_ids:
                    batch_index = len(task_ids)
                    task_id = str(uuid.uuid4())
                    await task_repository.create_task(
                        session,
                        task_id=task_id,
                        task_type="storage_sync",
                        payload={
                            "sync_type": "batch",
                            "source_endpoint_id": source_endpoint_id,
                            "target_endpoint_id": target_endpoint_id,
                            "image_ids": image_ids,
                            "batch_size": len(image_ids),
                            "batch_index": batch_index,
                            "force_overwrite": force_overwrite,
                        },
                    )
                    task_ids.append(task_id)
                
                # Update total_batches in all tasks
                if task_ids:
                    for task_id in task_ids:
                        await task_repository.update_payload_field(
                            session, task_id, "total_batches", len(task_ids)
                        )
                    await session.commit()
                    logger.info(f"Created {len(task_ids)} sync tasks")
                    
                    # Start processing tasks in background
                    for task_id in task_ids:
                        asyncio.create_task(self._process_sync_task(task_id))
                else:
                    logger.info("No images to sync")
                return task_ids
            
            # If image_ids provided directly, use the original batch logic
            if not image_ids:
                logger.info("No images to sync")
                return []
            
            total_batches = (len(image_ids) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
            
            # Split into batches
            for i in range(0, len(image_ids), self.BATCH_SIZE):
                batch = image_ids[i:i + self.BATCH_SIZE]
                batch_index = i // self.BATCH_SIZE
                
                task_id = str(uuid.uuid4())
                await task_repository.create_task(
                    session,
                    task_id=task_id,
                    task_type="storage_sync",
                    payload={
                        "sync_type": "batch",
                        "source_endpoint_id": source_endpoint_id,
                        "target_endpoint_id": target_endpoint_id,
                        "image_ids": batch,
                        "batch_size": len(batch),
                        "batch_index": batch_index,
                        "total_batches": total_batches,
                        "force_overwrite": force_overwrite,
                    },
                )
                task_ids.append(task_id)
                
                logger.info(
                    f"Created sync task {task_id}: batch {batch_index + 1}/{total_batches}, "
                    f"{len(batch)} images"
                )
            
            await session.commit()
        
        # Start processing tasks in background
        for task_id in task_ids:
            asyncio.create_task(self._process_sync_task(task_id))
        
        return task_ids

    async def _process_sync_task(self, task_id: str) -> None:
        """Process a sync task with checkpoint support."""
        async with self._sync_semaphore:
            try:
                await self._do_sync_task(task_id)
            except Exception as e:
                logger.error(f"Sync task {task_id} failed: {e}")
                async with async_session_maker() as session:
                    await task_repository.update_status(
                        session, task_id, "failed", error=str(e)
                    )
                    await session.commit()

    async def _do_sync_task(self, task_id: str) -> None:
        """Execute sync task with progress tracking."""
        async with async_session_maker() as session:
            task = await task_repository.get_by_id(session, task_id)
            if not task:
                return
            
            await task_repository.update_status(session, task_id, "processing")
            await session.commit()
        
        payload = task.payload or {}
        source_endpoint_id = payload.get("source_endpoint_id")
        target_endpoint_id = payload.get("target_endpoint_id")
        image_ids = payload.get("image_ids", [])
        force_overwrite = payload.get("force_overwrite", False)
        
        # Get endpoints
        async with async_session_maker() as session:
            source_endpoint = await storage_endpoint_repository.get_by_id(
                session, source_endpoint_id
            )
            target_endpoint = await storage_endpoint_repository.get_by_id(
                session, target_endpoint_id
            )
        
        if not source_endpoint or not target_endpoint:
            raise ValueError("Invalid source or target endpoint")
        
        # Process images
        completed = 0
        failed = 0
        failed_ids = []
        
        for i, image_id in enumerate(image_ids):
            try:
                success = await self._sync_single_image(
                    image_id,
                    source_endpoint,
                    target_endpoint,
                    force_overwrite,
                )
                if success:
                    completed += 1
                else:
                    failed += 1
                    if len(failed_ids) < 50:
                        failed_ids.append({"id": image_id, "error": "Sync returned false"})
            except Exception as e:
                failed += 1
                if len(failed_ids) < 50:
                    failed_ids.append({"id": image_id, "error": str(e)})
                logger.error(f"Failed to sync image {image_id}: {e}")
            
            # Checkpoint every N images
            if (i + 1) % self.CHECKPOINT_INTERVAL == 0:
                await self._update_progress(task_id, completed, failed, failed_ids)
            
            # Rate limiting
            await asyncio.sleep(self.SYNC_INTERVAL_SECONDS)
        
        # Final update
        await self._update_progress(task_id, completed, failed, failed_ids, final=True)
        logger.info(f"Sync task {task_id} completed: {completed} success, {failed} failed")

    async def _sync_single_image(
        self,
        image_id: int,
        source_endpoint,
        target_endpoint,
        force_overwrite: bool,
    ) -> bool:
        """Sync a single image between endpoints."""
        async with async_session_maker() as session:
            # Get source location
            source_location = await image_location_repository.get_by_image_and_endpoint(
                session, image_id, source_endpoint.id
            )
            if not source_location:
                logger.warning(f"No source location for image {image_id}")
                return False
            
            object_key = source_location.object_key
            
            # Check if already exists at target
            target_location = await image_location_repository.get_by_image_and_endpoint(
                session, image_id, target_endpoint.id
            )
            
            if target_location and target_location.sync_status == "synced":
                if not force_overwrite:
                    # Already synced, check if file exists
                    exists = await storage_service.file_exists(object_key, target_endpoint)
                    if exists:
                        logger.debug(f"Image {image_id} already synced, skipping")
                        return True
            
            # Download from source
            content = await storage_service.download_from_endpoint(
                object_key, source_endpoint
            )
            if not content:
                logger.error(f"Failed to download image {image_id} from source")
                return False
            
            # Upload to target
            success = await storage_service.upload_to_endpoint(
                content, object_key, target_endpoint
            )
            if not success:
                if target_location:
                    await image_location_repository.mark_failed(
                        session, target_location.id, "Upload failed"
                    )
                    await session.commit()
                return False
            
            # Create or update location record
            if target_location:
                await image_location_repository.mark_synced(session, target_location.id)
            else:
                await image_location_repository.create(
                    session,
                    image_id=image_id,
                    endpoint_id=target_endpoint.id,
                    object_key=object_key,
                    sync_status="synced",
                    synced_at=datetime.now(timezone.utc),
                )
            
            await session.commit()
            return True

    async def _update_progress(
        self,
        task_id: str,
        completed: int,
        failed: int,
        failed_ids: list,
        final: bool = False,
    ) -> None:
        """Update task progress in database."""
        async with async_session_maker() as session:
            result = {
                "completed_count": completed,
                "failed_count": failed,
                "failed_ids": failed_ids,
            }
            
            status = "completed" if final else "processing"
            await task_repository.update_status(
                session, task_id, status, result=result
            )
            await session.commit()

    async def get_sync_progress(self, task_id: str) -> dict:
        """Get sync task progress.
        
        Args:
            task_id: Task ID to query.
            
        Returns:
            Progress information dict.
        """
        async with async_session_maker() as session:
            task = await task_repository.get_by_id(session, task_id)
            if not task:
                return {"error": "Task not found"}
            
            payload = task.payload or {}
            result = task.result or {}
            
            total = payload.get("batch_size", 0)
            completed = result.get("completed_count", 0)
            failed = result.get("failed_count", 0)
            
            return {
                "task_id": task_id,
                "status": task.status,
                "total_count": total,
                "completed_count": completed,
                "failed_count": failed,
                "progress_percent": round(
                    (completed + failed) / max(total, 1) * 100, 2
                ),
                "batch_index": payload.get("batch_index"),
                "total_batches": payload.get("total_batches"),
            }

    async def process_pending_locations(self, limit: int = 100) -> int:
        """Process pending sync locations (for auto-mirror).
        
        Called periodically by background worker to sync pending items.
        
        Args:
            limit: Maximum locations to process.
            
        Returns:
            Number of locations processed.
        """
        processed = 0
        
        async with async_session_maker() as session:
            pending = await image_location_repository.get_pending_sync(session, limit=limit)
            
            for location in pending:
                # Get source location (primary)
                primary = await image_location_repository.get_primary_location(
                    session, location.image_id
                )
                if not primary:
                    await image_location_repository.mark_failed(
                        session, location.id, "No primary location"
                    )
                    continue
                
                # Get endpoints
                source_endpoint = await storage_endpoint_repository.get_by_id(
                    session, primary.endpoint_id
                )
                target_endpoint = await storage_endpoint_repository.get_by_id(
                    session, location.endpoint_id
                )
                
                if not source_endpoint or not target_endpoint:
                    await image_location_repository.mark_failed(
                        session, location.id, "Endpoint not found"
                    )
                    continue
                
                # Sync
                try:
                    success = await self._sync_single_image(
                        location.image_id,
                        source_endpoint,
                        target_endpoint,
                        force_overwrite=False,
                    )
                    processed += 1 if success else 0
                except Exception as e:
                    logger.error(f"Auto-sync failed for location {location.id}: {e}")
                
                await asyncio.sleep(self.SYNC_INTERVAL_SECONDS)
            
            await session.commit()
        
        return processed


# Singleton instance
storage_sync_service = StorageSyncService()
