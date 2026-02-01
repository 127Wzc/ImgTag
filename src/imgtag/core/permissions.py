"""用户权限位掩码定义。

使用位掩码模型实现细粒度权限控制。
安全性说明：权限码本身是公开的，安全性由后端数据库验证保证。
"""

from enum import IntFlag


class Permission(IntFlag):
    """用户权限枚举（位掩码）。

    使用 64 位整数，最多支持 64 种权限。
    Admin 角色绕过所有权限检查。

    Attributes:
        UPLOAD_IMAGE: 允许上传图片
        CREATE_TAGS: 允许新建标签（预留）
        AI_ANALYZE: 允许 AI 分析（预留）
        AI_SEARCH: 允许智能搜索（预留）
    """

    # === 图片权限 ===
    UPLOAD_IMAGE = 1 << 0  # 上传图片

    # === 预留权限 ===
    CREATE_TAGS = 1 << 1  # 新建标签
    AI_ANALYZE = 1 << 2  # AI 分析
    AI_SEARCH = 1 << 3  # 智能搜索

    # === 预设组合 ===
    NONE = 0  # 无权限
    DEFAULT = UPLOAD_IMAGE  # 默认权限（仅上传）
    FULL = (1 << 4) - 1  # 所有当前权限 (0xF = 15)


def has_permission(user_permissions: int, required: Permission) -> bool:
    """检查用户是否拥有指定权限。

    Args:
        user_permissions: 用户的权限位掩码。
        required: 需要检查的权限。

    Returns:
        如果用户拥有指定权限返回 True，否则返回 False。
    """
    return (user_permissions & required) == required


def check_permission(user: dict, required: Permission) -> bool:
    """检查用户字典是否拥有指定权限。

    Admin 角色自动拥有所有权限。

    Args:
        user: 用户字典（包含 role 和 permissions）。
        required: 需要检查的权限。

    Returns:
        如果用户拥有指定权限返回 True，否则返回 False。
    """
    # Admin 拥有所有权限
    if user.get("role") == "admin":
        return True
    return has_permission(user.get("permissions", 0), required)

