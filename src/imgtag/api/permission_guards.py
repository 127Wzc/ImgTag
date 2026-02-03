"""API 层权限检查辅助函数。

说明：
- core/permissions.py 仅提供纯函数与位掩码定义，不依赖 FastAPI
- 本文件集中封装 FastAPI 端点中重复的 403/缺失项提示逻辑
"""

from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.permissions import (
    Permission,
    check_permission,
    permission_denied_detail,
    permission_denied_with_missing_detail,
)
from imgtag.db.repositories import tag_repository


def ensure_permission(user: dict, permission: Permission) -> None:
    """确保用户拥有权限，否则抛出 403。"""
    if check_permission(user, permission):
        return
    raise HTTPException(status_code=403, detail=permission_denied_detail(permission))


async def ensure_create_tags_if_missing(
    session: AsyncSession,
    user: dict,
    tag_names: Sequence[str],
) -> None:
    """当 tag_names 中存在“需要新增的普通标签(level=2)”时，要求 CREATE_TAGS 权限。

    设计目标：
    - 允许无 CREATE_TAGS 权限的用户给图片绑定“已存在的普通标签(level=2)”
    - 禁止隐式创建新普通标签(level=2)
    - 禁止通过普通标签入口修改主分类(level=0)/分辨率(level=1)
    """
    if not tag_names:
        return

    normalized = [t.strip() for t in tag_names if t and str(t).strip()]
    if not normalized:
        return

    # name 全局唯一：若同名标签为 level 0/1，则不能作为普通标签(level=2)使用
    name_levels = await tag_repository.get_name_levels(session, normalized)
    reserved = [name for name, level in name_levels.items() if level in (0, 1)]
    if reserved:
        preview = ", ".join(reserved[:10])
        suffix = "..." if len(reserved) > 10 else ""
        raise HTTPException(
            status_code=409,
            detail=f"标签名已被主分类/分辨率占用，不能作为普通标签使用: {preview}{suffix}",
        )

    missing = [name for name in sorted(set(normalized)) if name not in name_levels]
    if not missing:
        return

    if check_permission(user, Permission.CREATE_TAGS):
        return

    raise HTTPException(
        status_code=403,
        detail=permission_denied_with_missing_detail(
            Permission.CREATE_TAGS,
            missing,
            item_label="标签",
        ),
    )
