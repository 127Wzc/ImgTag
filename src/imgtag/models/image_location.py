"""Image location model for multi-endpoint storage tracking.

Tracks where each image is stored across multiple endpoints.
Supports sync status tracking and primary location designation.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base

if TYPE_CHECKING:
    from imgtag.models.image import Image
    from imgtag.models.storage_endpoint import StorageEndpoint


class ImageLocation(Base):
    """Image storage location across endpoints.

    Tracks where each image is stored, enabling multi-endpoint
    redundancy and load balancing.

    Attributes:
        id: Primary key.
        image_id: Foreign key to images table.
        endpoint_id: Foreign key to storage_endpoints table.
        object_key: Storage path/key (e.g., ab/cd/hash.jpg).
        is_primary: Whether this is the primary storage location.
        sync_status: Current sync status (synced/pending/failed).
        sync_error: Error message if sync failed.
        created_at: When this location was created.
        synced_at: When sync completed successfully.
        category_code: Category code at upload time (for building full path).
    """

    __tablename__ = "image_locations"
    __table_args__ = (
        UniqueConstraint("image_id", "endpoint_id", name="uq_image_location"),
        Index("ix_image_locations_image_id", "image_id"),
        Index("ix_image_locations_endpoint_id", "endpoint_id"),
        Index("ix_image_locations_sync_status", "sync_status"),
        {"comment": "图片存储位置表"},
    )

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # Foreign keys
    image_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("images.id", ondelete="CASCADE"),
        nullable=False,
        comment="图片ID",
    )
    endpoint_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("storage_endpoints.id", ondelete="RESTRICT"),
        nullable=False,
        comment="存储端点ID",
    )

    # Storage path (unified across all endpoints)
    object_key: Mapped[str] = mapped_column(
        Text, nullable=False, comment="对象键(如 images/ab/cd/hash.jpg)"
    )

    # Status
    is_primary: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False, comment="是否为主存储位置"
    )
    sync_status: Mapped[str] = mapped_column(
        String(20), server_default="synced", nullable=False,
        comment="同步状态: synced/pending/failed"
    )
    sync_error: Mapped[str | None] = mapped_column(Text, comment="同步错误信息")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="同步完成时间"
    )

    # Category directory (stored at upload time, immutable after)
    category_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="上传时的分类代码(用于构建完整存储路径)"
    )

    # Relationships
    image: Mapped["Image"] = relationship("Image", back_populates="locations")
    endpoint: Mapped["StorageEndpoint"] = relationship(
        "StorageEndpoint", back_populates="locations"
    )

    def __repr__(self) -> str:
        return (
            f"<ImageLocation(id={self.id}, image_id={self.image_id}, "
            f"endpoint_id={self.endpoint_id}, status='{self.sync_status}')>"
        )
