"""Collection models for organizing images.

Supports hierarchical collections with cover images.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from imgtag.models.image import Image
    from imgtag.models.user import User


class Collection(Base, TimestampMixin):
    """Collection model for grouping images.

    Attributes:
        id: Primary key.
        name: Collection name.
        description: Optional description.
        cover_image_id: Image ID to use as cover.
        parent_id: Parent collection ID for nesting.
        user_id: Owner user ID.
        sort_order: Display order.
        is_public: Whether collection is public.
    """

    __tablename__ = "collections"
    __table_args__ = {"comment": "收藏夹表"}

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # Collection info
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="名称")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="描述")

    # References
    cover_image_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="SET NULL"), comment="封面图片ID"
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("collections.id", ondelete="SET NULL"), comment="父收藏夹ID"
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), comment="所属用户ID"
    )

    # Settings
    sort_order: Mapped[int] = mapped_column(
        Integer, server_default="0", nullable=False, comment="排序"
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False, comment="是否公开"
    )

    # Relationships
    cover_image: Mapped[Optional["Image"]] = relationship(
        "Image", foreign_keys=[cover_image_id]
    )
    parent: Mapped[Optional["Collection"]] = relationship(
        "Collection", remote_side=[id], backref="children"
    )
    owner: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    images: Mapped[list["Image"]] = relationship(
        "Image", secondary="image_collections", back_populates="collections"
    )

    def __repr__(self) -> str:
        return f"<Collection(id={self.id}, name='{self.name}')>"


class ImageCollection(Base):
    """Association table between images and collections.

    Attributes:
        image_id: Image foreign key.
        collection_id: Collection foreign key.
        added_at: When the image was added to the collection.
    """

    __tablename__ = "image_collections"
    __table_args__ = {"comment": "图片-收藏夹关联表"}

    # Composite primary key
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), primary_key=True
    )
    collection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )

    # Timestamp
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="添加时间",
    )

    def __repr__(self) -> str:
        return f"<ImageCollection(image_id={self.image_id}, collection_id={self.collection_id})>"
