"""Base storage task service for background operations.

Provides abstract base class and common utilities for storage-related
background tasks like sync and deletion.
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import (
    BATCH_CONFIG,
    BatchConfig,
    StorageTaskStatus,
    StorageTaskType,
)
from imgtag.core.storage_runtime import notify_storage_tasks, record_storage_progress
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import image_location_repository, storage_endpoint_repository, task_repository
from imgtag.services.storage_task_control import snapshot_endpoint, storage_task_control

logger = get_logger(__name__)

# Generic type for task context
T = TypeVar("T")


@dataclass
class TaskProgress:
    """Progress tracking for storage tasks."""
    
    task_id: str
    task_type: StorageTaskType
    status: StorageTaskStatus = StorageTaskStatus.PENDING
    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    failed_items: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    
    @property
    def processed_count(self) -> int:
        return self.success_count + self.failed_count
    
    @property
    def progress_percent(self) -> float:
        if self.total_count == 0:
            return 0.0
        return (self.processed_count / self.total_count) * 100
    
    def to_result_dict(self) -> dict:
        """Convert to result dict for database storage."""
        return {
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "failed_items": self.failed_items[:50],  # Limit stored failures
            **self.extra,
        }


class BaseStorageTaskService(ABC, Generic[T]):
    """Abstract base class for storage task services.
    
    Provides common infrastructure for:
    - Task creation and tracking
    - Batch processing with checkpoints
    - Progress updates
    - Error handling
    
    Subclasses implement specific logic via abstract methods.
    """
    
    # Must be set by subclass
    TASK_TYPE: StorageTaskType
    
    # Batch configuration
    BATCH_CONFIG: BatchConfig = BATCH_CONFIG
    
    # ========== Abstract Methods (must implement) ==========
    
    @abstractmethod
    async def get_items_to_process(self, context: T) -> list[Any]:
        """Get list of items to process for this task.
        
        Args:
            context: Task-specific context object.
            
        Returns:
            List of items to process.
        """
        ...
    
    @abstractmethod
    async def process_single_item(
        self, 
        item: Any, 
        context: T,
    ) -> tuple[bool, str | None]:
        """Process a single item.
        
        Args:
            item: The item to process.
            context: Task-specific context object.
            
        Returns:
            Tuple of (success, error_message).
        """
        ...
    
    @abstractmethod
    async def build_context(self, task_id: str, payload: dict) -> T:
        """Build context object from task payload.
        
        Args:
            task_id: The task ID.
            payload: Task payload from database.
            
        Returns:
            Context object for processing.
        """
        ...
    
    # ========== Task Creation ==========
    
    async def create_task(
        self,
        payload: dict,
        initiated_by: str = "system",
    ) -> str:
        """Create a new task and start processing.
        
        Args:
            payload: Task-specific payload data.
            initiated_by: Username who initiated.
            
        Returns:
            Task ID.
        """
        async with async_session_maker() as session:
            task_id = await self.enqueue_task(session, payload, initiated_by)
            await session.commit()

        # 提交后唤醒统一调度
        notify_storage_tasks()
        
        logger.info(f"Created {self.TASK_TYPE.value} task: {task_id}")
        return task_id

    async def enqueue_task(self, session, payload: dict, initiated_by: str = "system") -> str:
        """在调用方事务内登记任务；提交后由调用方唤醒调度。"""
        endpoint_id = payload["endpoint_id"]
        endpoints = await storage_endpoint_repository.lock_all(session)
        endpoint = next((ep for ep in endpoints if ep.id == endpoint_id), None)
        if endpoint is None:
            raise ValueError("端点不存在")
        if await storage_endpoint_repository.has_cleanup_task(session, endpoint_id) or await task_repository.get_active_for_endpoint(session, endpoint_id, StorageTaskType.all_values()):
            raise ValueError("端点已有进行中的任务，请等待完成或先中断")
        endpoint.operation_generation += 1
        task_id = str(uuid.uuid4())
        payload.update(initiated_by=initiated_by, created_at=datetime.now(timezone.utc).isoformat(),
                       endpoint_snapshot=snapshot_endpoint(endpoint), endpoint_name=endpoint.name)
        payload["total_count"] = (len(payload["object_keys"]) if "object_keys" in payload else
                                 await image_location_repository.count_by_endpoint(session, endpoint_id))
        await task_repository.create_task(session, task_id=task_id, task_type=self.TASK_TYPE.value, payload=payload)
        return task_id
    
    # ========== Task Execution ==========
    
    async def _run_task(self, task_id: str) -> None:
        await storage_task_control.run(task_id, lambda: self._execute(task_id))

    async def _execute(self, task_id: str) -> None:
        async with async_session_maker() as session:
            task = await task_repository.get_by_id(session, task_id)
            payload, result = task.payload or {}, task.result or {}
        context = await self.build_context(task_id, payload)
        items = await self.get_items_to_process(context)
        progress = TaskProgress(task_id=task_id, task_type=self.TASK_TYPE,
            status=StorageTaskStatus.PROCESSING, total_count=payload.get("total_count", len(items)),
            success_count=result.get("success_count", 0), failed_count=0)
        await self._process_items(items, progress, context)
        progress.status = StorageTaskStatus.FAILED if progress.failed_count else StorageTaskStatus.COMPLETED
        await self._update_progress(progress, final=True)

    async def _process_items(self, items: list[Any], progress: TaskProgress, context: T) -> None:
        consecutive_failures = 0
        for item in items:
            # 在网络请求前验证租约；网络期间不持有数据库锁或连接。
            async with async_session_maker() as session:
                await storage_endpoint_repository.guard_write(session, {
                    context.endpoint_id: context.endpoint.operation_generation or 0,
                })
            try:
                success, error = await asyncio.wait_for(
                    self.process_single_item(item, context), timeout=settings.STORAGE_ITEM_TIMEOUT)
            except asyncio.TimeoutError:
                success, error = False, "单项操作超时"
            if success:
                async with async_session_maker() as session:
                    # 补选主位置会更新其他端点的位置行，统一锁序避免两个清理任务交叉等待。
                    await storage_endpoint_repository.lock_all(session)
                    await storage_endpoint_repository.guard_write(session, {
                        context.endpoint_id: context.endpoint.operation_generation or 0,
                    })
                    location_id = item.get("location_id", item.get("id"))
                    if location_id is not None:
                        await image_location_repository.remove_locations(session, context.endpoint_id,
                            [location_id],
                            delete_empty_images=(self.TASK_TYPE == StorageTaskType.DELETE or context.delete_files))
                    else:
                        # 定向删文件任务没有位置行；与进度一起保存剩余文件，恢复时不重复计数。
                        context.object_keys = [key for key in context.object_keys if key != item["object_key"]]
                        await task_repository.update_payload_field(session, progress.task_id, "object_keys", context.object_keys)
                    progress.success_count += 1
                    changed = await task_repository.update_status(session, progress.task_id, "processing", result=progress.to_result_dict())
                    await session.commit()
                    if changed:
                        record_storage_progress(progress.task_id)
                consecutive_failures = 0
            else:
                progress.failed_count += 1
                consecutive_failures += 1
                if len(progress.failed_items) < self.BATCH_CONFIG.max_failed_items:
                    progress.failed_items.append({"location_id": item.get("location_id", item.get("id")), "error": error})
                await self._update_progress(progress)
                if consecutive_failures >= settings.STORAGE_MAX_CONSECUTIVE_FAILURES:
                    raise RuntimeError("连续操作失败，任务已停止；已完成结果保留，未完成项目可重试")
            if self.BATCH_CONFIG.rate_limit_seconds:
                await asyncio.sleep(self.BATCH_CONFIG.rate_limit_seconds)

    # ========== Progress Tracking ==========
    
    async def _update_progress(
        self,
        progress: TaskProgress,
        final: bool = False,
    ) -> None:
        """Update task progress in database."""
        async with async_session_maker() as session:
            status = progress.status.value if final else StorageTaskStatus.PROCESSING.value
            changed = await task_repository.update_status(
                session,
                progress.task_id,
                status,
                result=progress.to_result_dict(),
            )
            await session.commit()
            if changed:
                record_storage_progress(progress.task_id)
    
    async def get_progress(self, task_id: str) -> dict:
        """Get task progress.
        
        Returns:
            Progress dict with status, counts, etc.
        """
        async with async_session_maker() as session:
            task = await task_repository.get_by_id(session, task_id)
            
            if not task:
                return {"error": "Task not found"}
            
            payload = task.payload or {}
            result = task.result or {}
            
            total = payload.get("total_count", 0)
            success = result.get("success_count", 0)
            failed = result.get("failed_count", 0)
            
            return {
                "task_id": task_id,
                "task_type": task.type,
                "status": task.status,
                "total_count": total,
                "success_count": success,
                "failed_count": failed,
                "progress_percent": (
                    (success + failed) / max(total, 1) * 100
                ),
                "payload": payload,
                "result": result,
            }
