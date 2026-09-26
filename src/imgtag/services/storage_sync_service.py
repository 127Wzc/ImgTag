"""Storage synchronization service for background file sync.

Handles background synchronization of files between storage endpoints
with checkpoint support and batch processing.
"""

import asyncio
import random
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Optional

from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeoutError

from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import BATCH_CONFIG, StorageTaskStatus, StorageTaskType
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    image_location_repository,
    storage_endpoint_repository,
    task_repository,
)
from imgtag.models.storage_endpoint import StorageEndpoint
from imgtag.services.storage_service import storage_service

logger = get_logger(__name__)


def is_transient_db_error(error: Exception) -> bool:
    """只重试连接压力或连接中断，不重试认证、权限和 SQL 错误。"""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PoolTimeoutError):
            return True
        if isinstance(current, DBAPIError) and current.connection_invalidated:
            return True
        state = getattr(current, "sqlstate", None)
        if state and (state.startswith("08") or state in {"53300", "57P01", "57P02", "57P03"}):
            return True
        if "EMAXCONNSESSION" in str(current):
            return True
        current = getattr(current, "orig", None) or current.__cause__ or current.__context__
    return False


def retry_sync_db(operation):
    """重试幂等数据库操作；每次调用自行创建、关闭 session，等待时不占连接。"""
    @wraps(operation)
    async def wrapped(*args, **kwargs):
        for attempt in range(1, settings.STORAGE_SYNC_DB_MAX_ATTEMPTS + 1):
            try:
                return await operation(*args, **kwargs)
            except Exception as error:
                if not is_transient_db_error(error) or attempt == settings.STORAGE_SYNC_DB_MAX_ATTEMPTS:
                    raise
                delay = min(settings.STORAGE_SYNC_DB_RETRY_DELAY * 2 ** (attempt - 1), 30)
                delay += random.uniform(0, delay * 0.2)
                logger.warning("同步数据库暂时不可用：%s，第 %s 次失败，%.1f 秒后重试",
                               getattr(operation, "__name__", "database_operation"), attempt, delay)
                await asyncio.sleep(delay)
    return wrapped


