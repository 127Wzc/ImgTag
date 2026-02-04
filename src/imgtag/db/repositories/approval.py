"""Approval repository for approval workflow management.

Provides async access to approval and audit log records.
"""

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from imgtag.core.logging_config import get_logger
from imgtag.db.repositories.base import BaseRepository
from imgtag.models.approval import Approval, AuditLog

logger = get_logger(__name__)


class ApprovalRepository(BaseRepository[Approval]):
    """Repository for Approval model.

    Includes methods for:
    - Approval listing and filtering
    - Approval status updates
    - Audit log creation
    """

    model = Approval

    async def get_pending(
        self,
        session: AsyncSession,
        *,
        types: Sequence[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Approval], int]:
        """Get pending approval requests.

        Args:
            session: Database session.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            Tuple of (approvals, total_count).
        """
        from sqlalchemy import func

        # Count query
        count_stmt = (
            select(func.count())
            .select_from(Approval)
            .where(Approval.status == "pending")
        )
        if types:
            count_stmt = count_stmt.where(Approval.type.in_(list(types)))
        count_result = await session.execute(count_stmt)
        total = count_result.scalar() or 0

        # Data query with eager loading
        stmt = (
            select(Approval)
            .where(Approval.status == "pending")
            .options(selectinload(Approval.requester))
            .order_by(Approval.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if types:
            stmt = stmt.where(Approval.type.in_(list(types)))
        result = await session.execute(stmt)
        approvals = result.scalars().all()

        return approvals, total

    async def get_with_relations(
        self,
        session: AsyncSession,
        approval_id: int,
    ) -> Optional[Approval]:
        """Get approval with eager-loaded relationships.

        Args:
            session: Database session.
            approval_id: Approval ID.

        Returns:
            Approval with requester and reviewer loaded.
        """
        stmt = (
            select(Approval)
            .where(Approval.id == approval_id)
            .options(
                selectinload(Approval.requester),
                selectinload(Approval.reviewer),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def approve(
        self,
        session: AsyncSession,
        approval: Approval,
        reviewer_id: int,
        comment: str | None = None,
    ) -> Approval:
        """Approve a request.

        Args:
            session: Database session.
            approval: Approval instance.
            reviewer_id: Admin user ID.
            comment: Optional review comment.

        Returns:
            Updated Approval instance.
        """
        approval.status = "approved"
        approval.reviewer_id = reviewer_id
        approval.review_comment = comment
        approval.reviewed_at = datetime.now(timezone.utc)
        await session.flush()
        logger.info(f"审批已通过: {approval.id}")
        return approval

    async def reject(
        self,
        session: AsyncSession,
        approval: Approval,
        reviewer_id: int,
        comment: str | None = None,
    ) -> Approval:
        """Reject a request.

        Args:
            session: Database session.
            approval: Approval instance.
            reviewer_id: Admin user ID.
            comment: Optional review comment.

        Returns:
            Updated Approval instance.
        """
        approval.status = "rejected"
        approval.reviewer_id = reviewer_id
        approval.review_comment = comment
        approval.reviewed_at = datetime.now(timezone.utc)
        await session.flush()
        logger.info(f"审批已拒绝: {approval.id}")
        return approval


class AuditLogRepository(BaseRepository[AuditLog]):
    """Repository for AuditLog model."""

    model = AuditLog

    async def add_log(
        self,
        session: AsyncSession,
        user_id: int | None,
        action: str,
        *,
        target_type: str | None = None,
        target_id: int | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        """Create an audit log entry.

        Args:
            session: Database session.
            user_id: User who performed the action.
            action: Action type.
            target_type: Type of affected resource.
            target_id: ID of affected resource.
            old_value: Previous state.
            new_value: New state.
            ip_address: Client IP address.

        Returns:
            Created AuditLog instance.
        """
        log = AuditLog(
            user_id=user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
        )
        session.add(log)
        await session.flush()
        return log


# Global repository instances
approval_repository = ApprovalRepository()
audit_log_repository = AuditLogRepository()
