"""Add trigger for tag usage count.

创建触发器自动维护 tags.usage_count 字段。

Revision ID: 0002_tag_usage_trigger
Revises: 0001_initial
Create Date: 2026-01-04
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0002_tag_usage_trigger'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create trigger to auto-update tag usage_count."""
    
    # 创建触发器函数
    op.execute("""
        CREATE OR REPLACE FUNCTION update_tag_usage_count()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE tags SET usage_count = usage_count + 1 WHERE id = NEW.tag_id;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE tags SET usage_count = GREATEST(usage_count - 1, 0) WHERE id = OLD.tag_id;
                RETURN OLD;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # 创建 INSERT 触发器
    op.execute("""
        CREATE TRIGGER trigger_image_tag_insert
        AFTER INSERT ON image_tags
        FOR EACH ROW
        EXECUTE FUNCTION update_tag_usage_count();
    """)
    
    # 创建 DELETE 触发器
    op.execute("""
        CREATE TRIGGER trigger_image_tag_delete
        AFTER DELETE ON image_tags
        FOR EACH ROW
        EXECUTE FUNCTION update_tag_usage_count();
    """)
    
    # 初始化现有数据的 usage_count
    op.execute("""
        UPDATE tags t
        SET usage_count = (
            SELECT COUNT(*) FROM image_tags it WHERE it.tag_id = t.id
        );
    """)


def downgrade() -> None:
    """Remove trigger and function."""
    op.execute("DROP TRIGGER IF EXISTS trigger_image_tag_insert ON image_tags;")
    op.execute("DROP TRIGGER IF EXISTS trigger_image_tag_delete ON image_tags;")
    op.execute("DROP FUNCTION IF EXISTS update_tag_usage_count();")
