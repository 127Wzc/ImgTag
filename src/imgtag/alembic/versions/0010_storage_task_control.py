"""存储任务取消、租约与端点清理回写保护。

Revision ID: 0010_storage_task_control
Revises: 0009_public_url_addressing
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_storage_task_control"
down_revision = "0009_public_url_addressing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("storage_endpoints", sa.Column("operation_generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tasks", sa.Column("run_token", sa.String(36), nullable=True))
    op.add_column("tasks", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("tasks", "heartbeat_at")
    op.drop_column("tasks", "run_token")
    op.drop_column("storage_endpoints", "operation_generation")
