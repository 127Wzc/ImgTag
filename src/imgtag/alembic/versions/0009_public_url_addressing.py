"""区分 S3 公开服务地址与桶专属地址，保留旧版默认行为。

Revision ID: 0009_public_url_addressing
Revises: 0008_search_indexes
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_public_url_addressing"
down_revision = "0008_search_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "storage_endpoints",
        sa.Column(
            "public_url_include_bucket", sa.Boolean(), nullable=False,
            server_default=sa.true(),
            comment="公开URL前缀后是否追加桶名(true=服务地址, false=桶专属地址)",
        ),
    )


def downgrade():
    op.drop_column("storage_endpoints", "public_url_include_bucket")
