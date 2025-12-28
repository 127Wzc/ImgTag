"""Initial schema creation.

Revision ID: 0001
Revises: 
Create Date: 2025-12-26

Creates all tables for ImgTag from scratch.
Use this migration for fresh database initialization.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (required for vector type)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # === Users table ===
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("username", sa.String(50), unique=True, nullable=False, comment="用户名"),
        sa.Column("email", sa.String(100), unique=True, nullable=True, comment="邮箱"),
        sa.Column("password_hash", sa.String(255), nullable=False, comment="密码哈希"),
        sa.Column("role", sa.String(20), server_default="user", nullable=False, comment="角色"),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False, comment="是否激活"),
        sa.Column("api_key", sa.String(64), unique=True, nullable=True, comment="API密钥"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True, comment="最后登录时间"),
        comment="用户表",
    )

    # === Images table ===
    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("image_url", sa.Text(), nullable=False, comment="图片访问URL"),
        sa.Column("file_path", sa.Text(), nullable=True, comment="本地文件路径"),
        sa.Column("file_hash", sa.String(64), nullable=True, comment="文件MD5哈希"),
        sa.Column("file_type", sa.String(20), nullable=True, comment="文件类型"),
        sa.Column("file_size", sa.Numeric(10, 2), nullable=True, comment="文件大小(MB)"),
        sa.Column("width", sa.Integer(), nullable=True, comment="宽度(px)"),
        sa.Column("height", sa.Integer(), nullable=True, comment="高度(px)"),
        sa.Column("storage_type", sa.String(20), server_default="local", nullable=False, comment="存储类型"),
        sa.Column("s3_path", sa.Text(), nullable=True, comment="S3存储路径"),
        sa.Column("local_exists", sa.Boolean(), server_default="true", nullable=False, comment="本地文件是否存在"),
        sa.Column("original_url", sa.Text(), nullable=True, comment="原始URL"),
        sa.Column("description", sa.Text(), nullable=True, comment="图片描述"),
        sa.Column("embedding", Vector(512), nullable=True, comment="向量嵌入(512维)"),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="上传用户ID"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="图片信息表",
    )
    op.create_index("ix_images_file_hash", "images", ["file_hash"])
    op.create_index("ix_images_created_at", "images", [sa.text("created_at DESC")])

    # === Tags table ===
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("name", sa.String(100), unique=True, nullable=False, comment="标签名"),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, comment="父标签ID"),
        sa.Column("source", sa.String(20), server_default="system", nullable=False, comment="来源"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("level", sa.Integer(), server_default="2", nullable=False, comment="层级"),
        sa.Column("usage_count", sa.Integer(), server_default="0", nullable=False, comment="使用次数"),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False, comment="排序"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="标签表",
    )

    # === Image-Tags association ===
    op.create_table(
        "image_tags",
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source", sa.String(20), server_default="ai", nullable=False, comment="来源"),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="添加用户ID"),
        sa.Column("sort_order", sa.Integer(), server_default="99", nullable=False, comment="排序"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="添加时间"),
        comment="图片-标签关联表",
    )

    # === Collections table ===
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("name", sa.String(100), nullable=False, comment="名称"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("cover_image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="SET NULL"), nullable=True, comment="封面图片ID"),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, comment="父收藏夹ID"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True, comment="所属用户ID"),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False, comment="排序"),
        sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False, comment="是否公开"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="收藏夹表",
    )

    # === Image-Collections association ===
    op.create_table(
        "image_collections",
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("collection_id", sa.Integer(), sa.ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="添加时间"),
        comment="图片-收藏夹关联表",
    )

    # === Tasks table ===
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(36), primary_key=True, comment="任务ID(UUID)"),
        sa.Column("type", sa.String(50), nullable=False, comment="任务类型"),
        sa.Column("status", sa.String(20), nullable=False, comment="状态"),
        sa.Column("payload", postgresql.JSONB(), nullable=True, comment="任务输入数据"),
        sa.Column("result", postgresql.JSONB(), nullable=True, comment="任务结果数据"),
        sa.Column("error", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="完成时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="任务队列表",
    )

    # === Approvals table ===
    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("type", sa.String(50), nullable=False, comment="请求类型"),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False, comment="状态"),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="请求用户ID"),
        sa.Column("target_type", sa.String(50), nullable=True, comment="目标类型"),
        sa.Column("target_ids", postgresql.ARRAY(sa.Integer()), nullable=True, comment="目标ID列表"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, comment="请求数据"),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="审批用户ID"),
        sa.Column("review_comment", sa.Text(), nullable=True, comment="审批备注"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True, comment="审批时间"),
        comment="审批请求表",
    )

    # === Audit logs table ===
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="操作用户ID"),
        sa.Column("action", sa.String(50), nullable=False, comment="操作类型"),
        sa.Column("target_type", sa.String(50), nullable=True, comment="目标类型"),
        sa.Column("target_id", sa.Integer(), nullable=True, comment="目标ID"),
        sa.Column("old_value", postgresql.JSONB(), nullable=True, comment="旧值"),
        sa.Column("new_value", postgresql.JSONB(), nullable=True, comment="新值"),
        sa.Column("ip_address", sa.String(45), nullable=True, comment="IP地址"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="操作时间"),
        comment="审计日志表",
    )

    # === Config table ===
    op.create_table(
        "config",
        sa.Column("key", sa.String(100), primary_key=True, comment="配置键"),
        sa.Column("value", sa.Text(), nullable=False, comment="配置值"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("is_secret", sa.Boolean(), server_default="false", nullable=False, comment="是否为敏感配置"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="系统配置表",
    )

    # === Schema meta table ===
    op.create_table(
        "schema_meta",
        sa.Column("key", sa.String(50), primary_key=True, comment="元信息键"),
        sa.Column("value", sa.Text(), nullable=False, comment="元信息值"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="数据库元信息表",
    )

    # Create vector index for similarity search
    op.execute("""
        CREATE INDEX ix_images_embedding ON images 
        USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
    """)

    # === Seed Initial Data ===
    conn = op.get_bind()
    
    # 1. Seed Category Tags (Level 0)
    categories = [
        ('风景', '自然风光、城市景观', 1),
        ('人像', '真人照片、人物特写', 2),
        ('动漫', '动画、漫画、二次元', 3),
        ('表情包', '表情、梗图、搞笑图', 4),
        ('产品', '商品、摄影棚照片', 5),
        ('艺术', '绘画、设计作品', 6),
        ('截图', '屏幕截图、界面', 7),
        ('文档', '文字、表格、证件', 8),
        ('其他', '无法分类', 99),
    ]

    for name, desc, order in categories:
        conn.execute(sa.text("""
            INSERT INTO tags (name, level, source, description, sort_order) 
            VALUES (:name, 0, 'system', :desc, :order)
        """), {"name": name, "desc": desc, "order": order})

    # 2. Seed Resolution Tags (Level 1)
    # Using raw SQL to insert default data
    resolutions = [
        ('8K', '超高清 8K 分辨率 (≥7680px)', 100),
        ('4K', '超高清 4K 分辨率 (≥3840px)', 101),
        ('2K', '高清 2K 分辨率 (≥2560px)', 102),
        ('1080p', '全高清 1080p (≥1920px)', 103),
        ('720p', '高清 720p (≥1280px)', 104),
        ('SD', '标清 (<1280px)', 105),
    ]

    for name, desc, order in resolutions:
         conn.execute(sa.text("""
            INSERT INTO tags (name, level, source, description, sort_order) 
            VALUES (:name, 1, 'system', :desc, :order)
        """), {"name": name, "desc": desc, "order": order})


def downgrade() -> None:
    op.drop_table("schema_meta")
    op.drop_table("config")
    op.drop_table("audit_logs")
    op.drop_table("approvals")
    op.drop_table("tasks")
    op.drop_table("image_collections")
    op.drop_table("collections")
    op.drop_table("image_tags")
    op.drop_table("tags")
    op.drop_table("images")
    op.drop_table("users")
