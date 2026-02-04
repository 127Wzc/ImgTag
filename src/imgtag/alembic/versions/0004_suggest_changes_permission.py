"""Add SUGGEST_CHANGES permission bit and update default.

为 users.permissions 增加新的权限位：
- SUGGEST_CHANGES = 1 << 3 (8)

同时将默认权限从 7 更新为 15，并对存量普通用户做权限补齐（按位或）。

Revision ID: 0004_suggest_changes_permission
Revises: 0003_user_permissions
Create Date: 2026-02-04
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0004_suggest_changes_permission"
down_revision: Union[str, None] = "0003_user_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Update default permissions and backfill existing users."""
    # 新注册/新建用户默认权限：7 -> 15
    op.alter_column(
        "users",
        "permissions",
        server_default="15",
    )

    # 存量普通用户补齐建议权限位（admin 角色不依赖 permissions）
    op.execute(
        "UPDATE users SET permissions = permissions | 8 WHERE role != 'admin'"
    )


def downgrade() -> None:
    """Revert default permissions and remove SUGGEST_CHANGES bit."""
    # 清理建议权限位（仅对普通用户）
    op.execute(
        "UPDATE users SET permissions = permissions & ~8 WHERE role != 'admin'"
    )

    # 恢复默认值：15 -> 7
    op.alter_column(
        "users",
        "permissions",
        server_default="7",
    )

