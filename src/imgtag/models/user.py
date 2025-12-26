"""User model for authentication and authorization.

Stores user credentials, roles, and API keys.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base

if TYPE_CHECKING:
    from imgtag.models.image import Image


class User(Base):
    """User account model.

    Attributes:
        id: Primary key.
        username: Unique username for login.
        email: Optional unique email address.
        password_hash: Hashed password (salt$hash format).
        role: User role ('admin' or 'user').
        is_active: Whether the account is active.
        api_key: Optional API key for external access.
        created_at: Account creation timestamp.
        last_login_at: Last successful login timestamp.
    """

    __tablename__ = "users"
    __table_args__ = {"comment": "用户表"}

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # Authentication
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="用户名"
    )
    email: Mapped[Optional[str]] = mapped_column(
        String(100), unique=True, nullable=True, comment="邮箱"
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="密码哈希(salt$hash)"
    )

    # Authorization
    role: Mapped[str] = mapped_column(
        String(20), server_default="user", nullable=False, comment="角色: admin/user"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False, comment="是否激活"
    )

    # API access
    api_key: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, comment="API密钥"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后登录时间"
    )

    # Relationships
    images: Mapped[list["Image"]] = relationship(
        "Image", back_populates="uploader", foreign_keys="Image.uploaded_by"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"
