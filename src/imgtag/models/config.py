"""Configuration and schema metadata models.

Stores application configuration and database schema version.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from imgtag.models.base import Base


class Config(Base):
    """Application configuration key-value store.

    Attributes:
        key: Configuration key (primary key).
        value: Configuration value.
        description: Optional description.
        is_secret: Whether to mask value in API responses.
        updated_at: Last update timestamp.
    """

    __tablename__ = "config"
    __table_args__ = {"comment": "系统配置表"}

    # Primary key
    key: Mapped[str] = mapped_column(String(100), primary_key=True, comment="配置键")

    # Value
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="配置值")
    description: Mapped[str | None] = mapped_column(Text, comment="描述")

    # Settings
    is_secret: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False, comment="是否为敏感配置"
    )

    # Timestamp
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )

    def __repr__(self) -> str:
        return f"<Config(key='{self.key}')>"


class SchemaMeta(Base):
    """Database schema metadata.

    Tracks schema version for migration management.

    Attributes:
        key: Metadata key (primary key).
        value: Metadata value.
        updated_at: Last update timestamp.
    """

    __tablename__ = "schema_meta"
    __table_args__ = {"comment": "数据库元信息表"}

    # Primary key
    key: Mapped[str] = mapped_column(String(50), primary_key=True, comment="元信息键")

    # Value
    value: Mapped[str] = mapped_column(Text, nullable=False, comment="元信息值")

    # Timestamp
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )

    def __repr__(self) -> str:
        return f"<SchemaMeta(key='{self.key}', value='{self.value}')>"
