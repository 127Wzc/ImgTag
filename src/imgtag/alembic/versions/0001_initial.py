"""Initial schema creation with multi-endpoint storage support.

Revision ID: 0001
Revises:
Create Date: 2025-12-26

Creates all tables for ImgTag from scratch with unified storage architecture.
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

    # === Storage Endpoints table ===
    op.create_table(
        "storage_endpoints",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("name", sa.String(50), unique=True, nullable=False, comment="端点名称"),
        sa.Column("provider", sa.String(20), nullable=False, comment="提供商: local/s3"),
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
        sa.Column("role", sa.String(20), server_default="primary", nullable=False, comment="角色: primary(主)/backup(备份)"),
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

    # === Images table (without legacy storage columns) ===
    op.create_table(
        "images",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("file_hash", sa.String(64), nullable=True, comment="文件MD5哈希"),
        sa.Column("file_type", sa.String(20), nullable=True, comment="文件类型"),
        sa.Column("file_size", sa.Numeric(10, 2), nullable=True, comment="文件大小(MB)"),
        sa.Column("width", sa.Integer(), nullable=True, comment="宽度(px)"),
        sa.Column("height", sa.Integer(), nullable=True, comment="高度(px)"),
        sa.Column("original_url", sa.Text(), nullable=True, comment="原始URL"),
        sa.Column("description", sa.Text(), nullable=True, comment="图片描述"),
        sa.Column("embedding", Vector(512), nullable=True, comment="向量嵌入(512维)"),
        sa.Column("is_public", sa.Boolean(), server_default="true", nullable=False, comment="是否公开可见"),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="上传用户ID"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False, comment="更新时间"),
        comment="图片信息表",
    )
    op.create_index("ix_images_file_hash", "images", ["file_hash"])
    op.create_index("ix_images_created_at", "images", [sa.text("created_at DESC")])
    op.create_index("ix_images_is_public_uploaded_by", "images", ["is_public", "uploaded_by"])

    # === Image Locations table ===
    op.create_table(
        "image_locations",
        sa.Column("id", sa.Integer(), primary_key=True, comment="主键ID"),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False, comment="图片ID"),
        sa.Column("endpoint_id", sa.Integer(), sa.ForeignKey("storage_endpoints.id", ondelete="RESTRICT"), nullable=False, comment="存储端点ID"),
        sa.Column("object_key", sa.Text(), nullable=False, comment="对象键(如 category/ab/cd/hash.jpg)"),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False, comment="是否为主存储位置"),
        sa.Column("sync_status", sa.String(20), server_default="synced", nullable=False, comment="同步状态: synced/pending/failed"),
        sa.Column("sync_error", sa.Text(), nullable=True, comment="同步错误信息"),
        sa.Column("category_code", sa.String(50), nullable=True, comment="上传时的分类代码"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment="创建时间"),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True, comment="同步完成时间"),
        comment="图片存储位置表",
    )
    op.create_unique_constraint("uq_image_location", "image_locations", ["image_id", "endpoint_id"])
    op.create_index("ix_image_locations_image_id", "image_locations", ["image_id"])
    op.create_index("ix_image_locations_endpoint_id", "image_locations", ["endpoint_id"])
    op.create_index("ix_image_locations_sync_status", "image_locations", ["sync_status"])

    # === Tags table (with category fields) ===
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
        sa.Column("code", sa.String(50), unique=True, nullable=True, comment="分类代码(用于存储子目录)"),
        sa.Column("prompt", sa.Text(), nullable=True, comment="分类专用分析提示词"),
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

    # 1. Create default local storage endpoint
    conn.execute(sa.text("""
        INSERT INTO storage_endpoints (name, provider, is_default_upload, role, read_priority, bucket_name)
        VALUES ('local', 'local', true, 'primary', 1, 'uploads')
    """))

    # 2. Seed Category Tags (Level 0) with codes and prompts
    categories = [
        ('风景', '自然风光、城市景观', 1, 'landscape', '''# 风景图片分析要求

请重点关注：
1. **场景类型**：自然风光（山川、海洋、森林等）或城市景观
2. **时间/天气**：日出、日落、晴天、阴天、雨雪等
3. **构图特点**：前景、中景、背景的层次
4. **光线/色调**：暖色调、冷色调、对比度等
5. **地理特征**：可识别的地点、地标

tags 应包含：场景类型、地理元素、天气、季节、色调风格'''),
        ('人像', '真人照片、人物特写', 2, 'portrait', '''# 人像图片分析要求

请重点关注：
1. **人物特征**：性别、年龄段、表情、姿态
2. **拍摄风格**：特写、半身、全身、环境人像
3. **背景环境**：室内/室外、纯色背景/场景背景
4. **光线效果**：自然光、人工光、逆光、侧光等
5. **服装/配饰**：着装风格、特色配饰

tags 应包含：人物特征、拍摄类型、场景、光线风格'''),
        ('动漫', '动画、漫画、二次元', 3, 'anime', '''# 动漫/二次元图片分析要求

请重点关注：
1. **角色信息**：角色名称（如能识别）、角色特征
2. **作品来源**：动画、漫画、游戏作品名（如能识别）
3. **画风特点**：赛璐璐、厚涂、水彩风、线稿等
4. **场景类型**：日常、战斗、校园、奇幻等
5. **情感表达**：角色的表情、氛围

tags 应包含：角色名、作品名、画风、场景类型、情感'''),
        ('表情包', '表情、梗图、搞笑图', 4, 'meme', '''# 表情包/梗图分析要求

请重点关注：
1. **主体**：图片中的核心形象（熊猫头、杰尼龟、动漫角色、名人等）
2. **文字**：提取图片上所有文字（OCR）。如果模糊请推断；如果没有请标注"无"
3. **心情/氛围**：2-4 个形容词描述情绪（阴阳怪气、无奈、暴躁、委屈、嘲讽等）
4. **表述含义**：一句话解释使用场景或潜台词

description 格式：主体: xxx。文字: xxx。心情/氛围: xxx。表述含义: xxx。
tags 应包含：主体名称、情绪、关键动作、梗名称'''),
        ('产品', '商品、摄影棚照片', 5, 'product', '''# 产品图片分析要求

请重点关注：
1. **产品类型**：电子产品、服饰、食品、家居等
2. **品牌标识**：可识别的品牌 logo 或名称
3. **拍摄风格**：白底图、场景图、模特展示等
4. **产品特征**：颜色、材质、款式、功能特点
5. **构图角度**：正面、侧面、45度、俯拍等

tags 应包含：产品类别、品牌、颜色、拍摄风格'''),
        ('艺术', '绘画、设计作品', 6, 'art', '''# 艺术作品分析要求

请重点关注：
1. **艺术类型**：油画、水彩、素描、数字艺术、雕塑、装置等
2. **风格流派**：印象派、抽象派、超现实主义、极简主义等
3. **主题内容**：人物、风景、静物、抽象
4. **色彩运用**：主色调、对比、饱和度
5. **艺术家**：如能识别作者或作品名称

tags 应包含：艺术类型、风格流派、主题、色彩特点'''),
        ('图文', '截图、文档、图文混合', 7, 'text_image', '''# 图文类图片分析要求（截图/文档）

请重点关注：
1. **类型判断**：截图（手机/电脑界面）还是文档（证件、表格、书页）
2. **来源平台**：微信、微博、抖音、网页、操作系统等
3. **关键文字**：OCR 提取主要文字内容
4. **内容主题**：聊天记录、新闻、通知、表格数据等
5. **格式特征**：深色/浅色模式、印刷体/手写体

tags 应包含：类型（截图/文档）、平台来源、内容主题、关键词'''),
        ('美食', '美食、食物、饮品照片', 8, 'food', '''# 美食图片分析要求

请重点关注：
1. **食物类型**：中餐、西餐、日料、甜点、饮品等
2. **菜品名称**：如能识别具体菜名
3. **呈现方式**：摆盘、容器、装饰
4. **场景环境**：餐厅、家庭、户外野餐等
5. **视觉特点**：色彩搭配、食欲感、拍摄角度

tags 应包含：菜系、菜品名、食材、场景、风格'''),
        ('宠物', '猫狗等宠物、动物照片', 9, 'pet', '''# 宠物/动物图片分析要求

请重点关注：
1. **动物种类**：猫、狗、兔子、仓鼠、鸟类等（具体品种更佳）
2. **行为动作**：睡觉、玩耍、进食、卖萌等
3. **表情状态**：开心、好奇、慵懒、警惕等
4. **环境场景**：室内、户外、宠物店等
5. **特殊特征**：毛色、体型、配饰

tags 应包含：动物种类、品种（如适用）、行为、情绪、特征'''),
        ('壁纸', '桌面/手机壁纸、高清大图', 10, 'wallpaper', '''# 壁纸图片分析要求

请重点关注：
1. **适用场景**：桌面壁纸、手机壁纸、平板壁纸
2. **主题风格**：风景、抽象、极简、科幻、动漫等
3. **色调氛围**：暖色调、冷色调、渐变、纯色等
4. **构图特点**：是否适合放置图标、留白区域
5. **分辨率类型**：横版/竖版、宽屏/标准

tags 应包含：适用设备、主题风格、色调、画面元素'''),
        ('其他', '无法分类', 99, 'other', '''# 其他图片分析要求

请尽可能详细描述图片内容，包括：
1. 图片中的主要元素
2. 场景或背景
3. 可能的用途或含义

tags 应涵盖图片的主要特征和关键词'''),
    ]

    for name, desc, order, code, prompt in categories:
        conn.execute(sa.text("""
            INSERT INTO tags (name, level, source, description, sort_order, code, prompt) 
            VALUES (:name, 0, 'system', :desc, :order, :code, :prompt)
        """), {"name": name, "desc": desc, "order": order, "code": code, "prompt": prompt})

    # 3. Seed Resolution Tags (Level 1)
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
    op.drop_index("ix_image_locations_sync_status", table_name="image_locations")
    op.drop_index("ix_image_locations_endpoint_id", table_name="image_locations")
    op.drop_index("ix_image_locations_image_id", table_name="image_locations")
    op.drop_constraint("uq_image_location", "image_locations", type_="unique")
    op.drop_table("image_locations")
    op.drop_table("images")
    op.drop_table("storage_endpoints")
    op.drop_table("users")
