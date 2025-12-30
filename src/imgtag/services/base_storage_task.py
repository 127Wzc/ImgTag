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

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import (
    BATCH_CONFIG,
    BatchConfig,
    StorageTaskStatus,
    StorageTaskType,
)
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import task_repository

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
    
    def __init__(self):
        self._semaphore = asyncio.Semaphore(self.BATCH_CONFIG.max_concurrent)
    
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
    
    @abstractmethod
    async def on_task_complete(
        self, 
        progress: TaskProgress, 
        context: T,
    ) -> None:
        """Called when task completes (success or failure).
        
        Use this for cleanup, final database updates, etc.
        
        Args:
            progress: Final progress state.
            context: Task-specific context object.
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
        task_id = str(uuid.uuid4())
        
        # Add common fields to payload
        payload["initiated_by"] = initiated_by
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        
        async with async_session_maker() as session:
            await task_repository.create_task(
                session,
                task_id=task_id,
                task_type=self.TASK_TYPE.value,
                payload=payload,
            )
            await session.commit()
        
        # Start background processing
        asyncio.create_task(self._run_task(task_id))
        
        logger.info(f"Created {self.TASK_TYPE.value} task: {task_id}")
        return task_id
    
    # ========== Task Execution ==========
    
    async def _run_task(self, task_id: str) -> None:
        """Run task with error handling."""
        progress = TaskProgress(
            task_id=task_id,
            task_type=self.TASK_TYPE,
            status=StorageTaskStatus.PROCESSING,
        )
        context: T | None = None
        
        try:
            # Load task and build context
            async with async_session_maker() as session:
                task = await task_repository.get_by_id(session, task_id)
                if not task:
                    logger.error(f"Task {task_id} not found")
                    return
                
                await task_repository.update_status(
                    session, task_id, StorageTaskStatus.PROCESSING.value
                )
                await session.commit()
            
            payload = task.payload or {}
            context = await self.build_context(task_id, payload)
            
            # Get items and set total
            items = await self.get_items_to_process(context)
            progress.total_count = len(items)
            
            # Process items in batches
            await self._process_items(items, progress, context)
            
            # Mark complete
            progress.status = StorageTaskStatus.COMPLETED
            
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            progress.status = StorageTaskStatus.FAILED
            progress.failed_items.append({"error": str(e)})
        
        finally:
            # Update final status
            await self._update_progress(progress, final=True)
            
            # Call completion hook
            if context is not None:
                try:
                    await self.on_task_complete(progress, context)
                except Exception as e:
                    logger.error(f"on_task_complete failed: {e}")
            
            logger.info(
                f"Task {task_id} {progress.status.value}: "
                f"{progress.success_count} success, {progress.failed_count} failed"
            )
    
    async def _process_items(
        self,
        items: list[Any],
        progress: TaskProgress,
        context: T,
    ) -> None:
        """Process items with batch concurrency and checkpoints."""
        config = self.BATCH_CONFIG
        
        async def process_with_semaphore(item: Any) -> tuple[bool, str | None]:
            """Process single item with semaphore control."""
            async with self._semaphore:
                if config.rate_limit_seconds > 0:
                    await asyncio.sleep(config.rate_limit_seconds)
                return await self.process_single_item(item, context)
        
        # 按 checkpoint_interval 分批处理
        for batch_start in range(0, len(items), config.checkpoint_interval):
            batch = items[batch_start:batch_start + config.checkpoint_interval]
            
            # 并发执行当前批次
            results = await asyncio.gather(
                *[process_with_semaphore(item) for item in batch],
                return_exceptions=True
            )
            
            # 统计结果
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    progress.failed_count += 1
                    if len(progress.failed_items) < 50:
                        progress.failed_items.append({
                            "item": str(batch[i]),
                            "error": str(result),
                        })
                    logger.error(f"Failed to process item: {result}")
                else:
                    success, error = result
                    if success:
                        progress.success_count += 1
                    else:
                        progress.failed_count += 1
                        if len(progress.failed_items) < 50:
                            progress.failed_items.append({
                                "item": str(batch[i]),
                                "error": error or "Unknown error",
                            })
            
            # Checkpoint update
            await self._update_progress(progress)
            logger.debug(
                f"Task {progress.task_id} checkpoint: "
                f"{progress.processed_count}/{progress.total_count}"
            )
    
    # ========== Progress Tracking ==========
    
    async def _update_progress(
        self,
        progress: TaskProgress,
        final: bool = False,
    ) -> None:
        """Update task progress in database."""
        async with async_session_maker() as session:
            status = progress.status.value if final else StorageTaskStatus.PROCESSING.value
            await task_repository.update_status(
                session,
                progress.task_id,
                status,
                result=progress.to_result_dict(),
            )
            await session.commit()
    
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
