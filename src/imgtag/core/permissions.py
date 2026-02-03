"""用户权限位掩码定义。

使用位掩码模型实现细粒度权限控制。
安全性说明：权限码本身是公开的，安全性由后端数据库验证保证。
"""

from enum import IntFlag
from typing import Sequence


class Permission(IntFlag):
    """用户权限枚举（位掩码）。

    使用 64 位整数，最多支持 64 种权限。
    Admin 角色绕过所有权限检查。

    Attributes:
        UPLOAD_IMAGE: 允许上传图片
        CREATE_TAGS: 允许新建标签
        AI_ANALYZE: 允许 AI 分析
    """

    # === 图片权限 ===
    UPLOAD_IMAGE = 1 << 0  # 上传图片

    # === 功能权限 ===
    CREATE_TAGS = 1 << 1  # 新建标签
    AI_ANALYZE = 1 << 2  # AI 分析

    # === 预设组合 ===
    NONE = 0  # 无权限
    FULL = (1 << 3) - 1  # 所有当前权限 (0x7 = 7)
    DEFAULT = FULL  # 默认权限（全开）


# 权限名称映射（用于友好的错误提示）
PERMISSION_NAMES = {
    Permission.UPLOAD_IMAGE: "上传图片",
    Permission.CREATE_TAGS: "新建标签",
    Permission.AI_ANALYZE: "AI 分析",
}


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


def get_permission_name(permission: Permission) -> str:
    """获取权限的友好名称。

    Args:
        permission: 权限枚举值。

    Returns:
        权限的中文名称，如果未找到则返回英文名称。
    """
    return PERMISSION_NAMES.get(permission, permission.name)


def permission_denied_detail(permission: Permission) -> str:
    """统一的无权限错误信息。"""
    perm_name = get_permission_name(permission)
    return f"暂无{perm_name}权限，请联系管理员开通"


def permission_denied_with_missing_detail(
    permission: Permission,
    missing_items: Sequence[str],
    *,
    item_label: str = "内容",
    limit: int = 10,
) -> str:
    """无权限 + 缺失项提示（用于“会隐式创建资源”的场景）。"""
    items = [s.strip() for s in missing_items if s and str(s).strip()]
    preview = ", ".join(items[:limit])
    suffix = "..." if len(items) > limit else ""
    return f"{permission_denied_detail(permission)}，无法创建新{item_label}: {preview}{suffix}"