class StorageSyncService:
    """Background storage synchronization service.
    
    Manages sync tasks between storage endpoints with:
    - Batch processing with configurable size
    - Checkpoint updates every N images
    - Retry support
    - Force overwrite option
    """

    TASK_TYPE = StorageTaskType.SYNC
    BATCH_CONFIG = BATCH_CONFIG  # Use unified config

    def __init__(self):
        self._running = False
        self._sync_semaphore = asyncio.Semaphore(settings.STORAGE_SYNC_CONCURRENCY)

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
                    session, source_endpoint_id, batch_size=BATCH_CONFIG.batch_size
                ):
                    image_ids.append(loc.image_id)
                    
                    # Create task for each complete batch
                    if len(image_ids) >= BATCH_CONFIG.batch_size:
                        batch_index = len(task_ids)
                        task_id = str(uuid.uuid4())
                        await task_repository.create_task(
                            session,
                            task_id=task_id,
                            task_type=self.TASK_TYPE.value,
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
                        task_type=self.TASK_TYPE.value,
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
            
            total_batches = (len(image_ids) + BATCH_CONFIG.batch_size - 1) // BATCH_CONFIG.batch_size
            
            # Split into batches
            for i in range(0, len(image_ids), BATCH_CONFIG.batch_size):
                batch = image_ids[i:i + BATCH_CONFIG.batch_size]
                batch_index = i // BATCH_CONFIG.batch_size
                
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
                try:
                    await self._mark_task_failed(task_id, str(e))
                except Exception:
                    # 数据库完全不可用时无法持久化失败状态，明确记录，避免后台异常丢失。
                    logger.exception("同步任务 %s 已停止，但无法保存失败状态，请恢复连接后重新同步", task_id)

    @retry_sync_db
    async def _mark_task_failed(self, task_id: str, error: str) -> None:
        async with async_session_maker() as session:
            await task_repository.update_status(session, task_id, "failed", error=error)
            await session.commit()

    @retry_sync_db
    async def _load_sync_task(
        self, task_id: str,
    ) -> tuple[dict[str, Any], StorageEndpoint, StorageEndpoint] | None:
        async with async_session_maker() as session:
            task = await task_repository.get_by_id(session, task_id)
            if not task:
                return None
            payload = dict(task.payload or {})
            source = await storage_endpoint_repository.get_by_id(session, payload.get("source_endpoint_id"))
            target = await storage_endpoint_repository.get_by_id(session, payload.get("target_endpoint_id"))
            if not source or not target:
                raise ValueError("Invalid source or target endpoint")
            await task_repository.update_status(session, task_id, "processing")
            await session.commit()
            return payload, source, target

    async def _do_sync_task(self, task_id: str) -> None:
        loaded = await self._load_sync_task(task_id)
        if loaded is None:
            return
        payload, source_endpoint, target_endpoint = loaded
        image_ids = payload.get("image_ids", [])
        force_overwrite = payload.get("force_overwrite", False)

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
                if is_transient_db_error(e):
                    # 持续拥塞时停止本批，避免把后续图片全部快速记为失败。
                    raise
                failed += 1
                if len(failed_ids) < 50:
                    failed_ids.append({"id": image_id, "error": str(e)})
                logger.error(f"Failed to sync image {image_id}: {e}")
            
            # Checkpoint every N images
            if (i + 1) % BATCH_CONFIG.checkpoint_interval == 0:
                await self._update_progress(task_id, completed, failed, failed_ids)
            
            # Rate limiting
            await asyncio.sleep(BATCH_CONFIG.rate_limit_seconds)
        
        # Final update
        await self._update_progress(task_id, completed, failed, failed_ids, final=True)
        logger.info(f"Sync task {task_id} completed: {completed} success, {failed} failed")

    @retry_sync_db
    async def _load_sync_locations(
        self, image_id: int, source_endpoint: StorageEndpoint, target_endpoint: StorageEndpoint,
    ) -> tuple[str, str | None, bool]:
        async with async_session_maker() as session:
            source = await image_location_repository.get_by_image_and_endpoint(
                session, image_id, source_endpoint.id
            )
            if source is None:
                raise ValueError(f"图片 {image_id} 没有源端点记录")
            target = await image_location_repository.get_by_image_and_endpoint(
                session, image_id, target_endpoint.id
            )
            return source.object_key, source.category_code, bool(target and target.sync_status == "synced")

    @retry_sync_db
    async def _save_sync_location(
        self, image_id: int, target_endpoint: StorageEndpoint,
        object_key: str, category_code: str | None,
    ) -> None:
        async with async_session_maker() as session:
            # 重读记录以支持提交结果不确定后的重试。
            target = await image_location_repository.get_by_image_and_endpoint(
                session, image_id, target_endpoint.id
            )
            if target:
                await image_location_repository.mark_synced(session, target.id)
            else:
                await image_location_repository.create(
                    session, image_id=image_id, endpoint_id=target_endpoint.id,
                    object_key=object_key, category_code=category_code,
                    sync_status="synced", synced_at=datetime.now(timezone.utc),
                )
            await session.commit()

    async def _sync_single_image(
        self, image_id: int, source_endpoint: StorageEndpoint,
        target_endpoint: StorageEndpoint, force_overwrite: bool,
    ) -> bool:
        object_key, category_code, synced = await self._load_sync_locations(
            image_id, source_endpoint, target_endpoint
        )
        # 本地检查和 S3 传输期间，数据库 session 已关闭。
        if synced and not force_overwrite:
            if await storage_service.file_exists(object_key, target_endpoint):
                return True
        content = await storage_service.download_from_endpoint(object_key, source_endpoint)
        if not content:
            logger.error("无法从源端点下载图片 %s", image_id)
            return False
        if not await storage_service.verify_content_hash(content, object_key):
            logger.error("图片 %s 的源内容与文件名哈希不符，停止写入目标", image_id)
            return False
        if not await storage_service.upload_to_endpoint(content, object_key, target_endpoint):
            logger.error("无法写入目标端点：图片 %s", image_id)
            return False
        # 保存元数据失败时只重试数据库写入，不重复下载已传输的图片。
        await self._save_sync_location(image_id, target_endpoint, object_key, category_code)
        return True

    @retry_sync_db
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
                "success_count": completed,  # 统一字段名
                "failed_count": failed,
                "failed_items": failed_ids,  # 统一字段名
            }
            
            status = (StorageTaskStatus.FAILED.value if failed else StorageTaskStatus.COMPLETED.value) if final else StorageTaskStatus.PROCESSING.value
            await task_repository.update_status(
                session, task_id, status, result=result,
                error=f"{failed} 张图片同步失败，请重新发起同步" if final and failed else None
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
            completed = result.get("success_count", 0)
            failed = result.get("failed_count", 0)
            
            return {
                "task_id": task_id,
                "task_type": task.type,
                "status": task.status,
                "total_count": total,
                "success_count": completed,
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
            items = [(loc.id, loc.image_id, loc.endpoint_id) for loc in pending]

        for location_id, image_id, endpoint_id in items:
            try:
                endpoints = await self._load_pending_endpoints(location_id, image_id, endpoint_id)
                if endpoints is None:
                    continue
                source, target = endpoints
                success = await self._sync_single_image(image_id, source, target, False)
                processed += int(success)
            except Exception as error:
                logger.exception("自动同步图片 %s 失败", image_id)
                if is_transient_db_error(error):
                    break
            await asyncio.sleep(BATCH_CONFIG.rate_limit_seconds)
        return processed

    @retry_sync_db
    async def _load_pending_endpoints(
        self, location_id: int, image_id: int, endpoint_id: int,
    ) -> tuple[StorageEndpoint, StorageEndpoint] | None:
        async with async_session_maker() as session:
            primary = await image_location_repository.get_primary_location(session, image_id)
            source = await storage_endpoint_repository.get_by_id(session, primary.endpoint_id) if primary else None
            target = await storage_endpoint_repository.get_by_id(session, endpoint_id)
            if not source or not target:
                await image_location_repository.mark_failed(session, location_id, "Source or target endpoint not found")
                await session.commit()
                return None
            return source, target


# Singleton instance
storage_sync_service = StorageSyncService()
