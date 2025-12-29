"""Storage constants.

Centralized constants for storage providers, MIME types, and related configurations.
"""

from enum import Enum


class StorageProvider(str, Enum):
    """Storage provider types."""
    LOCAL = "local"
    S3 = "s3"


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
