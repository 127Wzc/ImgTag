"""Tag models for image categorization.

Supports hierarchical tags with levels (system, resolution, user-defined).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from imgtag.models.image import Image
    from imgtag.models.user import User


class Tag(Base, TimestampMixin):
    """Tag model with hierarchical support.

    Tag levels:
        - 0: Main category (风景, 人像, 动漫, etc.)
        - 1: Resolution tags (8K, 4K, 2K, etc.)
        - 2: AI/User generated tags

    Attributes:
        id: Primary key.
        name: Unique tag name.
        parent_id: Parent tag ID for hierarchy.
        source: Tag source ('system', 'ai', 'user').
        description: Optional tag description.
        level: Tag level (0=category, 1=resolution, 2=normal).
        usage_count: Number of images using this tag.
        sort_order: Display order.
    """

    __tablename__ = "tags"
    __table_args__ = {"comment": "标签表(支持层级)"}

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # Tag info
    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment="标签名"
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="SET NULL"), comment="父标签ID"
    )
    source: Mapped[str] = mapped_column(
        String(20), server_default="system", nullable=False, comment="来源: system/ai/user"
    )
    description: Mapped[Optional[str]] = mapped_column(Text, comment="描述")

    # Classification
    level: Mapped[int] = mapped_column(
        Integer, server_default="1", nullable=False, comment="层级: 0=主分类, 1=分辨率, 2=普通"
    )
    usage_count: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False, comment="使用次数"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False, comment="排序"
    )

    # Relationships
    parent: Mapped[Optional["Tag"]] = relationship(
        "Tag", remote_side=[id], backref="children"
    )
    images: Mapped[list["Image"]] = relationship(
        "Image", secondary="image_tags", back_populates="tags"
    )

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name='{self.name}', level={self.level})>"


class ImageTag(Base):
    """Association table between images and tags.

    Tracks the source of the tag assignment and ordering.

    Attributes:
        image_id: Image foreign key.
        tag_id: Tag foreign key.
        source: Who added the tag ('ai', 'user', 'system').
        added_by: User ID who added the tag (if user).
        sort_order: Display order for this image's tags.
        added_at: When the tag was added.
    """

    __tablename__ = "image_tags"
    __table_args__ = {"comment": "图片-标签关联表"}

    # Composite primary key
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    # Metadata
    source: Mapped[str] = mapped_column(
        String(20), server_default="ai", nullable=False, comment="来源: ai/user/system"
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), comment="添加用户ID"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, server_default="99", nullable=False, comment="排序"
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="添加时间",
    )

    def __repr__(self) -> str:
        return f"<ImageTag(image_id={self.image_id}, tag_id={self.tag_id})>"
