"""Image model for storing uploaded images and their metadata.

Supports multi-endpoint storage via ImageLocation relationship.
Vector embeddings for similarity search.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from imgtag.models.collection import Collection
    from imgtag.models.image_location import ImageLocation
    from imgtag.models.tag import Tag
    from imgtag.models.user import User


class Image(Base, TimestampMixin):
    """Image model with metadata and vector embedding.

    Attributes:
        id: Primary key.
        file_hash: MD5 hash for deduplication.
        file_type: File extension (jpg, png, etc.).
        file_size: Size in megabytes.
        width: Image width in pixels.
        height: Image height in pixels.
        original_url: Original source URL if imported.
        description: AI-generated or user description.
        embedding: Vector embedding for similarity search.
        uploaded_by: User ID who uploaded the image.
        is_public: Whether image is publicly visible.
        locations: Storage locations across endpoints (via ImageLocation).
    """

    __tablename__ = "images"
    __table_args__ = {"comment": "图片信息表"}

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # File info
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), comment="文件MD5哈希")
    file_type: Mapped[Optional[str]] = mapped_column(String(20), comment="文件类型")
    file_size: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), comment="文件大小(MB)"
    )

    # Dimensions
    width: Mapped[Optional[int]] = mapped_column(Integer, comment="宽度(px)")
    height: Mapped[Optional[int]] = mapped_column(Integer, comment="高度(px)")

    # Original source
    original_url: Mapped[Optional[str]] = mapped_column(Text, comment="原始URL")

    # Content
    description: Mapped[Optional[str]] = mapped_column(Text, comment="图片描述")
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(None), comment="向量嵌入"
    )

    # Relations
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), comment="上传用户ID"
    )

    # Privacy control
    is_public: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False, comment="是否公开可见"
    )

    # Relationships
    uploader: Mapped[Optional["User"]] = relationship(
        "User", back_populates="images", foreign_keys=[uploaded_by]
    )
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", secondary="image_tags", back_populates="images"
    )
    collections: Mapped[list["Collection"]] = relationship(
        "Collection", secondary="image_collections", back_populates="images"
    )
    locations: Mapped[list["ImageLocation"]] = relationship(
        "ImageLocation", back_populates="image", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Image(id={self.id}, file_type='{self.file_type}')>"

