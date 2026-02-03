"""Add permissions field to users table.

为用户表添加权限位掩码字段，用于细粒度权限控制。

Revision ID: 0003_user_permissions
Revises: 0002_tag_usage_trigger
Create Date: 2026-01-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_user_permissions"
down_revision: Union[str, None] = "0002_tag_usage_trigger"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add permissions column with default value."""
    op.add_column(
        "users",
        sa.Column(
            "permissions",
            sa.BigInteger(),
            server_default="7",  # 默认 FULL 权限（UPLOAD_IMAGE | CREATE_TAGS | AI_ANALYZE）
            nullable=False,
            comment="权限位掩码(仅对user角色生效)",
        ),
    )


def downgrade() -> None:
    """Remove permissions column."""
    op.drop_column("users", "permissions")
