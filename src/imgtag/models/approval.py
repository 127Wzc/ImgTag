"""Approval and audit log models.

Tracks approval workflows and user actions for auditing.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base


class Approval(Base):
    """Approval request model.

    Used for batch operations that require admin review.

    Attributes:
        id: Primary key.
        type: Request type ('batch_delete', 'batch_tag', etc.).
        status: Current status ('pending', 'approved', 'rejected').
        requester_id: User who made the request.
        target_type: Type of target ('image', 'tag', etc.).
        target_ids: Array of target IDs.
        payload: Additional request data.
        reviewer_id: Admin who reviewed the request.
        review_comment: Optional review comment.
        created_at: Request creation time.
        reviewed_at: Review completion time.
    """

    __tablename__ = "approvals"
    __table_args__ = {"comment": "审批请求表"}

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # Request info
    type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="请求类型: batch_delete/batch_tag/etc"
    )
    status: Mapped[str] = mapped_column(
        String(20), server_default="pending", nullable=False,
        comment="状态: pending/approved/rejected"
    )

    # Requester
    requester_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), comment="请求用户ID"
    )

    # Target
    target_type: Mapped[Optional[str]] = mapped_column(
        String(50), comment="目标类型: image/tag/etc"
    )
    target_ids: Mapped[Optional[list[int]]] = mapped_column(
        ARRAY(Integer), comment="目标ID列表"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="请求数据"
    )

    # Review
    reviewer_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), comment="审批用户ID"
    )
    review_comment: Mapped[Optional[str]] = mapped_column(Text, comment="审批备注")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="审批时间"
    )

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])

    def __repr__(self) -> str:
        return f"<Approval(id={self.id}, type='{self.type}', status='{self.status}')>"


class AuditLog(Base):
    """Audit log model for tracking user actions.

    Attributes:
        id: Primary key.
        user_id: User who performed the action.
        action: Action type ('create', 'update', 'delete', etc.).
        target_type: Type of affected resource.
        target_id: ID of affected resource.
        old_value: Previous state as JSON.
        new_value: New state as JSON.
        ip_address: Client IP address.
        created_at: Action timestamp.
    """

    __tablename__ = "audit_logs"
    __table_args__ = {"comment": "审计日志表"}

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # Actor
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), comment="操作用户ID"
    )

    # Action
    action: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="操作类型: create/update/delete/etc"
    )
    target_type: Mapped[Optional[str]] = mapped_column(
        String(50), comment="目标类型: image/tag/user/etc"
    )
    target_id: Mapped[Optional[int]] = mapped_column(Integer, comment="目标ID")

    # Change tracking
    old_value: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, comment="旧值")
    new_value: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, comment="新值")

    # Context
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), comment="IP地址")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="操作时间",
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action='{self.action}', target='{self.target_type}/{self.target_id}')>"
