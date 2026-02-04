"""Custom exceptions for ImgTag API.

Provides structured error handling with error codes and messages.
"""

from typing import Any, Optional


class APIError(Exception):
    """Base API exception with structured error info.
    
    Attributes:
        code: Error code string (e.g., "TAG_NOT_FOUND")
        message: Human-readable error message
        status_code: HTTP status code
        details: Optional additional error details
    """
    
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: Optional[dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to response dict."""
        return {
            "success": False,
            "error": {
                "code": self.code,
                "message": self.message,
                **self.details,
            }
        }


# ============= 400 Bad Request =============

class ValidationError(APIError):
    """Validation/parameter error."""
    def __init__(self, message: str = "参数验证失败", **details):
        super().__init__("VALIDATION_ERROR", message, 400, details)


class EmptyValueError(APIError):
    """Required field is empty."""
    def __init__(self, field: str = "字段"):
        super().__init__("EMPTY_VALUE", f"{field}不能为空", 400)


# ============= 401 Unauthorized =============

class UnauthorizedError(APIError):
    """Not logged in or token invalid."""
    def __init__(self, message: str = "请先登录"):
        super().__init__("UNAUTHORIZED", message, 401)


class TokenExpiredError(APIError):
    """Token has expired."""
    def __init__(self):
        super().__init__("TOKEN_EXPIRED", "登录已过期，请重新登录", 401)


# ============= 403 Forbidden =============

class ForbiddenError(APIError):
    """No permission to access resource."""
    def __init__(self, message: str = "权限不足"):
        super().__init__("FORBIDDEN", message, 403)


class AdminRequiredError(APIError):
    """Admin role required."""
    def __init__(self):
        super().__init__("ADMIN_REQUIRED", "仅管理员可执行此操作", 403)


class OwnerRequiredError(APIError):
    """Resource ownership required."""
    def __init__(self):
        super().__init__("OWNER_REQUIRED", "只能操作自己的资源", 403)


# ============= 404 Not Found =============

class NotFoundError(APIError):
    """Resource not found."""
    def __init__(self, resource: str = "资源"):
        super().__init__("NOT_FOUND", f"{resource}不存在", 404)


class TagNotFoundError(APIError):
    """Tag not found."""
    def __init__(self, name: str = ""):
        msg = f"标签 '{name}' 不存在" if name else "标签不存在"
        super().__init__("TAG_NOT_FOUND", msg, 404)


class ImageNotFoundError(APIError):
    """Image not found."""
    def __init__(self, image_id: Optional[int] = None):
        msg = f"图片 #{image_id} 不存在" if image_id else "图片不存在"
        super().__init__("IMAGE_NOT_FOUND", msg, 404)


# ============= 409 Conflict =============

class ConflictError(APIError):
    """Resource conflict (e.g., duplicate)."""
    def __init__(self, message: str = "资源冲突"):
        super().__init__("CONFLICT", message, 409)


class DuplicateError(APIError):
    """Duplicate resource."""
    def __init__(self, resource: str = "资源"):
        super().__init__("DUPLICATE", f"{resource}已存在", 409)


class TagExistsError(APIError):
    """Tag with same name already exists."""
    def __init__(self, name: str):
        super().__init__("TAG_EXISTS", f"标签 '{name}' 已存在", 409)


# ============= 500 Internal Error =============

class InternalError(APIError):
    """Internal server error."""
    def __init__(self, message: str = "服务器内部错误"):
        super().__init__("INTERNAL_ERROR", message, 500)


# ============= 503 Service Unavailable =============

class TransientAPIError(APIError):
    """Transient error that is typically safe to retry."""

    def __init__(self, code: str, message: str = "服务暂不可用，请稍后重试", **details):
        super().__init__(code, message, 503, details)


class DBSchemaChangedError(TransientAPIError):
    """Database schema/config changed during runtime; retry may succeed after pool refresh."""

    def __init__(self):
        super().__init__(
            "DB_SCHEMA_CHANGED",
            "数据库结构/配置刚发生变更，请重试；若仍失败请重启后端服务。",
        )


class DBTimeoutError(TransientAPIError):
    """Database operation timed out."""

    def __init__(self):
        super().__init__(
            "DB_TIMEOUT",
            "数据库连接/查询超时，请检查数据库服务是否可用后重试。",
        )
