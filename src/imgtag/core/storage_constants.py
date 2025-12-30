"""Storage constants.

Centralized constants for storage providers, MIME types, and related configurations.
"""

from enum import Enum


class StorageProvider(str, Enum):
    """Storage provider types."""
    LOCAL = "local"
    S3 = "s3"


class EndpointRole(str, Enum):
    """存储端点角色。
    
    Attributes:
        PRIMARY: 主端点，可直接上传图片
        BACKUP: 备份端点，不可直接上传，自动从主端点同步
    """
    PRIMARY = "primary"
    BACKUP = "backup"
    
    @classmethod
    def is_uploadable(cls, role: str) -> bool:
        """检查端点角色是否允许直接上传"""
        return role == cls.PRIMARY.value


class StorageTaskType(str, Enum):
    """Storage task types for background operations."""
    SYNC = "storage_sync"
    DELETE = "storage_delete"
    UNLINK = "storage_unlink"  # 解绑端点并清理
    
    @classmethod
    def all_values(cls) -> list[str]:
        """Get all task type values as list (for DB queries)."""
        return [t.value for t in cls]
    
    @classmethod
    def display_name(cls, task_type: str) -> str:
        """Get display name for a task type."""
        names = {
            cls.SYNC.value: "同步",
            cls.DELETE.value: "删除",
            cls.UNLINK.value: "解除关联",
        }
        return names.get(task_type, task_type)


class StorageTaskStatus(str, Enum):
    """Storage task status values."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============= Batch Processing Configuration =============

from dataclasses import dataclass


@dataclass(frozen=True)
class BatchConfig:
    """Configuration for batch processing operations.
    
    Optimized for 2C2G (2 CPU, 2GB RAM) servers.
    
    Attributes:
        batch_size: Maximum items per batch/task.
        checkpoint_interval: Update progress every N items.
        max_concurrent: Maximum concurrent operations.
        rate_limit_seconds: Delay between operations (0 = no limit).
        max_failed_items: Maximum failed items to store in result.
    """
    batch_size: int = 500
    checkpoint_interval: int = 50
    max_concurrent: int = 3
    rate_limit_seconds: float = 0.1  # 轻微限速避免资源抢占
    max_failed_items: int = 50


# 统一配置实例
BATCH_CONFIG = BatchConfig()


# Default priority for unknown endpoints
DEFAULT_PRIORITY = 999

# File extension to MIME type mapping
EXTENSION_TO_MIME: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "svg": "image/svg+xml",
    "ico": "image/x-icon",
    "tiff": "image/tiff",
    "tif": "image/tiff",
}

# Supported image extensions for upload
SUPPORTED_IMAGE_EXTENSIONS: set[str] = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"
}

# Default MIME type when extension is unknown
DEFAULT_MIME_TYPE = "image/jpeg"


def get_mime_type(extension: str) -> str:
    """Get MIME type for a file extension.
    
    Args:
        extension: File extension without leading dot.
        
    Returns:
        MIME type string.
    """
    ext = extension.lower().lstrip(".")
    return EXTENSION_TO_MIME.get(ext, DEFAULT_MIME_TYPE)
