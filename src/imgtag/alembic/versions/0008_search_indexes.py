"""补齐标签反向索引，移除没有检索消费者的历史 IVF 索引。

Revision ID: 0008_search_indexes
Revises: 0007_subject_workflow
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_search_indexes"
down_revision = "0007_subject_workflow"
branch_labels = None
depends_on = None


def upgrade():
    # 不在启动迁移里构建 HNSW；在线索引操作不能放在事务块中。
    schema = op.get_bind().execute(sa.text("""
        SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.oid = to_regclass('images')
    """)).scalar_one()
    quote = op.get_bind().dialect.identifier_preparer
    invalid = op.get_bind().execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM pg_index x JOIN pg_class c ON c.oid = x.indexrelid
            WHERE x.indrelid = to_regclass('image_tags') AND c.relname = 'ix_image_tags_tag_image'
              AND NOT x.indisvalid)
    """)).scalar_one()
    with op.get_context().autocommit_block():
        if invalid:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {quote.quote_schema(schema)}.ix_image_tags_tag_image")
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_image_tags_tag_image "
                   f"ON {quote.quote_schema(schema)}.image_tags (tag_id, image_id)")
        for name in ("ix_images_embedding", "idx_images_embedding"):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {quote.quote_schema(schema)}.{quote.quote(name)}")


def downgrade():
    # 不恢复在空表/无效向量上训练的 IVF。旧版精确搜索不依赖它。
    op.drop_index("ix_image_tags_tag_image", table_name="image_tags")
