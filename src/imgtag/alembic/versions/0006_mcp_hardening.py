"""add MCP write idempotency key

Revision ID: 0006_mcp_hardening
Revises: 0005_subject_memory
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_mcp_hardening"
down_revision: Union[str, None] = "0005_subject_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "images",
        sa.Column(
            "mcp_idempotency_key",
            sa.String(length=128),
            nullable=True,
            comment="MCP 写入幂等键",
        ),
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_images_mcp_idempotency
        ON images (uploaded_by, mcp_idempotency_key)
        WHERE mcp_idempotency_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("uq_images_mcp_idempotency", table_name="images")
    op.drop_column("images", "mcp_idempotency_key")
