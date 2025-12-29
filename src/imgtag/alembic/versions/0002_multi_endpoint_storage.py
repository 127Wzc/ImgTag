"""Add multi-endpoint storage support.

Revision ID: 0002_multi_endpoint_storage
Revises: 0001_initial
Create Date: 2025-12-29

Adds:
- storage_endpoints table for S3/R2/OSS configuration
- image_locations table for tracking images across endpoints
- is_public column on images for privacy control
- Migrates existing storage data to new structure
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002_multi_endpoint_storage"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 1. Create storage_endpoints table ===
    op.create_table(
        "storage_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("name", sa.String(50), unique=True, nullable=False, comment="端点名称"),
        sa.Column("provider", sa.String(20), nullable=False, comment="提供商: local/s3/r2/oss/cos/minio"),
        # S3 configuration
        sa.Column("endpoint_url", sa.Text(), nullable=True, comment="端点URL"),
        sa.Column("region", sa.String(50), server_default="auto", nullable=True, comment="区域"),
        sa.Column("bucket_name", sa.String(100), nullable=True, comment="存储桶名称"),
        sa.Column("path_style", sa.Boolean(), server_default="true", nullable=False, comment="是否使用路径风格(true=path, false=virtual-hosted)"),
        sa.Column("access_key_id", sa.Text(), nullable=True, comment="访问密钥ID(加密)"),
        sa.Column("secret_access_key", sa.Text(), nullable=True, comment="访问密钥(加密)"),
        # Public access
        sa.Column("public_url_prefix", sa.Text(), nullable=True, comment="CDN或公开访问前缀"),
        sa.Column("path_prefix", sa.String(100), server_default="", nullable=False, comment="对象路径前缀"),
        # Role and status
        sa.Column("role", sa.String(20), server_default="primary", nullable=False, comment="角色: primary/mirror/backup"),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False, comment="是否启用"),
        sa.Column("is_default_upload", sa.Boolean(), server_default="false", nullable=False, comment="是否为默认上传端点"),
        # Auto-sync
        sa.Column("auto_sync_enabled", sa.Boolean(), server_default="false", nullable=False, comment="是否自动同步"),
        sa.Column("sync_from_endpoint_id", sa.Integer(), sa.ForeignKey("storage_endpoints.id", ondelete="SET NULL"), nullable=True, comment="同步来源端点ID"),
        # Read strategy
        sa.Column("read_priority", sa.Integer(), server_default="100", nullable=False, comment="读取优先级(越小越优先)"),
        sa.Column("read_weight", sa.Integer(), server_default="1", nullable=False, comment="负载均衡权重"),
        # Health
        sa.Column("is_healthy", sa.Boolean(), server_default="true", nullable=False, comment="是否健康"),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True, comment="最后健康检查时间"),
        sa.Column("health_check_error", sa.Text(), nullable=True, comment="健康检查错误信息"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="存储端点配置表",
    )

    # === 2. Create image_locations table ===
    op.create_table(
        "image_locations",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False, comment="图片ID"),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("storage_endpoints.id", ondelete="RESTRICT"), nullable=False, comment="存储端点ID"),
        sa.Column("object_key", sa.Text(), nullable=False, comment="对象键(如 images/ab/cd/hash.jpg)"),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False, comment="是否为主存储位置"),
        sa.Column("sync_status", sa.String(20), server_default="synced", nullable=False, comment="同步状态: synced/pending/failed"),
        sa.Column("sync_error", sa.Text(), nullable=True, comment="同步错误信息"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True, comment="同步完成时间"),
        comment="图片存储位置表",
    )
    
    # Indexes for image_locations
    op.create_unique_constraint("uq_image_location", "image_locations", ["image_id", "endpoint_id"])
    op.create_index("ix_image_locations_image_id", "image_locations", ["image_id"])
    op.create_index("ix_image_locations_endpoint_id", "image_locations", ["endpoint_id"])
    op.create_index("ix_image_locations_sync_status", "image_locations", ["sync_status"])

    # === 3. Add is_public column to images ===
    op.add_column("images", sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False, comment="是否公开可见"))

    # === 4. Create default "local" endpoint and migrate existing data ===
    conn = op.get_bind()
    
    # Insert default local endpoint with bucket_name='uploads'
    # bucket_name is used as both URL path (/uploads/...) and physical directory name
    conn.execute(sa.text("""
        INSERT INTO storage_endpoints (name, provider, is_default_upload, role, read_priority, bucket_name)
        VALUES ('local', 'local', true, 'primary', 1, 'uploads')
    """))
    
    # Get the local endpoint ID
    result = conn.execute(sa.text("SELECT id FROM storage_endpoints WHERE name = 'local'"))
    local_endpoint_id = result.scalar()
    
    # Migrate existing images to image_locations
    # Extract only filename from file_path or image_url (not full path)
    conn.execute(sa.text("""
        INSERT INTO image_locations (image_id, endpoint_id, object_key, is_primary, sync_status, synced_at)
        SELECT 
            id,
            :endpoint_id,
            COALESCE(
                -- Extract filename from file_path (handle both /path/to/file.jpg and file.jpg)
                REGEXP_REPLACE(file_path, '^.*/([^/]+)$', '\\1'),
                -- Or extract from image_url (remove /uploads/ prefix)
                REGEXP_REPLACE(image_url, '^/uploads/', '')
            ),
            true,
            'synced',
            NOW()
        FROM images
        WHERE file_path IS NOT NULL OR image_url LIKE '/uploads/%'
    """), {"endpoint_id": local_endpoint_id})

    # Check if any S3 images exist and create S3 endpoint if needed
    s3_count = conn.execute(sa.text("SELECT COUNT(*) FROM images WHERE s3_path IS NOT NULL")).scalar()
    
    if s3_count > 0:
        # Create S3 endpoint from existing config (will need manual credential setup)
        conn.execute(sa.text("""
            INSERT INTO storage_endpoints (name, provider, role, read_priority, is_default_upload)
            VALUES ('s3-migrated', 's3', 'primary', 50, false)
        """))
        
        result = conn.execute(sa.text("SELECT id FROM storage_endpoints WHERE name = 's3-migrated'"))
        s3_endpoint_id = result.scalar()
        
        # Migrate S3 images
        conn.execute(sa.text("""
            INSERT INTO image_locations (image_id, endpoint_id, object_key, is_primary, sync_status, synced_at)
            SELECT 
                id,
                :endpoint_id,
                s3_path,
                CASE WHEN storage_type = 's3' THEN true ELSE false END,
                'synced',
                NOW()
            FROM images
            WHERE s3_path IS NOT NULL
            ON CONFLICT (image_id, endpoint_id) DO NOTHING
        """), {"endpoint_id": s3_endpoint_id})

    # === 5. Add index for is_public + uploaded_by (for privacy filtering) ===
    op.create_index("ix_images_is_public_uploaded_by", "images", ["is_public", "uploaded_by"])

    # === 6. Remove legacy storage columns (now handled by image_locations) ===
    op.drop_column("images", "image_url")
    op.drop_column("images", "file_path")
    op.drop_column("images", "storage_type")
    op.drop_column("images", "s3_path")
    op.drop_column("images", "local_exists")

    # === 7. Delete deprecated S3 config keys (now managed via storage_endpoints) ===
    conn.execute(sa.text("""
        DELETE FROM configs WHERE key IN (
            's3_enabled', 's3_endpoint_url', 's3_access_key_id', 's3_secret_access_key',
            's3_bucket_name', 's3_region', 's3_public_url_prefix', 's3_path_prefix',
            's3_force_reupload', 'image_url_priority'
        )
    """))


def downgrade() -> None:
    # Restore legacy columns
    op.add_column("images", sa.Column("local_exists", sa.Boolean(), server_default="true", nullable=False, comment="本地文件是否存在"))
    op.add_column("images", sa.Column("s3_path", sa.Text(), nullable=True, comment="S3存储路径"))
    op.add_column("images", sa.Column("storage_type", sa.String(20), server_default="local", nullable=False, comment="存储类型: local/s3"))
    op.add_column("images", sa.Column("file_path", sa.Text(), nullable=True, comment="本地文件路径"))
    op.add_column("images", sa.Column("image_url", sa.Text(), nullable=False, server_default="", comment="图片访问URL"))
    
    # Restore data from image_locations
    conn = op.get_bind()
    
    # Restore file_path and image_url from local endpoint
    conn.execute(sa.text("""
        UPDATE images SET 
            file_path = il.object_key,
            image_url = '/uploads/' || il.object_key,
            local_exists = true
        FROM image_locations il
        JOIN storage_endpoints se ON il.endpoint_id = se.id
        WHERE il.image_id = images.id AND se.provider = 'local' AND il.is_primary = true
    """))
    
    # Restore s3_path from S3 endpoints
    conn.execute(sa.text("""
        UPDATE images SET 
            s3_path = il.object_key,
            storage_type = 's3'
        FROM image_locations il
        JOIN storage_endpoints se ON il.endpoint_id = se.id
        WHERE il.image_id = images.id AND se.provider != 'local' AND il.is_primary = true
    """))
    
    # Remove new index
    op.drop_index("ix_images_is_public_uploaded_by", table_name="images")
    
    # Remove is_public column
    op.drop_column("images", "is_public")
    
    # Drop image_locations indexes and table
    op.drop_index("ix_image_locations_sync_status", table_name="image_locations")
    op.drop_index("ix_image_locations_endpoint_id", table_name="image_locations")
    op.drop_index("ix_image_locations_image_id", table_name="image_locations")
    op.drop_constraint("uq_image_location", "image_locations", type_="unique")
    op.drop_table("image_locations")
    
    # Drop storage_endpoints table
    op.drop_table("storage_endpoints")

