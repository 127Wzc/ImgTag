"""Task repository for background job tracking.

Provides async access to task records for job queue management.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.db.repositories.base import BaseRepository
from imgtag.models.task import Task

logger = get_logger(__name__)


class TaskRepository(BaseRepository[Task]):
    """Repository for Task model.

    Includes methods for:
    - Task creation and status updates
    - Task listing with filters
    - Cleanup of old tasks
    """

    model = Task

    async def create_task(
        self,
        session: AsyncSession,
        task_id: str,
        task_type: str,
        payload: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task record.

        Args:
            session: Database session.
            task_id: UUID string for the task.
            task_type: Type of task (analyze_image, batch_delete, etc.).
            payload: Task input data.

        Returns:
            Created Task instance.
        """
        task = Task(
            id=task_id,
            type=task_type,
            status="pending",
            payload=payload,
        )
        session.add(task)
        await session.flush()
        logger.info(f"创建任务 {task_id} (类型: {task_type})")
        return task

    async def update_status(
        self,
        session: AsyncSession,
        task_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        """Update task status.

        Args:
            session: Database session.
            task_id: Task ID to update.
            status: New status (pending/processing/completed/failed).
            result: Task result data (for completed status).
            error: Error message (for failed status).

        Returns:
            True if task was updated.
        """
        task = await self.get_by_id(session, task_id)
        if not task:
            logger.warning(f"任务不存在: {task_id}")
            return False

        task.status = status
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        if status in ("completed", "failed"):
            task.completed_at = datetime.now(timezone.utc)

        await session.flush()
        return True

    async def get_tasks(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Task], int]:
        """Get tasks with optional status filter.

        Args:
            session: Database session.
            status: Optional status filter.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            Tuple of (tasks, total_count).
        """
        from sqlalchemy import func

        # Build query
        stmt = select(Task).order_by(Task.created_at.desc())
        count_stmt = select(func.count()).select_from(Task)

        if status:
            stmt = stmt.where(Task.status == status)
            count_stmt = count_stmt.where(Task.status == status)

        # Get total count
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Get paginated results
        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        tasks = result.scalars().all()

        return tasks, total

    async def update_payload_field(
        self,
        session: AsyncSession,
        task_id: str,
        field: str,
        value: Any,
    ) -> bool:
        """Update a specific field in task payload.
        
        Args:
            session: Database session.
            task_id: Task ID to update.
            field: Payload field name.
            value: New value for the field.
            
        Returns:
            True if task was updated.
        """
        task = await self.get_by_id(session, task_id)
        if not task or not task.payload:
            return False
        task.payload[field] = value
        await session.flush()
        return True

    async def get_pending_and_processing(
        self,
        session: AsyncSession,
        limit: int = 1000,
    ) -> Sequence[Task]:
        """Get all pending and processing tasks.

        Used for task recovery on application startup.

        Args:
            session: Database session.
            limit: Maximum number of results.

        Returns:
            List of tasks.
        """
        stmt = (
            select(Task)
            .where(Task.status.in_(["pending", "processing"]))
            .order_by(Task.created_at)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def get_active_for_endpoint(
        self,
        session: AsyncSession,
        endpoint_id: int,
        task_types: list[str] | None = None,
    ) -> Optional[Task]:
        """Get active (pending/processing) task for an endpoint.
        
        Queries tasks where payload contains endpoint_id.
        
        Args:
            session: Database session.
            endpoint_id: Endpoint ID to check.
            task_types: Optional list of task types to filter.
            
        Returns:
            Active task if found, None otherwise.
        """
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy import cast
        
        stmt = (
            select(Task)
            .where(Task.status.in_(["pending", "processing"]))
            .where(Task.payload["endpoint_id"].as_integer() == endpoint_id)
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        
        if task_types:
            stmt = stmt.where(Task.type.in_(task_types))
        
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def cleanup_old_tasks(
        self,
        session: AsyncSession,
        days: int = 7,
    ) -> int:
        """Delete completed/failed tasks older than specified days.

        Args:
            session: Database session.
            days: Age threshold in days.

        Returns:
            Number of deleted tasks.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            delete(Task)
            .where(Task.status.in_(["completed", "failed"]))
            .where(Task.created_at < cutoff)
        )
        result = await session.execute(stmt)
        deleted = result.rowcount or 0
        logger.info(f"清理了 {deleted} 个旧任务（{days} 天前）")
        return deleted

    async def batch_delete(
        self,
        session: AsyncSession,
        task_ids: list[str],
    ) -> int:
        """Delete multiple tasks by IDs.

        Args:
            session: Database session.
            task_ids: List of task IDs to delete.

        Returns:
            Number of deleted tasks.
        """
        if not task_ids:
            return 0
        stmt = delete(Task).where(Task.id.in_(task_ids))
        result = await session.execute(stmt)
        return result.rowcount or 0

    async def claim_next_task(
        self,
        session: AsyncSession,
        task_types: list[str],
    ) -> Optional[Task]:
        """Atomically claim the next pending task using FOR UPDATE SKIP LOCKED.
        
        This ensures no two workers can claim the same task.
        
        Args:
            session: Database session.
            task_types: List of task types to process.
            
        Returns:
            Claimed task (already updated to 'processing'), or None.
        """
        # Use FOR UPDATE SKIP LOCKED to atomically claim a task
        stmt = (
            select(Task)
            .where(Task.status == "pending")
            .where(Task.type.in_(task_types))
            .order_by(Task.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        task = result.scalar_one_or_none()
        
        if task:
            task.status = "processing"
            await session.flush()
            image_id = task.payload.get("image_id") if task.payload else None
            logger.debug(f"抢占任务 {task.id} (image_id={image_id})")
        
        return task

    async def reset_stuck_tasks(
        self,
        session: AsyncSession,
        task_types: list[str],
        stuck_minutes: int = 10,
    ) -> int:
        """Reset stuck 'processing' tasks back to 'pending'.
        
        Called on service startup to recover tasks that were interrupted.
        
        Args:
            session: Database session.
            task_types: Task types to check.
            stuck_minutes: Minutes after which a processing task is considered stuck.
            
        Returns:
            Number of tasks reset.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)
        stmt = (
            update(Task)
            .where(Task.status == "processing")
            .where(Task.type.in_(task_types))
            .where(Task.updated_at < cutoff)
            .values(status="pending")
        )
        result = await session.execute(stmt)
        count = result.rowcount or 0
        if count > 0:
            logger.info(f"重置了 {count} 个 stuck 任务 (超过 {stuck_minutes} 分钟)")
        return count

    async def has_pending_for_image(
        self,
        session: AsyncSession,
        image_id: int,
        task_types: list[str],
    ) -> bool:
        """Check if there's already a pending/processing task for an image.
        
        Args:
            session: Database session.
            image_id: Image ID to check.
            task_types: Task types to check.
            
        Returns:
            True if a pending/processing task exists.
        """
        from sqlalchemy import func
        
        stmt = (
            select(func.count())
            .select_from(Task)
            .where(Task.status.in_(["pending", "processing"]))
            .where(Task.type.in_(task_types))
            .where(Task.payload["image_id"].as_integer() == image_id)
        )
        result = await session.execute(stmt)
        count = result.scalar() or 0
        return count > 0

    async def get_stats_by_type(
        self,
        session: AsyncSession,
        task_types: list[str],
    ) -> dict[str, int]:
        """Get task statistics by status for specific task types.
        
        Args:
            session: Database session.
            task_types: Task types to count.
            
        Returns:
            Dict with pending, processing, completed, failed counts.
        """
        from sqlalchemy import func, case
        
        stmt = (
            select(
                func.count(case((Task.status == "pending", 1))).label("pending"),
                func.count(case((Task.status == "processing", 1))).label("processing"),
                func.count(case((Task.status == "completed", 1))).label("completed"),
                func.count(case((Task.status == "failed", 1))).label("failed"),
            )
            .select_from(Task)
            .where(Task.type.in_(task_types))
        )
        result = await session.execute(stmt)
        row = result.one()
        return {
            "pending": row.pending or 0,
            "processing": row.processing or 0,
            "completed": row.completed or 0,
            "failed": row.failed or 0,
        }

    async def delete_by_status(
        self,
        session: AsyncSession,
        status: str,
        task_types: list[str],
    ) -> int:
        """Delete all tasks with a specific status.
        
        Args:
            session: Database session.
            status: Status to match (pending, completed, failed).
            task_types: Task types to delete.
            
        Returns:
            Number of deleted tasks.
        """
        stmt = (
            delete(Task)
            .where(Task.status == status)
            .where(Task.type.in_(task_types))
        )
        result = await session.execute(stmt)
        return result.rowcount or 0

    async def get_recent_completed(
        self,
        session: AsyncSession,
        task_types: list[str],
        limit: int = 10,
    ) -> Sequence[Task]:
        """Get recently completed tasks.
        
        Args:
            session: Database session.
            task_types: Task types to query.
            limit: Maximum number of results.
            
        Returns:
            List of recent completed/failed tasks.
        """
        stmt = (
            select(Task)
            .where(Task.status.in_(["completed", "failed"]))
            .where(Task.type.in_(task_types))
            .order_by(Task.completed_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return result.scalars().all()


# Global repository instance
task_repository = TaskRepository()

