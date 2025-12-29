"""Storage endpoint model for multi-endpoint storage support.

Supports multiple S3-compatible endpoints (AWS S3, Cloudflare R2, MinIO, etc.)
with encryption for sensitive credentials.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from imgtag.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from imgtag.models.image_location import ImageLocation


class StorageEndpoint(Base, TimestampMixin):
    """Storage endpoint configuration for S3-compatible services.

    Supports multiple providers with encrypted credential storage.
    
    Attributes:
        id: Primary key.
        name: Unique endpoint name for identification.
        provider: Storage provider type (local/s3/r2/oss/cos/minio).
        endpoint_url: S3-compatible endpoint URL.
        region: AWS region or equivalent.
        bucket_name: Target bucket name (also used as URL path for local provider).
        access_key_id: Encrypted access key ID.
        secret_access_key: Encrypted secret access key.
        public_url_prefix: CDN or public access URL prefix.
        path_prefix: Object key prefix for organization.
        role: Endpoint role (primary/mirror/backup).
        is_enabled: Whether endpoint is active.
        is_default_upload: Whether this is the default upload target.
        auto_sync_enabled: Whether to auto-sync from another endpoint.
        sync_from_endpoint_id: Source endpoint for auto-sync.
        read_priority: Lower value = higher priority for reading.
        read_weight: Weight for load balancing.
        is_healthy: Current health status.
        last_health_check: Last health check timestamp.
        health_check_error: Last error message if unhealthy.
    """

    __tablename__ = "storage_endpoints"
    __table_args__ = {"comment": "存储端点配置表"}

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, comment="主键ID")

    # Basic info
    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="端点名称"
    )
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="提供商: local/s3/r2/oss/cos/minio"
    )

    # S3-compatible configuration (stored encrypted)
    endpoint_url: Mapped[Optional[str]] = mapped_column(Text, comment="端点URL")
    region: Mapped[Optional[str]] = mapped_column(
        String(50), server_default="auto", comment="区域"
    )
    bucket_name: Mapped[Optional[str]] = mapped_column(String(100), comment="存储桶名称")
    path_style: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False,
        comment="是否使用路径风格(true=path, false=virtual-hosted)"
    )
    
    # Encrypted credentials (use properties for access)
    _access_key_id: Mapped[Optional[str]] = mapped_column(
        "access_key_id", Text, comment="访问密钥ID(加密)"
    )
    _secret_access_key: Mapped[Optional[str]] = mapped_column(
        "secret_access_key", Text, comment="访问密钥(加密)"
    )

    # Public access configuration
    public_url_prefix: Mapped[Optional[str]] = mapped_column(
        Text, comment="CDN或公开访问前缀"
    )
    path_prefix: Mapped[str] = mapped_column(
        String(100), server_default="", nullable=False, comment="对象路径前缀"
    )

    # Role and status
    role: Mapped[str] = mapped_column(
        String(20), server_default="primary", nullable=False,
        comment="角色: primary/mirror/backup"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False, comment="是否启用"
    )
    is_default_upload: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False, comment="是否为默认上传端点"
    )

    # Auto-sync configuration
    auto_sync_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False, comment="是否自动同步"
    )
    sync_from_endpoint_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("storage_endpoints.id", ondelete="SET NULL"),
        comment="同步来源端点ID"
    )

    # Read strategy
    read_priority: Mapped[int] = mapped_column(
        Integer, server_default="100", nullable=False, comment="读取优先级(越小越优先)"
    )
    read_weight: Mapped[int] = mapped_column(
        Integer, server_default="1", nullable=False, comment="负载均衡权重"
    )

    # Health status
    is_healthy: Mapped[bool] = mapped_column(
        Boolean, server_default="true", nullable=False, comment="是否健康"
    )
    last_health_check: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="最后健康检查时间"
    )
    health_check_error: Mapped[Optional[str]] = mapped_column(
        Text, comment="健康检查错误信息"
    )

    # Relationships
    sync_from_endpoint: Mapped[Optional["StorageEndpoint"]] = relationship(
        "StorageEndpoint", remote_side=[id], foreign_keys=[sync_from_endpoint_id]
    )
    locations: Mapped[list["ImageLocation"]] = relationship(
        "ImageLocation", back_populates="endpoint"
    )

    # --- Encrypted property accessors ---

    @property
    def access_key_id(self) -> str | None:
        """Decrypt and return access key ID."""
        if not self._access_key_id:
            return None
        # Lazy import to avoid circular dependency
        from imgtag.core.crypto import decrypt
        return decrypt(self._access_key_id)

    @access_key_id.setter
    def access_key_id(self, value: str | None) -> None:
        """Encrypt and store access key ID."""
        if not value:
            self._access_key_id = None
            return
        from imgtag.core.crypto import encrypt
        self._access_key_id = encrypt(value)

    @property
    def secret_access_key(self) -> str | None:
        """Decrypt and return secret access key."""
        if not self._secret_access_key:
            return None
        from imgtag.core.crypto import decrypt
        return decrypt(self._secret_access_key)

    @secret_access_key.setter
    def secret_access_key(self, value: str | None) -> None:
        """Encrypt and store secret access key."""
        if not value:
            self._secret_access_key = None
            return
        from imgtag.core.crypto import encrypt
        self._secret_access_key = encrypt(value)

    @property
    def has_credentials(self) -> bool:
        """Check if credentials are configured (without exposing them)."""
        return bool(self._access_key_id and self._secret_access_key)

    def __repr__(self) -> str:
        return f"<StorageEndpoint(id={self.id}, name='{self.name}', provider='{self.provider}')>"
