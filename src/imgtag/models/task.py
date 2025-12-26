"""Task model for background job tracking.

Tracks async tasks like image analysis and batch operations.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from imgtag.models.base import Base, TimestampMixin


class Task(Base, TimestampMixin):
    """Background task model.

    Attributes:
        id: UUID string as primary key.
        type: Task type ('analyze', 'batch_delete', etc.).
        status: Current status ('pending', 'processing', 'completed', 'failed').
        payload: Task input data as JSON.
        result: Task result data as JSON.
        error: Error message if failed.
        completed_at: Task completion timestamp.
    """

    __tablename__ = "tasks"
    __table_args__ = {"comment": "任务队列表"}

    # Primary key (UUID string)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, comment="任务ID(UUID)")

    # Task info
    type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="任务类型: analyze/batch_delete/etc"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="状态: pending/processing/completed/failed"
    )

    # Data
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, comment="任务输入数据"
    )
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True, comment="任务结果数据"
    )
    error: Mapped[Optional[str]] = mapped_column(Text, comment="错误信息")

    # Completion
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="完成时间"
    )

    def __repr__(self) -> str:
        return f"<Task(id='{self.id}', type='{self.type}', status='{self.status}')>"
