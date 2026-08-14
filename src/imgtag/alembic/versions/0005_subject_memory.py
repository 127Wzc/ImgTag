"""add subject memory tables

Revision ID: 0005_subject_memory
Revises: 0004_suggest_changes_permission
Create Date: 2026-02-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "0005_subject_memory"
down_revision: Union[str, None] = "0004_suggest_changes_permission"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("name", sa.String(length=120), nullable=False, comment="主体名称"),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="别名列表"),
        sa.Column("alias_tag_ids", postgresql.ARRAY(sa.Integer()), nullable=True, comment="主体别名标签ID列表(level=2)"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False, comment="是否启用"),
        sa.Column(
            "category_tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="RESTRICT"),
            nullable=False,
            comment="归属一级分类标签ID(level=0)",
        ),
        sa.Column(
            "primary_tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="RESTRICT"),
            nullable=False,
            comment="主体主名称标签ID(level=2)",
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="创建人ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="更新时间",
        ),
        sa.UniqueConstraint("name", name="uq_subjects_name"),
        sa.UniqueConstraint("primary_tag_id", name="uq_subjects_primary_tag"),
        comment="主体词典表",
    )
    op.create_index("ix_subjects_active", "subjects", ["is_active"])
    op.create_index("ix_subjects_category_tag", "subjects", ["category_tag_id"])

    op.create_table(
        "subject_samples",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column(
            "subject_id",
            sa.Integer(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
            comment="主体ID",
        ),
        sa.Column(
            "image_id",
            sa.Integer(),
            sa.ForeignKey("images.id", ondelete="SET NULL"),
            nullable=True,
            comment="来源图片ID",
        ),
        sa.Column(
            "embedding_model",
            sa.String(length=80),
            server_default="reference",
            nullable=False,
            comment="向量模型标识；V1 仅登记来源引用(reference)，真实向量由识别器接入后回填",
        ),
        # 维度不锁定：待真实识别器确定向量空间后再通过迁移固定维度并创建向量索引
        sa.Column("embedding", Vector(), nullable=True, comment="主体样本向量（V1 不写入）"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="样本附加信息"),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="创建人ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间",
        ),
        comment="主体样本向量表",
    )
    op.create_index("ix_subject_samples_subject_id", "subject_samples", ["subject_id"])
    op.create_index(
        "ix_subject_samples_model",
        "subject_samples",
        ["embedding_model"],
    )

    op.create_table(
        "image_subjects",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column(
            "image_id",
            sa.Integer(),
            sa.ForeignKey("images.id", ondelete="CASCADE"),
            nullable=False,
            comment="图片ID",
        ),
        sa.Column(
            "subject_id",
            sa.Integer(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
            comment="主体ID",
        ),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True, comment="置信度(0-1)"),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="manual",
            nullable=False,
            comment="来源: manual/auto/approval",
        ),
        sa.Column(
            "state",
            sa.String(length=20),
            server_default="confirmed",
            nullable=False,
            comment="状态: 当前仅 confirmed（pending/rejected 预留给后续版本）",
        ),
        sa.Column("is_primary", sa.Boolean(), server_default="true", nullable=False, comment="是否主主体"),
        sa.Column(
            "synced_primary_tag_id",
            sa.Integer(),
            sa.ForeignKey("tags.id", ondelete="SET NULL"),
            nullable=True,
            comment="由主体流程新增的主名称标签ID；仅该值对应的标签可在切换主体时移除",
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="创建人ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="更新时间",
        ),
        comment="图片主体结果表",
    )
    op.create_index("ix_image_subjects_image_id", "image_subjects", ["image_id"])
    op.create_index("ix_image_subjects_subject_id", "image_subjects", ["subject_id"])
    op.create_unique_constraint(
        "uq_image_subjects_image_subject",
        "image_subjects",
        ["image_id", "subject_id"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_image_subjects_primary
        ON image_subjects (image_id)
        WHERE is_primary = true
        """
    )
    # payload 中的 image_id 由主体建议服务统一写入。该部分唯一索引在并发请求
    # 下确保每张图片至多有一条 pending 主体建议。
    op.execute(
        """
        CREATE UNIQUE INDEX uq_approvals_pending_subject_image
        ON approvals ((payload ->> 'image_id'))
        WHERE type = 'suggest_subject_assignment' AND status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_approvals_pending_subject_image")
    op.execute("DROP INDEX IF EXISTS uq_image_subjects_primary")
    op.execute("ALTER TABLE image_subjects DROP CONSTRAINT IF EXISTS uq_image_subjects_image_subject")
    op.execute("DROP INDEX IF EXISTS ix_image_subjects_subject_id")
    op.execute("DROP INDEX IF EXISTS ix_image_subjects_image_id")
    op.drop_table("image_subjects")

    op.execute("DROP INDEX IF EXISTS ix_subject_samples_model")
    op.execute("DROP INDEX IF EXISTS ix_subject_samples_subject_id")
    op.drop_table("subject_samples")

    op.execute("DROP INDEX IF EXISTS ix_subjects_category_tag")
    op.execute("DROP INDEX IF EXISTS ix_subjects_active")
    op.execute("ALTER TABLE subjects DROP CONSTRAINT IF EXISTS uq_subjects_primary_tag")
    op.drop_table("subjects")
