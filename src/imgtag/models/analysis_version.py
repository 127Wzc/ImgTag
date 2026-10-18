"""图片分析历史快照。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from imgtag.models.base import Base


class ImageAnalysisVersion(Base):
    __tablename__ = "image_analysis_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    state: Mapped[str] = mapped_column(String(20), server_default="history")
    pending: Mapped[bool] = mapped_column(Boolean, server_default="false", index=True)
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    description: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB)
    subject_analysis: Mapped[dict | None] = mapped_column(JSONB)
    base_snapshot: Mapped[dict] = mapped_column(JSONB)
    metadata_snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
