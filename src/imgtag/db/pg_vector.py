#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PostgreSQL 向量数据库操作
包含对 images 表的增删改查操作
使用连接池管理数据库连接
"""

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.types.json import Json
import time
import os
from typing import List, Optional, Dict, Any, Tuple

from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.core.config import settings

logger = get_logger(__name__)
perf_logger = get_perf_logger()

# Schema 版本号 - 每次数据库结构变化时更新此版本号
# 格式：主版本.次版本.补丁 (major.minor.patch)
# - major: 不兼容的结构变化
# - minor: 新增表/字段
# - patch: 索引优化等小改动
SCHEMA_VERSION = "1.2.1"


class PGVectorDB:
    """PostgreSQL 向量数据库操作类（使用连接池）"""
    
    _instance = None
    _pool = None
    
    def __new__(cls, connection_string: str = None):
        """创建单例实例"""
        if cls._instance is None:
            logger.info("创建 PGVectorDB 单例实例")
            cls._instance = super(PGVectorDB, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, connection_string: str = None):
        """初始化数据库连接池"""
        if getattr(self, "_initialized", False):
            return
            
        if connection_string is None:
            connection_string = settings.PG_CONNECTION_STRING
        
        start_time = time.time()
        logger.info("初始化数据库连接池")
        
        try:
            PGVectorDB._pool = ConnectionPool(
                connection_string,
                min_size=2,
                max_size=10,
                name="pg_vector_pool",
                timeout=30,
                max_idle=300,  # 5分钟空闲后关闭连接
                check=ConnectionPool.check_connection  # 连接健康检查
            )
            
            with PGVectorDB._pool.connection() as conn:
                conn.autocommit = True
                with conn.cursor() as cursor:
                    self._init_tables(cursor)
            
            init_time = time.time() - start_time
            logger.info("数据库连接池初始化成功")
            perf_logger.info(f"数据库连接池初始化耗时: {init_time:.4f}秒")
            
            self._initialized = True
        except Exception as e:
            logger.error(f"数据库连接池初始化失败: {str(e)}")
            raise
    
    def _get_connection(self):
        """获取连接池中的连接"""
        return PGVectorDB._pool.connection()
    
    def _init_tables(self, cursor):
        """初始化数据库表（支持智能跳过检查）"""
        start_time = time.time()
        
        # 检查是否跳过数据库结构检查
        skip_check = os.environ.get("DB_SKIP_CHECK", "").lower() in ("true", "1", "yes")
        if skip_check:
            logger.info("DB_SKIP_CHECK=true，跳过数据库结构检查")
            return
        
        # 检查 schema_meta 表是否存在，用于存储版本信息
        cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'schema_meta'
        );
        """)
        schema_meta_exists = cursor.fetchone()[0]
        
        stored_version = None
        if schema_meta_exists:
            cursor.execute("SELECT value FROM schema_meta WHERE key = 'schema_version';")
            result = cursor.fetchone()
            stored_version = result[0] if result else None
        
        # 版本匹配，跳过完整检查但运行轻量验证
        if stored_version == SCHEMA_VERSION:
            logger.info(f"数据库结构版本匹配 (v{SCHEMA_VERSION})，执行轻量验证")
            self._quick_validate_schema(cursor)
            perf_logger.info(f"数据库轻量验证耗时: {time.time() - start_time:.4f}秒")
            return
        
        if stored_version:
            logger.info(f"数据库结构版本变化: {stored_version} -> {SCHEMA_VERSION}，执行完整检查")
        else:
            logger.info(f"首次运行或无版本记录，执行完整数据库结构检查 (v{SCHEMA_VERSION})")
        
        try:
            # 检查 vector 扩展
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions 
                WHERE name = 'vector' AND installed_version IS NOT NULL
            );
            """)
            
            vector_extension_exists = cursor.fetchone()[0]
            
            if not vector_extension_exists:
                logger.info("安装 vector 扩展")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # 检查 images 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'images'
            );
            """)
            
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                logger.info("创建 images 表")
                
                # 使用配置的向量维度
                vector_dim = settings.EMBEDDING_DIMENSIONS
                
                cursor.execute(f"""
                CREATE TABLE public.images (
                    id SERIAL PRIMARY KEY,
                    image_url TEXT NOT NULL,
                    file_type VARCHAR(20),
                    file_size DECIMAL(10,2),
                    description TEXT,
                    file_path TEXT,
                    original_url TEXT,
                    file_hash VARCHAR(64),
                    uploaded_by INTEGER,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    embedding vector({vector_dim})
                );
                """)
                
                # 添加列注释
                cursor.execute("""
                COMMENT ON TABLE public.images IS '图片信息表';
                COMMENT ON COLUMN public.images.id IS '主键ID';
                COMMENT ON COLUMN public.images.image_url IS '图片访问URL';
                COMMENT ON COLUMN public.images.file_type IS '文件类型(jpg/png/gif等)';
                COMMENT ON COLUMN public.images.file_size IS '文件大小(MB)';
                COMMENT ON COLUMN public.images.description IS '图片描述';
                COMMENT ON COLUMN public.images.file_path IS '本地文件路径';
                COMMENT ON COLUMN public.images.original_url IS '原始URL';
                COMMENT ON COLUMN public.images.file_hash IS '文件MD5哈希';
                COMMENT ON COLUMN public.images.uploaded_by IS '上传用户ID';
                COMMENT ON COLUMN public.images.created_at IS '创建时间';
                COMMENT ON COLUMN public.images.updated_at IS '更新时间';
                COMMENT ON COLUMN public.images.embedding IS '向量嵌入';
                """)
                
                # 创建索引（移除了 tags 索引）
                cursor.execute(f"""
                CREATE INDEX idx_images_embedding ON public.images 
                USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
                """)
                
                cursor.execute("""
                CREATE INDEX idx_images_created_at ON public.images (created_at DESC);
                """)
                
                logger.info("images 表创建成功")
            else:
                logger.info("images 表已存在")
            
            # 检查 collections 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'collections'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 collections 表")
                cursor.execute("""
                CREATE TABLE public.collections (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    cover_image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
                    parent_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
                    sort_order INTEGER DEFAULT 0,
                    is_public BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                """)
                logger.info("collections 表创建成功")
            
            # 检查 image_collections 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'image_collections'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 image_collections 表")
                cursor.execute("""
                CREATE TABLE public.image_collections (
                    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                    collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
                    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (image_id, collection_id)
                );
                """)
                logger.info("image_collections 表创建成功")
            
            # 检查 tags 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'tags'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 tags 表（带层级支持）")
                cursor.execute("""
                CREATE TABLE public.tags (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) UNIQUE NOT NULL,
                    parent_id INTEGER REFERENCES tags(id) ON DELETE SET NULL,
                    source VARCHAR(20) DEFAULT 'system',
                    description TEXT,
                    level INTEGER DEFAULT 1,
                    usage_count INTEGER DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                """)
                cursor.execute("CREATE INDEX idx_tags_parent ON public.tags(parent_id);")
                logger.info("tags 表创建成功")
            
            # 检查 tasks 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'tasks'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 tasks 表")
                cursor.execute("""
                CREATE TABLE public.tasks (
                    id VARCHAR(36) PRIMARY KEY,
                    type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    payload JSONB,
                    result JSONB,
                    error TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    completed_at TIMESTAMP WITH TIME ZONE
                );
                """)
                logger.info("tasks 表创建成功")
            
            # 检查 users 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'users'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 users 表")
                cursor.execute("""
                CREATE TABLE public.users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(20) NOT NULL DEFAULT 'user',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    last_login_at TIMESTAMP WITH TIME ZONE
                );
                """)
                cursor.execute("CREATE INDEX idx_users_role ON public.users(role);")
                
                # 插入默认管理员账号 (密码: admin123)
                import hashlib
                import secrets
                salt = secrets.token_hex(16)
                pw_hash = hashlib.pbkdf2_hmac(
                    'sha256', 
                    'admin'.encode('utf-8'), 
                    salt.encode('utf-8'), 
                    100000
                )
                password_hash = f"{salt}${pw_hash.hex()}"
                cursor.execute("""
                INSERT INTO users (username, password_hash, role)
                VALUES ('admin', %s, 'admin')
                ON CONFLICT (username) DO NOTHING;
                """, (password_hash,))
                logger.info("users 表创建成功，默认管理员账号已创建 (admin/admin)")
            
            # 检查 approvals 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'approvals'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 approvals 表")
                cursor.execute("""
                CREATE TABLE public.approvals (
                    id SERIAL PRIMARY KEY,
                    type VARCHAR(50) NOT NULL,
                    status VARCHAR(20) DEFAULT 'pending',
                    requester_id INTEGER REFERENCES users(id),
                    target_type VARCHAR(50),
                    target_ids INTEGER[],
                    payload JSONB NOT NULL,
                    reviewer_id INTEGER REFERENCES users(id),
                    review_comment TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    reviewed_at TIMESTAMP WITH TIME ZONE
                );
                """)
                cursor.execute("CREATE INDEX idx_approvals_status ON public.approvals(status);")
                cursor.execute("CREATE INDEX idx_approvals_requester ON public.approvals(requester_id);")
                logger.info("approvals 表创建成功")
            
            # 检查 audit_logs 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'audit_logs'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 audit_logs 表")
                cursor.execute("""
                CREATE TABLE public.audit_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    action VARCHAR(50) NOT NULL,
                    target_type VARCHAR(50),
                    target_id INTEGER,
                    old_value JSONB,
                    new_value JSONB,
                    ip_address VARCHAR(45),
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                """)
                cursor.execute("CREATE INDEX idx_audit_logs_user ON public.audit_logs(user_id);")
                cursor.execute("CREATE INDEX idx_audit_logs_action ON public.audit_logs(action);")
                logger.info("audit_logs 表创建成功")
            
            # 检查 image_tags 表
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'image_tags'
            );
            """)
            
            if not cursor.fetchone()[0]:
                logger.info("创建 image_tags 表")
                cursor.execute("""
                CREATE TABLE public.image_tags (
                    image_id INTEGER REFERENCES images(id) ON DELETE CASCADE,
                    tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
                    source VARCHAR(20) NOT NULL DEFAULT 'ai',
                    added_by INTEGER REFERENCES users(id),
                    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (image_id, tag_id)
                );
                """)
                # 核心索引：tag_id 用于按标签查询；image_id 已是主键的前缀，自动有索引
                cursor.execute("CREATE INDEX idx_image_tags_tag_id ON public.image_tags(tag_id);")
                logger.info("image_tags 表创建成功")
            
            # 所有表创建完成后，检查并添加新列
            self._check_and_add_columns(cursor)
            
            # 确保默认 admin 账号存在
            self._ensure_default_admin(cursor)
            
            # 创建/更新 schema_meta 表保存版本号
            self._save_schema_version(cursor)
            
            init_time = time.time() - start_time
            perf_logger.info(f"表结构初始化耗时: {init_time:.4f}秒")
            
        except Exception as e:
            logger.error(f"初始化表结构失败: {str(e)}")
            raise
    
    def _check_and_add_columns(self, cursor):
        """检查并添加新列"""
        # images 表新列（注意：uploaded_by 不使用外键约束以避免顺序问题）
        images_columns = [
            ("file_path", "TEXT"),
            ("original_url", "TEXT"),
            ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
            ("uploaded_by", "INTEGER"),  # 逻辑外键，不加约束
            ("file_hash", "VARCHAR(64)"),  # 文件 MD5 哈希，用于去重
            ("file_type", "VARCHAR(20)"),  # 文件类型，如 jpg、png、gif
            ("file_size", "DECIMAL(10,2)"),  # 文件大小 (MB)
            # v1.2.1 新增
            ("width", "INTEGER"),  # 图片宽度（像素）
            ("height", "INTEGER"),  # 图片高度（像素）
            ("storage_type", "VARCHAR(20) DEFAULT 'local'"),  # 存储类型: local/s3
            ("s3_path", "TEXT"),  # S3 完整存储路径
            ("local_exists", "BOOLEAN DEFAULT TRUE"),  # 本地文件是否存在
        ]
        
        for col_name, col_type in images_columns:
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'images' 
                AND column_name = %s
            );
            """, (col_name,))
            
            if not cursor.fetchone()[0]:
                logger.info(f"添加 images 表新列: {col_name}")
                cursor.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_type};")
        
        # tags 表新列（针对已存在的旧表）
        tags_columns = [
            ("parent_id", "INTEGER REFERENCES tags(id) ON DELETE SET NULL"),
            ("source", "VARCHAR(20) DEFAULT 'system'"),
            ("description", "TEXT"),
            ("level", "INTEGER DEFAULT 1"),
            ("sort_order", "INTEGER DEFAULT 0"),
            ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
        ]
        
        for col_name, col_type in tags_columns:
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'tags' 
                AND column_name = %s
            );
            """, (col_name,))
            
            if not cursor.fetchone()[0]:
                logger.info(f"添加 tags 表新列: {col_name}")
                cursor.execute(f"ALTER TABLE tags ADD COLUMN {col_name} {col_type};")
        
        # collections 表新列（用户关联）
        cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'collections' 
            AND column_name = 'user_id'
        );
        """)
        if not cursor.fetchone()[0]:
            logger.info("添加 collections 表新列: user_id")
            cursor.execute("ALTER TABLE collections ADD COLUMN user_id INTEGER;")
            # 设置现有收藏夹归属于管理员（user_id=1）
            cursor.execute("UPDATE collections SET user_id = 1 WHERE user_id IS NULL;")
        
        # users 表新列（API 密钥）
        cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'users' 
            AND column_name = 'api_key'
        );
        """)
        if not cursor.fetchone()[0]:
            logger.info("添加 users 表新列: api_key")
            cursor.execute("ALTER TABLE users ADD COLUMN api_key VARCHAR(64) UNIQUE;")
        
        # image_tags 表新列（v1.2.1：标签排序）
        cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_schema = 'public' 
            AND table_name = 'image_tags' 
            AND column_name = 'sort_order'
        );
        """)
        if not cursor.fetchone()[0]:
            logger.info("添加 image_tags 表新列: sort_order")
            cursor.execute("ALTER TABLE image_tags ADD COLUMN sort_order INTEGER DEFAULT 99;")
        
        # 预插入系统标签（v1.2.1）
        self._ensure_system_tags(cursor)
        
        # 优化索引：删除废弃索引，确保核心索引存在
        self._optimize_indexes(cursor)
    
    def _ensure_system_tags(self, cursor):
        """确保系统标签存在（主分类 level=0，分辨率 level=1）"""
        # 主分类标签（level=0, id=1-99）
        # ID 10 "待分类" 是新图片的默认分类
        main_categories = [
            (1, '风景', '自然风光、城市景观', 1),
            (2, '人像', '真人照片、人物特写', 2),
            (3, '动漫', '动画、漫画、二次元', 3),
            (4, '表情包', '表情、梗图、搞笑图', 4),
            (5, '产品', '商品、摄影棚照片', 5),
            (6, '艺术', '绘画、设计作品', 6),
            (7, '截图', '屏幕截图、界面', 7),
            (8, '文档', '文字、表格、证件', 8),
            (9, '其他', '无法分类', 99),
            (10, '待分类', '新图片默认分类，等待人工分类', 0),  # 排序为 0，置顶
        ]
        
        for tag_id, name, desc, sort_order in main_categories:
            cursor.execute("""
            INSERT INTO tags (id, name, level, source, description, sort_order)
            VALUES (%s, %s, 0, 'system', %s, %s)
            ON CONFLICT (name) DO NOTHING;
            """, (tag_id, name, desc, sort_order))
        
        # 分辨率标签（level=1, id=100-105）
        resolution_tags = [
            (100, '8K', '超高清 8K 分辨率 (≥7680px)', 100),
            (101, '4K', '超高清 4K 分辨率 (≥3840px)', 101),
            (102, '2K', '高清 2K 分辨率 (≥2560px)', 102),
            (103, '1080p', '全高清 1080p (≥1920px)', 103),
            (104, '720p', '高清 720p (≥1280px)', 104),
            (105, 'SD', '标清 (<1280px)', 105),
        ]
        
        for tag_id, name, desc, sort_order in resolution_tags:
            cursor.execute("""
            INSERT INTO tags (id, name, level, source, description, sort_order)
            VALUES (%s, %s, 1, 'system', %s, %s)
            ON CONFLICT (name) DO NOTHING;
            """, (tag_id, name, desc, sort_order))
        
        # 确保序列从 1000 开始（为 AI/用户标签预留空间）
        cursor.execute("""
        SELECT setval('tags_id_seq', GREATEST(1000, (SELECT COALESCE(MAX(id), 0) FROM tags)));
        """)
        
        logger.info("系统标签检查完成（主分类 + 分辨率），序列已设置为从 1000 开始")
    
    def _optimize_indexes(self, cursor):
        """优化索引：删除废弃索引，确保核心索引存在"""
        # 需要删除的废弃索引列表
        deprecated_indexes = [
            "idx_image_tags_source",      # 按source查询很少用
            "idx_image_tags_image_id",    # 主键前缀已有索引
            "idx_image_tags_image_tag",   # 与主键重复
            "idx_users_role",             # 用户量小，不需要
            "idx_tags_parent",            # 标签层级很少用
            "idx_approvals_requester",    # 审批量小，不需要
            "idx_audit_logs_user",        # 审计日志很少查询
            "idx_audit_logs_action",      # 审计日志很少查询
            "idx_images_tags",            # 旧的 tags 数组索引（已废弃）
        ]
        
        # 删除废弃索引
        deleted_count = 0
        for idx_name in deprecated_indexes:
            try:
                cursor.execute(f"DROP INDEX IF EXISTS {idx_name};")
                # 检查是否真的删除了（通过影响行数无法判断，用日志记录）
                deleted_count += 1
            except Exception as e:
                logger.debug(f"删除索引 {idx_name} 时出错（可能不存在）: {e}")
        
        logger.info(f"索引清理完成，尝试删除 {len(deprecated_indexes)} 个废弃索引")
        
        # 核心索引定义：{索引名: 创建语句}
        core_indexes = {
            "idx_image_tags_tag_id": "CREATE INDEX IF NOT EXISTS idx_image_tags_tag_id ON public.image_tags(tag_id);",
            "idx_tags_name": "CREATE INDEX IF NOT EXISTS idx_tags_name ON public.tags(name);",
            "idx_approvals_status": "CREATE INDEX IF NOT EXISTS idx_approvals_status ON public.approvals(status);",
            "idx_images_created_at": "CREATE INDEX IF NOT EXISTS idx_images_created_at ON public.images(created_at DESC);",
        }
        
        # 确保核心索引存在
        created_count = 0
        for idx_name, create_sql in core_indexes.items():
            try:
                cursor.execute(create_sql)
                created_count += 1
            except Exception as e:
                logger.warning(f"创建索引 {idx_name} 失败: {e}")
        
        logger.info(f"核心索引检查完成，确保 {len(core_indexes)} 个索引存在")
    
    def _save_schema_version(self, cursor):
        """保存 schema 版本到数据库"""
        try:
            # 创建 schema_meta 表（如果不存在）
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS public.schema_meta (
                key VARCHAR(50) PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            """)
            
            # 插入或更新 schema 版本
            cursor.execute("""
            INSERT INTO schema_meta (key, value, updated_at)
            VALUES ('schema_version', %s, NOW())
            ON CONFLICT (key) DO UPDATE SET value = %s, updated_at = NOW();
            """, (SCHEMA_VERSION, SCHEMA_VERSION))
            
            logger.info(f"已保存数据库结构版本: {SCHEMA_VERSION}")
        except Exception as e:
            logger.warning(f"保存 schema 版本失败: {e}")
    
    def _quick_validate_schema(self, cursor):
        """轻量验证：检查核心表和索引是否存在，缺失时自动修复"""
        issues = []
        
        # 核心表列表
        expected_tables = ["images", "tags", "users", "collections", "image_tags", 
                          "image_collections", "approvals", "audit_logs", "schema_meta"]
        
        # 检查表是否存在
        cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public';
        """)
        existing_tables = {row[0] for row in cursor.fetchall()}
        
        missing_tables = set(expected_tables) - existing_tables
        if missing_tables:
            issues.append(f"缺失表: {', '.join(missing_tables)}")
            logger.warning(f"发现缺失表: {', '.join(missing_tables)}")
            logger.warning("  手动修复: 更新 SCHEMA_VERSION 触发完整检查，或手动执行建表语句")
        
        # 核心索引定义：{索引名: 创建语句}
        core_indexes = {
            "idx_image_tags_tag_id": "CREATE INDEX IF NOT EXISTS idx_image_tags_tag_id ON public.image_tags(tag_id);",
            "idx_tags_name": "CREATE INDEX IF NOT EXISTS idx_tags_name ON public.tags(name);",
            "idx_approvals_status": "CREATE INDEX IF NOT EXISTS idx_approvals_status ON public.approvals(status);",
            "idx_images_created_at": "CREATE INDEX IF NOT EXISTS idx_images_created_at ON public.images(created_at DESC);",
        }
        
        # 检查索引是否存在
        cursor.execute("""
        SELECT indexname FROM pg_indexes WHERE schemaname = 'public';
        """)
        existing_indexes = {row[0] for row in cursor.fetchall()}
        
        # 检查并自动创建缺失的核心索引
        missing_indexes = set(core_indexes.keys()) - existing_indexes
        if missing_indexes:
            logger.info(f"发现 {len(missing_indexes)} 个缺失索引，正在自动创建...")
            for idx_name in missing_indexes:
                create_sql = core_indexes[idx_name]
                try:
                    cursor.execute(create_sql)
                    logger.info(f"  ✓ 已创建索引: {idx_name}")
                except Exception as e:
                    logger.error(f"  ✗ 创建索引 {idx_name} 失败: {e}")
                    issues.append(f"创建索引失败: {idx_name}")
        
        # 检查是否有多余的废弃索引
        deprecated_indexes = [
            "idx_image_tags_source", "idx_image_tags_image_id", "idx_image_tags_image_tag",
            "idx_users_role", "idx_tags_parent", "idx_approvals_requester",
            "idx_audit_logs_user", "idx_audit_logs_action", "idx_images_tags"
        ]
        extra_indexes = set(deprecated_indexes) & existing_indexes
        if extra_indexes:
            logger.info(f"发现 {len(extra_indexes)} 个废弃索引，正在自动删除...")
            for idx_name in extra_indexes:
                try:
                    cursor.execute(f"DROP INDEX IF EXISTS {idx_name};")
                    logger.info(f"  ✓ 已删除废弃索引: {idx_name}")
                except Exception as e:
                    logger.warning(f"  ✗ 删除索引 {idx_name} 失败: {e}")
        
        if issues:
            logger.warning(f"数据库结构验证发现 {len(issues)} 个问题")
        else:
            logger.info("数据库结构验证通过")
    
    def _ensure_default_admin(self, cursor):
        """确保默认管理员账号存在"""
        cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            import hashlib
            import secrets
            salt = secrets.token_hex(16)
            pw_hash = hashlib.pbkdf2_hmac(
                'sha256', 
                'admin'.encode('utf-8'), 
                salt.encode('utf-8'), 
                100000
            )
            password_hash = f"{salt}${pw_hash.hex()}"
            cursor.execute("""
            INSERT INTO users (username, password_hash, role)
            VALUES ('admin', %s, 'admin');
            """, (password_hash,))
            logger.info("默认管理员账号已创建 (admin/admin)")
        else:
            logger.info("默认管理员账号已存在")
    
    def insert_image(
        self,
        image_url: str,
        tags: List[str],
        embedding: List[float] = None,
        description: str = None,
        file_path: str = None,
        original_url: str = None,
        tag_source: str = "ai",
        file_hash: str = None,
        file_type: str = None,
        file_size: float = None,
        width: int = None,
        height: int = None,
        storage_type: str = "local",
        s3_path: str = None,
        local_exists: bool = True,
        category_id: int = None
    ) -> Optional[int]:
        """插入一条图像记录
        
        Args:
            embedding: 向量嵌入，可为 None 表示未生成向量
            width: 图片宽度（像素）
            height: 图片高度（像素）
            storage_type: 存储类型 local/s3
            s3_path: S3 完整存储路径
            local_exists: 本地文件是否存在
            category_id: 用户指定的 level=0 分类标签 ID
        """
        start_time = time.time()
        logger.debug(f"插入图像记录: {image_url}")
        
        try:
            # 支持 embedding 为 None（表示未生成向量）
            embedding_value = None
            if embedding is not None and len(embedding) > 0:
                vector_str = ','.join(map(str, embedding))
                embedding_value = f"[{vector_str}]"
            
            # 自动从 URL 截取文件类型
            if not file_type:
                import os
                url_path = image_url.split("?")[0]  # 去掉查询参数
                file_type = os.path.splitext(url_path)[1].lower().lstrip(".")
                if not file_type:
                    file_type = "unknown"
            
            # 不再存储 tags 到 images 表
            query = """
            INSERT INTO images (image_url, embedding, description, file_path, original_url, file_hash, file_type, file_size, width, height, storage_type, s3_path, local_exists)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (
                        image_url, embedding_value, description,
                        file_path, original_url, file_hash, file_type, file_size,
                        width, height, storage_type, s3_path, local_exists
                    ))
                    new_id = cursor.fetchone()[0]
                conn.commit()
            
            # 使用关联表存储标签
            if tags and len(tags) > 0:
                self.set_image_tags(new_id, tags, source=tag_source)
            
            # 自动分配系统标签（level 0 分类 + level 1 分辨率）
            self.auto_assign_system_tags(new_id, width, height, category_id=category_id)
            
            process_time = time.time() - start_time
            logger.info(f"插入成功，ID: {new_id}, 耗时: {process_time:.4f}秒")
            
            return new_id
        except Exception as e:
            logger.error(f"插入失败: {str(e)}")
            return None
    
    def set_image_tags(self, image_id: int, tags: List[str], source: str = "ai", user_id: int = None):
        """设置图片的标签（智能更新：保留现有标签来源，新标签用指定来源）"""
        if not tags:
            # 如果传空列表，删除所有标签并减少计数
            try:
                with self._get_connection() as conn:
                    with conn.cursor() as cursor:
                        # 先减少被删除标签的计数
                        cursor.execute("""
                            UPDATE tags SET usage_count = usage_count - 1
                            WHERE id IN (SELECT tag_id FROM image_tags WHERE image_id = %s);
                        """, (image_id,))
                        cursor.execute("DELETE FROM image_tags WHERE image_id = %s", (image_id,))
                    conn.commit()
            except Exception as e:
                logger.error(f"删除图片标签失败: {str(e)}")
            return
        
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    tag_names = [t.strip() for t in tags if t.strip()]
                    if not tag_names:
                        conn.commit()
                        return
                    
                    # 获取当前图片的所有标签及来源
                    cursor.execute("""
                    SELECT t.name, it.source FROM image_tags it
                    JOIN tags t ON it.tag_id = t.id
                    WHERE it.image_id = %s;
                    """, (image_id,))
                    existing_tags = {row[0]: row[1] for row in cursor.fetchall()}
                    
                    # 计算需要删除和添加的标签
                    new_tag_set = set(tag_names)
                    existing_tag_set = set(existing_tags.keys())
                    
                    tags_to_delete = existing_tag_set - new_tag_set
                    tags_to_add = new_tag_set - existing_tag_set
                    
                    # 删除不再需要的标签关联，并减少计数
                    if tags_to_delete:
                        placeholders = ','.join(['%s'] * len(tags_to_delete))
                        # 先减少被删除标签的计数
                        cursor.execute(f"""
                            UPDATE tags SET usage_count = usage_count - 1
                            WHERE name IN ({placeholders});
                        """, list(tags_to_delete))
                        cursor.execute(f"""
                        DELETE FROM image_tags WHERE image_id = %s AND tag_id IN (
                            SELECT id FROM tags WHERE name IN ({placeholders})
                        );
                        """, [image_id] + list(tags_to_delete))
                    
                    # 只为新增的标签创建关联
                    if tags_to_add:
                        for tag_name in tags_to_add:
                            # 确保标签存在（AI/用户创建的标签 level=2）
                            cursor.execute("""
                            INSERT INTO tags (name, source, level)
                            VALUES (%s, %s, 2)
                            ON CONFLICT (name) DO UPDATE SET usage_count = tags.usage_count + 1
                            RETURNING id;
                            """, (tag_name, source))
                            tag_id = cursor.fetchone()[0]
                            
                            # 插入关联
                            cursor.execute("""
                            INSERT INTO image_tags (image_id, tag_id, source, added_by)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (image_id, tag_id) DO NOTHING;
                            """, (image_id, tag_id, source, user_id))
                    
                conn.commit()
            logger.info(f"更新图片 {image_id} 标签: +{len(tags_to_add)} -{len(tags_to_delete)}, 新标签来源: {source}")
        except Exception as e:
            logger.error(f"设置图片标签失败: {str(e)}")
    
    def search_by_tags(self, tags: List[str], limit: int = None) -> List[Dict]:
        """通过标签搜索图像（使用 image_tags 关联表）"""
        if limit is None:
            limit = settings.DEFAULT_SEARCH_LIMIT
            
        start_time = time.time()
        logger.info(f"按标签搜索: {tags}, 限制: {limit}")
        
        try:
            if not tags:
                return []
            
            tag_placeholders = ','.join(['%s'] * len(tags))
            query = f"""
            SELECT i.id, i.image_url, i.description, i.original_url
            FROM images i
            WHERE i.id IN (
                SELECT it.image_id FROM image_tags it
                JOIN tags t ON it.tag_id = t.id
                WHERE t.name IN ({tag_placeholders})
                GROUP BY it.image_id
                HAVING COUNT(DISTINCT t.name) = %s
            )
            LIMIT %s;
            """
            
            params = list(tags) + [len(tags), limit]
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    results = cursor.fetchall()
                    
                    # 批量获取标签
                    image_ids = [row[0] for row in results]
                    tags_map = {}
                    if image_ids:
                        cursor.execute("""
                        SELECT it.image_id, ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                        FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE it.image_id = ANY(%s)
                        GROUP BY it.image_id;
                        """, (image_ids,))
                        for row in cursor.fetchall():
                            tags_map[row[0]] = row[1]
            
            images = []
            for row in results:
                images.append({
                    "id": row[0],
                    "image_url": row[1],
                    "tags": tags_map.get(row[0], []),
                    "description": row[2],
                    "original_url": row[3]
                })
            
            process_time = time.time() - start_time
            logger.info(f"标签搜索完成，找到 {len(images)} 条记录，耗时: {process_time:.4f}秒")
            
            return images
        except Exception as e:
            logger.error(f"标签搜索失败: {str(e)}")
            return []
    
    def search_similar_vectors(
        self, 
        query_vector: List[float], 
        limit: int = None, 
        threshold: float = None
    ) -> List[Dict]:
        """向量相似度搜索"""
        if limit is None:
            limit = settings.DEFAULT_SEARCH_LIMIT
        if threshold is None:
            threshold = settings.DEFAULT_SIMILARITY_THRESHOLD
            
        start_time = time.time()
        logger.info(f"向量相似度搜索，阈值: {threshold}, 限制: {limit}")
        
        try:
            vector_str = ','.join(map(str, query_vector))
            
            query = """
            SELECT id, image_url, description, original_url,
                   1 - (embedding <=> %s) as similarity
            FROM images
            WHERE 1 - (embedding <=> %s) > %s
            ORDER BY similarity DESC
            LIMIT %s;
            """
            
            query_start = time.time()
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (
                        f"[{vector_str}]", f"[{vector_str}]", threshold, limit
                    ))
                    results = cursor.fetchall()
                    
                    # 批量获取标签
                    image_ids = [row[0] for row in results]
                    tags_map = {}
                    if image_ids:
                        cursor.execute("""
                        SELECT it.image_id, ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                        FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE it.image_id = ANY(%s)
                        GROUP BY it.image_id;
                        """, (image_ids,))
                        for row in cursor.fetchall():
                            tags_map[row[0]] = row[1]
            
            query_time = time.time() - query_start
            perf_logger.info(f"向量搜索 SQL 执行耗时: {query_time:.4f}秒")
            
            images = []
            for row in results:
                images.append({
                    "id": row[0],
                    "image_url": row[1],
                    "tags": tags_map.get(row[0], []),
                    "description": row[2],
                    "original_url": row[3],
                    "similarity": row[4]
                })
            
            total_time = time.time() - start_time
            logger.info(f"向量搜索完成，找到 {len(images)} 条记录，耗时: {total_time:.4f}秒")
            
            if images:
                max_similarity = max(img["similarity"] for img in images)
                perf_logger.info(f"最高相似度: {max_similarity:.4f}")
            
            return images
        except Exception as e:
            logger.error(f"向量搜索失败: {str(e)}")
            return []

    def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = None,
        threshold: float = None,
        vector_weight: float = 0.7,
        tag_weight: float = 0.3,
        category_id: int = None,
        resolution_id: int = None
    ) -> List[Dict]:
        """混合搜索：向量相似度 + 标签匹配（优化版，使用 LEFT JOIN 替代多次 EXISTS）"""
        if limit is None:
            limit = settings.DEFAULT_SEARCH_LIMIT
        if threshold is None:
            threshold = settings.DEFAULT_SIMILARITY_THRESHOLD
            
        start_time = time.time()
        logger.info(f"混合搜索: '{query_text}', 阈值: {threshold}, 分类: {category_id}, 分辨率: {resolution_id}")
        
        try:
            vector_str = ','.join(map(str, query_vector))
            
            # 构建额外的过滤条件
            extra_conditions = []
            extra_params = []
            if category_id:
                extra_conditions.append("i.id IN (SELECT image_id FROM image_tags WHERE tag_id = %s)")
                extra_params.append(category_id)
            if resolution_id:
                extra_conditions.append("i.id IN (SELECT image_id FROM image_tags WHERE tag_id = %s)")
                extra_params.append(resolution_id)
            
            extra_where = " AND " + " AND ".join(extra_conditions) if extra_conditions else ""
            
            # 优化版：使用 LEFT JOIN 一次性计算标签匹配，避免多次 EXISTS 子查询
            # tag_match 子查询只执行一次，结果通过 LEFT JOIN 关联
            # 过滤掉 NULL 向量：未生成向量的图片不参与相似度搜索
            query = f"""
            WITH tag_match AS (
                SELECT DISTINCT it.image_id
                FROM image_tags it
                JOIN tags t ON it.tag_id = t.id
                WHERE t.name = %s
            )
            SELECT i.id, i.image_url, i.description, i.original_url,
                   (1 - (i.embedding <=> %s)) as vector_score,
                   (CASE WHEN tm.image_id IS NOT NULL THEN 1.0 ELSE 0.0 END) as tag_score,
                   i.s3_path, i.local_exists
            FROM images i
            LEFT JOIN tag_match tm ON i.id = tm.image_id
            WHERE i.embedding IS NOT NULL
              AND ((1 - (i.embedding <=> %s)) > %s OR tm.image_id IS NOT NULL)
              {extra_where}
            ORDER BY (
                (1 - (i.embedding <=> %s)) * %s + 
                (CASE WHEN tm.image_id IS NOT NULL THEN 1.0 ELSE 0.0 END) * %s
            ) DESC
            LIMIT %s;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    params = [
                        query_text,
                        f"[{vector_str}]", 
                        f"[{vector_str}]", 
                        threshold
                    ] + extra_params + [
                        f"[{vector_str}]",
                        vector_weight,
                        tag_weight,
                        limit
                    ]
                    cursor.execute(query, params)
                    results = cursor.fetchall()
                    
                    # 批量获取标签（只取 level=2 的普通标签）
                    image_ids = [row[0] for row in results]
                    tags_map = {}
                    if image_ids:
                        cursor.execute("""
                        SELECT it.image_id, ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                        FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE it.image_id = ANY(%s) AND t.level = 2
                        GROUP BY it.image_id;
                        """, (image_ids,))
                        for row in cursor.fetchall():
                            tags_map[row[0]] = row[1]
            
            images = []
            for row in results:
                # row: id, image_url, description, original_url, vector_score, tag_score, s3_path, local_exists
                vector_score = float(row[4])
                tag_score = float(row[5])
                final_score = vector_score * vector_weight + tag_score * tag_weight
                display_url = self.get_display_url(row[1], row[6], row[7] if row[7] is not None else True)
                
                images.append({
                    "id": row[0],
                    "image_url": display_url,
                    "tags": tags_map.get(row[0], []),
                    "description": row[2],
                    "original_url": row[3],
                    "similarity": final_score,
                    "vector_score": vector_score,
                    "tag_score": tag_score
                })
            
            total_time = time.time() - start_time
            logger.info(f"混合搜索完成，找到 {len(images)} 条记录，耗时: {total_time:.4f}秒")
            
            return images
        except Exception as e:
            logger.error(f"混合搜索失败: {str(e)}")
            return []
    
    def count_images(self) -> int:
        """获取图像总数"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM images;")
                    count = cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"获取图像总数失败: {str(e)}")
            return 0
    
    def count_pending_images(self) -> int:
        """获取待分析图片数量（没有标签的图片）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) FROM images i
                        WHERE i.id NOT IN (SELECT DISTINCT image_id FROM image_tags);
                    """)
                    count = cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"获取待分析图片数量失败: {str(e)}")
            return 0
    
    def count_images_by_date(self, date_str: str, count_type: str = "uploaded") -> int:
        """按日期统计图片数量
        
        Args:
            date_str: 日期字符串，格式 YYYY-MM-DD
            count_type: 'uploaded' 按上传日期统计，'analyzed' 按分析完成（有标签）日期统计
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    if count_type == "uploaded":
                        # 按上传日期（created_at）统计
                        cursor.execute("""
                            SELECT COUNT(*) FROM images
                            WHERE DATE(created_at) = %s;
                        """, (date_str,))
                    else:
                        # 按分析完成日期统计（最近添加标签的日期）
                        cursor.execute("""
                            SELECT COUNT(DISTINCT it.image_id) FROM image_tags it
                            WHERE DATE(it.added_at) = %s;
                        """, (date_str,))
                    count = cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"按日期统计图片失败: {str(e)}")
            return 0
    
    def search_images(
        self,
        tags: List[str] = None,
        url_contains: str = None,
        description_contains: str = None,
        keyword: str = None,
        category_id: int = None,
        resolution_id: int = None,
        pending_only: bool = False,
        duplicates_only: bool = False,
        limit: int = 10,
        offset: int = 0,
        sort_by: str = "id",
        sort_desc: bool = False
    ) -> Dict[str, Any]:
        """高级图像搜索"""
        start_time = time.time()
        logger.info(f"高级图像搜索: 标签:{tags}, URL包含:{url_contains}, 关键字:{keyword}, 分类:{category_id}, 分辨率:{resolution_id}")
        
        try:
            conditions = []
            params = []
            
            # 主分类过滤 (level=0)
            if category_id:
                conditions.append("""
                    i.id IN (SELECT image_id FROM image_tags WHERE tag_id = %s)
                """)
                params.append(category_id)
            
            # 分辨率过滤 (level=1)
            if resolution_id:
                conditions.append("""
                    i.id IN (SELECT image_id FROM image_tags WHERE tag_id = %s)
                """)
                params.append(resolution_id)
            
            # 待分析过滤：无标签的图片
            if pending_only:
                conditions.append("""
                    i.id NOT IN (SELECT DISTINCT image_id FROM image_tags)
                """)
            
            # 重复图片过滤：只显示有重复 hash 的图片
            if duplicates_only:
                conditions.append("""
                    i.file_hash IN (
                        SELECT file_hash FROM images 
                        WHERE file_hash IS NOT NULL AND file_hash != ''
                        GROUP BY file_hash HAVING COUNT(*) > 1
                    )
                """)
            
            # 标签过滤：使用子查询
            if tags and len(tags) > 0:
                tag_placeholders = ','.join(['%s'] * len(tags))
                conditions.append(f"""
                    i.id IN (
                        SELECT it.image_id FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE t.name IN ({tag_placeholders})
                        GROUP BY it.image_id
                        HAVING COUNT(DISTINCT t.name) = %s
                    )
                """)
                params.extend(tags)
                params.append(len(tags))
            
            if url_contains:
                conditions.append("i.image_url ILIKE %s")
                params.append(f"%{url_contains}%")
            
            # 关键字搜索：同时模糊匹配描述和标签
            if keyword:
                conditions.append("""
                    (i.description ILIKE %s OR i.id IN (
                        SELECT it.image_id FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE t.name ILIKE %s
                    ))
                """)
                params.append(f"%{keyword}%")
                params.append(f"%{keyword}%")
            elif description_contains:
                # 向后兼容：只匹配描述
                conditions.append("i.description ILIKE %s")
                params.append(f"%{description_contains}%")
            
            valid_sort_fields = {"id": "i.id", "url": "i.image_url", "created_at": "i.created_at"}
            sort_field = valid_sort_fields.get(sort_by, "i.id")
            sort_order = "DESC" if sort_desc else "ASC"
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 获取图片列表
            query = f"""
            SELECT i.id, i.image_url, i.description, i.original_url, i.s3_path, i.local_exists
            FROM images i
            WHERE {where_clause}
            ORDER BY {sort_field} {sort_order}
            LIMIT %s OFFSET %s;
            """
            
            query_params = params + [limit, offset]
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, query_params)
                    results = cursor.fetchall()
                    
                    # 批量获取标签（只取 level=2 的普通标签）
                    image_ids = [row[0] for row in results]
                    tags_map = {}
                    if image_ids:
                        cursor.execute("""
                        SELECT it.image_id, ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                        FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE it.image_id = ANY(%s) AND t.level = 2
                        GROUP BY it.image_id;
                        """, (image_ids,))
                        for row in cursor.fetchall():
                            tags_map[row[0]] = row[1]
            
            images = []
            for row in results:
                # row: id, image_url, description, original_url, s3_path, local_exists
                display_url = self.get_display_url(row[1], row[4], row[5] if row[5] is not None else True)
                images.append({
                    "id": row[0],
                    "image_url": display_url,
                    "tags": tags_map.get(row[0], []),
                    "description": row[2],
                    "original_url": row[3]
                })
            
            # 获取总数
            count_query = f"""
            SELECT COUNT(*) FROM images i WHERE {where_clause};
            """
            
            total_count = 0
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(count_query, params)
                    total_count = cursor.fetchone()[0]
            
            process_time = time.time() - start_time
            logger.info(f"高级搜索完成，找到 {len(images)}/{total_count} 条记录，耗时: {process_time:.4f}秒")
            
            return {
                "images": images,
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        except Exception as e:
            logger.error(f"高级搜索失败: {str(e)}")
            return {"images": [], "total": 0, "limit": limit, "offset": offset}

    def get_random_images_by_tags(self, tags: List[str], count: int = 1) -> List[Dict]:
        """根据标签获取随机图片"""
        start_time = time.time()
        logger.info(f"随机图片查询: 标签={tags}, 数量={count}")
        
        try:
            conditions = []
            params = []
            
            # 标签过滤
            if tags and len(tags) > 0:
                tag_placeholders = ','.join(['%s'] * len(tags))
                conditions.append(f"""
                    i.id IN (
                        SELECT it.image_id FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE t.name IN ({tag_placeholders})
                        GROUP BY it.image_id
                        HAVING COUNT(DISTINCT t.name) = %s
                    )
                """)
                params.extend(tags)
                params.append(len(tags))
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            # 随机查询
            query = f"""
            SELECT i.id, i.image_url, i.description
            FROM images i
            WHERE {where_clause}
            ORDER BY RANDOM()
            LIMIT %s;
            """
            params.append(count)
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    results = cursor.fetchall()
                    
                    # 获取标签
                    image_ids = [row[0] for row in results]
                    tags_map = {}
                    if image_ids:
                        cursor.execute("""
                        SELECT it.image_id, ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                        FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE it.image_id = ANY(%s)
                        GROUP BY it.image_id;
                        """, (image_ids,))
                        for row in cursor.fetchall():
                            tags_map[row[0]] = row[1]
            
            images = []
            for row in results:
                images.append({
                    "id": row[0],
                    "image_url": row[1],
                    "description": row[2],
                    "tags": tags_map.get(row[0], [])
                })
            
            process_time = time.time() - start_time
            logger.info(f"随机图片查询完成，找到 {len(images)} 条记录，耗时: {process_time:.4f}秒")
            
            return images
        except Exception as e:
            logger.error(f"随机图片查询失败: {str(e)}")
            return []

    def sync_tags(self) -> int:
        """同步 tags 表与 image_tags 关联表中的标签计数"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 先将所有标签计数重置为 0
                    cursor.execute("UPDATE tags SET usage_count = 0;")
                    
                    # 2. 从 image_tags 关联表重新计算每个标签的使用次数
                    cursor.execute("""
                    UPDATE tags
                    SET usage_count = tag_counts.count
                    FROM (
                        SELECT tag_id, COUNT(*) as count
                        FROM image_tags
                        GROUP BY tag_id
                    ) AS tag_counts
                    WHERE tags.id = tag_counts.tag_id;
                    """)
                    
                    return cursor.rowcount
        except Exception as e:
            logger.error(f"同步标签失败: {str(e)}")
            return 0

    def get_tags(self, limit: int = 100, sort_by: str = "usage_count") -> List[Dict]:
        """获取标签列表"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    order_clause = "usage_count DESC" if sort_by == "usage_count" else "name ASC"
                    cursor.execute(f"""
                    SELECT id, name, usage_count, created_at
                    FROM tags 
                    ORDER BY {order_clause} 
                    LIMIT %s;
                    """, (limit,))
                    
                    return [{
                        "id": row[0],
                        "name": row[1],
                        "usage_count": row[2],
                        "created_at": row[3]
                    } for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"获取标签列表失败: {str(e)}")
            return []

    def tag_exists(self, name: str) -> bool:
        """检查标签是否存在（高效索引查询）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM tags WHERE name = %s LIMIT 1;", (name,))
                    return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"检查标签存在失败: {str(e)}")
            return False

    def rename_tag(self, old_name: str, new_name: str) -> bool:
        """重命名标签（ID 不变，仅修改名称）
        
        如果新名称已存在则拒绝重命名。
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 检查新标签名是否已存在
                    cursor.execute("SELECT id FROM tags WHERE name = %s;", (new_name,))
                    if cursor.fetchone():
                        logger.warning(f"标签 '{new_name}' 已存在，无法重命名")
                        return False
                    
                    # 2. 获取旧标签的 ID
                    cursor.execute("SELECT id FROM tags WHERE name = %s;", (old_name,))
                    old_tag = cursor.fetchone()
                    
                    if not old_tag:
                        logger.warning(f"旧标签 '{old_name}' 不存在")
                        return False
                    
                    old_tag_id = old_tag[0]
                    
                    # 3. 直接重命名（ID 保持不变）
                    cursor.execute("""
                    UPDATE tags SET name = %s, updated_at = NOW() WHERE id = %s;
                    """, (new_name, old_tag_id))
                    
                    return True
        except Exception as e:
            logger.error(f"重命名标签失败: {str(e)}")
            return False

    def delete_tag(self, tag_name: str) -> bool:
        """删除标签（image_tags 会级联删除）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 直接从 tags 表删除，image_tags 会通过外键级联删除
                    cursor.execute("DELETE FROM tags WHERE name = %s;", (tag_name,))
                    
                    return True
        except Exception as e:
            logger.error(f"删除标签失败: {str(e)}")
            return False
    
    def update_image(
        self,
        image_id: int,
        image_url: str = None,
        tags: List[str] = None,
        description: str = None,
        embedding: List[float] = None,
        tag_source: str = "user",
        user_id: int = None,
        original_url: str = None
    ) -> bool:
        """更新图像信息"""
        start_time = time.time()
        logger.info(f"更新图像 ID:{image_id}")
        
        try:
            update_fields = []
            params = []
            
            if image_url is not None:
                update_fields.append("image_url = %s")
                params.append(image_url)
                
            # 标签通过 set_image_tags 更新，不再存到 images 表
            if tags is not None:
                self.set_image_tags(image_id, tags, source=tag_source, user_id=user_id)
                
            if description is not None:
                update_fields.append("description = %s")
                params.append(description)
                
            if embedding is not None:
                vector_str = ','.join(map(str, embedding))
                update_fields.append("embedding = %s")
                params.append(f"[{vector_str}]")
            
            if original_url is not None:
                update_fields.append("original_url = %s")
                params.append(original_url)
            
            update_fields.append("updated_at = NOW()")
            
            if len(update_fields) == 1:
                # 只有 updated_at，跳过
                if tags is None:
                    logger.info("没有提供要更新的字段")
                    return True
            
            query = f"""
            UPDATE images
            SET {", ".join(update_fields)}
            WHERE id = %s;
            """
            
            params.append(image_id)
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    if cursor.rowcount == 0 and len(update_fields) > 1:
                        logger.warning(f"未找到 ID 为 {image_id} 的图像记录")
                        return False
                conn.commit()
            
            process_time = time.time() - start_time
            logger.info(f"图像信息更新完成，耗时: {process_time:.4f}秒")
            
            return True
        except Exception as e:
            logger.error(f"图像信息更新失败: {str(e)}")
            return False
    
    def sync_user_tags(self, image_id: int, tags: List[str], source: str = "user", user_id: int = None):
        """同步用户添加的标签到 image_tags 表"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    for tag_name in tags:
                        # 确保 tag 存在于 tags 表（用户标签 level=2）
                        cursor.execute("""
                        INSERT INTO tags (name, source, level)
                        VALUES (%s, %s, 2)
                        ON CONFLICT (name) DO UPDATE SET usage_count = tags.usage_count + 1
                        RETURNING id;
                        """, (tag_name, source))
                        tag_id = cursor.fetchone()[0]
                        
                        # 插入或更新 image_tags
                        cursor.execute("""
                        INSERT INTO image_tags (image_id, tag_id, source, added_by)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (image_id, tag_id) DO UPDATE SET source = %s, added_by = %s;
                        """, (image_id, tag_id, source, user_id, source, user_id))
                conn.commit()
            logger.info(f"同步 {len(tags)} 个 {source} 标签到图片 {image_id}")
        except Exception as e:
            logger.error(f"同步用户标签失败: {str(e)}")
    
    def get_image_tags_with_source(self, image_id: int) -> List[Dict]:
        """获取图片标签及来源信息（含 level）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT t.name, it.source, t.level
                    FROM image_tags it
                    JOIN tags t ON it.tag_id = t.id
                    WHERE it.image_id = %s
                    ORDER BY t.level ASC, CASE WHEN it.source = 'user' THEN 0 ELSE 1 END, t.name;
                    """, (image_id,))
                    results = cursor.fetchall()
            return [{"name": r[0], "source": r[1], "level": r[2]} for r in results]
        except Exception as e:
            logger.error(f"获取图片标签来源失败: {str(e)}")
            return []
    
    def delete_image(self, image_id: int) -> bool:
        """删除图像（同时更新标签计数）"""
        start_time = time.time()
        logger.info(f"删除图像 ID:{image_id}")
        
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 先减少该图片关联标签的计数
                    cursor.execute("""
                        UPDATE tags SET usage_count = usage_count - 1
                        WHERE id IN (SELECT tag_id FROM image_tags WHERE image_id = %s);
                    """, (image_id,))
                    
                    # 2. 删除图片（image_tags 会通过 ON DELETE CASCADE 自动删除）
                    cursor.execute("""
                        DELETE FROM images
                        WHERE id = %s
                        RETURNING id;
                    """, (image_id,))
                    result = cursor.fetchone()
                conn.commit()
            
            if not result:
                logger.warning(f"未找到 ID 为 {image_id} 的图像记录")
                return False
            
            process_time = time.time() - start_time
            logger.info(f"图像删除完成，耗时: {process_time:.4f}秒")
            
            return True
        except Exception as e:
            logger.error(f"图像删除失败: {str(e)}")
            return False
    
    def get_image(self, image_id: int) -> Optional[Dict]:
        """获取单个图像"""
        start_time = time.time()
        logger.info(f"获取图像 ID:{image_id}")
        
        try:
            # 获取图片基本信息（含 s3_path 和 local_exists）
            query = """
            SELECT id, image_url, description, file_path, original_url, width, height, file_size, s3_path, local_exists
            FROM images
            WHERE id = %s;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (image_id,))
                    result = cursor.fetchone()
                    
                    if not result:
                        logger.warning(f"未找到 ID 为 {image_id} 的图像记录")
                        return None
                    
                    # 从关联表获取标签
                    cursor.execute("""
                    SELECT t.name FROM image_tags it
                    JOIN tags t ON it.tag_id = t.id
                    WHERE it.image_id = %s
                    ORDER BY it.sort_order ASC, it.added_at;
                    """, (image_id,))
                    tags = [row[0] for row in cursor.fetchall()]
            
            # 应用 URL 优先级
            # result: id, image_url, description, file_path, original_url, width, height, file_size, s3_path, local_exists
            display_url = self.get_display_url(result[1], result[8], result[9] if result[9] is not None else True)
            
            image = {
                "id": result[0],
                "image_url": display_url,
                "tags": tags,  # 从关联表获取
                "description": result[2],
                "file_path": result[3],
                "original_url": result[4],
                "width": result[5],
                "height": result[6],
                "file_size": float(result[7]) if result[7] else None
            }
            
            process_time = time.time() - start_time
            logger.info(f"图像获取完成，耗时: {process_time:.4f}秒")
            
            return image
        except Exception as e:
            logger.error(f"图像获取失败: {str(e)}")
            return None
    
    def create_collection(self, name: str, description: str = None, parent_id: int = None) -> Optional[int]:
        """创建收藏夹"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    INSERT INTO collections (name, description, parent_id)
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """, (name, description, parent_id))
                    new_id = cursor.fetchone()[0]
                conn.commit()
            return new_id
        except Exception as e:
            logger.error(f"创建收藏夹失败: {str(e)}")
            return None

    def get_collections(self) -> List[Dict]:
        """获取所有收藏夹"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT c.id, c.name, c.description, c.cover_image_id, c.parent_id, 
                           c.sort_order, c.is_public, c.created_at, c.updated_at,
                           COUNT(ic.image_id) as image_count
                    FROM collections c
                    LEFT JOIN image_collections ic ON c.id = ic.collection_id
                    GROUP BY c.id
                    ORDER BY c.sort_order, c.created_at DESC;
                    """)
                    results = cursor.fetchall()
            
            return [{
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "cover_image_id": row[3],
                "parent_id": row[4],
                "sort_order": row[5],
                "is_public": row[6],
                "created_at": row[7],
                "updated_at": row[8],
                "image_count": row[9]
            } for row in results]
        except Exception as e:
            logger.error(f"获取收藏夹列表失败: {str(e)}")
            return []

    def get_random_image_from_collection(
        self, 
        collection_id: int, 
        tags: Optional[List[str]] = None,
        include_children: bool = False
    ) -> Optional[Dict]:
        """从收藏夹中获取随机图片（使用 image_tags 关联表）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 获取收藏夹 ID 列表（包括子收藏夹）
                    collection_ids = [collection_id]
                    
                    if include_children:
                        cursor.execute("""
                        WITH RECURSIVE sub_collections AS (
                            SELECT id FROM collections WHERE id = %s
                            UNION ALL
                            SELECT c.id FROM collections c
                            INNER JOIN sub_collections sc ON c.parent_id = sc.id
                        )
                        SELECT id FROM sub_collections;
                        """, (collection_id,))
                        collection_ids = [row[0] for row in cursor.fetchall()]
                    
                    # 构建查询
                    if tags:
                        # 使用 image_tags 关联表过滤标签
                        tag_placeholders = ','.join(['%s'] * len(tags))
                        query = f"""
                        SELECT i.id, i.image_url, i.description, 
                               i.file_path, i.original_url
                        FROM images i
                        JOIN image_collections ic ON i.id = ic.image_id
                        WHERE ic.collection_id = ANY(%s)
                          AND i.id IN (
                              SELECT it.image_id FROM image_tags it
                              JOIN tags t ON it.tag_id = t.id
                              WHERE t.name IN ({tag_placeholders})
                          )
                        ORDER BY RANDOM() LIMIT 1;
                        """
                        params = [collection_ids] + list(tags)
                    else:
                        query = """
                        SELECT i.id, i.image_url, i.description, 
                               i.file_path, i.original_url
                        FROM images i
                        JOIN image_collections ic ON i.id = ic.image_id
                        WHERE ic.collection_id = ANY(%s)
                        ORDER BY RANDOM() LIMIT 1;
                        """
                        params = [collection_ids]
                    
                    cursor.execute(query, params)
                    result = cursor.fetchone()
                    
                    if not result:
                        return None
                    
                    # 获取该图片的标签
                    cursor.execute("""
                    SELECT ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                    FROM image_tags it
                    JOIN tags t ON it.tag_id = t.id
                    WHERE it.image_id = %s;
                    """, (result[0],))
                    tags_result = cursor.fetchone()
                    image_tags = tags_result[0] if tags_result and tags_result[0] else []
            
            return {
                "id": result[0],
                "image_url": result[1],
                "tags": image_tags,
                "description": result[2],
                "file_path": result[3],
                "original_url": result[4]
            }
        except Exception as e:
            logger.error(f"获取随机图片失败: {str(e)}")
            return None

    def get_collection(self, collection_id: int) -> Optional[Dict]:
        """获取单个收藏夹详情"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT id, name, description, cover_image_id, parent_id
                    FROM collections
                    WHERE id = %s;
                    """, (collection_id,))
                    result = cursor.fetchone()
            
            if not result:
                return None
                
            return {
                "id": result[0],
                "name": result[1],
                "description": result[2],
                "cover_image_id": result[3],
                "parent_id": result[4]
            }
        except Exception as e:
            logger.error(f"获取收藏夹详情失败: {str(e)}")
            return None

    def update_collection(self, collection_id: int, name: str = None, description: str = None, cover_image_id: int = None) -> bool:
        """更新收藏夹"""
        try:
            updates = []
            params = []
            if name is not None:
                updates.append("name = %s")
                params.append(name)
            if description is not None:
                updates.append("description = %s")
                params.append(description)
            if cover_image_id is not None:
                updates.append("cover_image_id = %s")
                params.append(cover_image_id)
            
            if not updates:
                return True
                
            params.append(collection_id)
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(f"""
                    UPDATE collections 
                    SET {', '.join(updates)}, updated_at = NOW()
                    WHERE id = %s;
                    """, params)
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"更新收藏夹失败: {str(e)}")
            return False

    def delete_collection(self, collection_id: int) -> bool:
        """删除收藏夹"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM collections WHERE id = %s;", (collection_id,))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"删除收藏夹失败: {str(e)}")
            return False

    def add_image_to_collection(self, collection_id: int, image_id: int) -> bool:
        """添加图片到收藏夹"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    INSERT INTO image_collections (collection_id, image_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING;
                    """, (collection_id, image_id))
                    
                    # 如果收藏夹没有封面，自动设置第一张图为封面
                    cursor.execute("""
                    UPDATE collections 
                    SET cover_image_id = %s 
                    WHERE id = %s AND cover_image_id IS NULL;
                    """, (image_id, collection_id))
                    
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"添加图片到收藏夹失败: {str(e)}")
            return False

    def remove_image_from_collection(self, collection_id: int, image_id: int) -> bool:
        """从收藏夹移除图片"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    DELETE FROM image_collections 
                    WHERE collection_id = %s AND image_id = %s;
                    """, (collection_id, image_id))
                    
                    # 如果移除的是封面，尝试设置其他图片为封面
                    cursor.execute("""
                    UPDATE collections
                    SET cover_image_id = (
                        SELECT image_id FROM image_collections 
                        WHERE collection_id = %s 
                        LIMIT 1
                    )
                    WHERE id = %s AND cover_image_id = %s;
                    """, (collection_id, collection_id, image_id))
                    
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"从收藏夹移除图片失败: {str(e)}")
            return False

    def get_collection_images(self, collection_id: int, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
        """获取收藏夹内的图片（使用 image_tags 关联表）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 获取图片列表
                    cursor.execute("""
                    SELECT i.id, i.image_url, i.description, i.file_path, i.original_url
                    FROM images i
                    JOIN image_collections ic ON i.id = ic.image_id
                    WHERE ic.collection_id = %s
                    ORDER BY ic.added_at DESC
                    LIMIT %s OFFSET %s;
                    """, (collection_id, limit, offset))
                    results = cursor.fetchall()
                    
                    # 批量获取标签
                    image_ids = [row[0] for row in results]
                    tags_map = {}
                    if image_ids:
                        cursor.execute("""
                        SELECT it.image_id, ARRAY_AGG(t.name ORDER BY it.sort_order ASC, it.added_at)
                        FROM image_tags it
                        JOIN tags t ON it.tag_id = t.id
                        WHERE it.image_id = ANY(%s)
                        GROUP BY it.image_id;
                        """, (image_ids,))
                        for row in cursor.fetchall():
                            tags_map[row[0]] = row[1]
                    
                    # 获取总数
                    cursor.execute("""
                    SELECT COUNT(*) FROM image_collections WHERE collection_id = %s;
                    """, (collection_id,))
                    total = cursor.fetchone()[0]
            
            images = [{
                "id": row[0],
                "image_url": row[1],
                "tags": tags_map.get(row[0], []),
                "description": row[2],
                "file_path": row[3],
                "original_url": row[4]
            } for row in results]
            
            return {
                "images": images,
                "total": total,
                "limit": limit,
                "offset": offset
            }
        except Exception as e:
            logger.error(f"获取收藏夹图片失败: {str(e)}")
            return {"images": [], "total": 0}

    def create_task(self, task_id: str, task_type: str, payload: Dict[str, Any]) -> str:
        """创建任务"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tasks (id, type, status, payload)
                        VALUES (%s, %s, 'pending', %s)
                        RETURNING id
                        """,
                        (task_id, task_type, Json(payload))
                    )
                    return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"创建任务失败: {str(e)}")
            raise

    def update_task_status(
        self, 
        task_id: str, 
        status: str, 
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> bool:
        """更新任务状态"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    updates = ["status = %s", "updated_at = NOW()"]
                    params = [status]
                    
                    if result is not None:
                        updates.append("result = %s")
                        params.append(Json(result))
                    
                    if error is not None:
                        updates.append("error = %s")
                        params.append(error)
                    
                    if status in ['completed', 'failed']:
                        updates.append("completed_at = NOW()")
                    
                    params.append(task_id)
                    
                    query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = %s"
                    cur.execute(query, params)
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"更新任务状态失败: {str(e)}")
            return False

    def get_tasks(self, limit: int = 50, offset: int = 0, status: Optional[str] = None) -> Dict[str, Any]:
        """获取任务列表"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    query = "SELECT * FROM tasks"
                    params = []
                    
                    if status:
                        query += " WHERE status = %s"
                        params.append(status)
                    
                    # 获取总数
                    count_query = f"SELECT COUNT(*) FROM ({query}) as t"
                    cur.execute(count_query, params)
                    total = cur.fetchone()['count']
                    
                    # 获取列表
                    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                    params.extend([limit, offset])
                    
                    cur.execute(query, params)
                    tasks = cur.fetchall()
                    
                    return {
                        "tasks": tasks,
                        "total": total,
                        "limit": limit,
                        "offset": offset
                    }
        except Exception as e:
            logger.error(f"获取任务列表失败: {str(e)}")
            return {"tasks": [], "total": 0}

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT * FROM tasks WHERE id = %s",
                        (task_id,)
                    )
                    return cur.fetchone()
        except Exception as e:
            logger.error(f"获取任务详情失败: {str(e)}")
            return None

    def cleanup_old_tasks(self, days: int = 7) -> int:
        """清理旧任务"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM tasks 
                        WHERE created_at < NOW() - INTERVAL '%s days'
                        AND status IN ('completed', 'failed')
                        """,
                        (days,)
                    )
                    return cur.rowcount
        except Exception as e:
            logger.error(f"清理旧任务失败: {str(e)}")
            return 0

    # ========== 用户管理 ==========
    
    def create_user(self, username: str, password_hash: str, email: str = None, role: str = "user") -> Optional[int]:
        """创建用户"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO users (username, password_hash, email, role)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id;
                    """, (username, password_hash, email, role))
                    new_id = cur.fetchone()[0]
                conn.commit()
                return new_id
        except Exception as e:
            logger.error(f"创建用户失败: {str(e)}")
            return None
    
    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """根据用户名获取用户"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                    return cur.fetchone()
        except Exception as e:
            logger.error(f"获取用户失败: {str(e)}")
            return None
    
    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        """根据 ID 获取用户"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                    return cur.fetchone()
        except Exception as e:
            logger.error(f"获取用户失败: {str(e)}")
            return None
    
    def update_user_last_login(self, user_id: int) -> bool:
        """更新用户最后登录时间"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET last_login_at = NOW() WHERE id = %s",
                        (user_id,)
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新登录时间失败: {str(e)}")
            return False
    
    def get_all_users(self) -> List[Dict]:
        """获取所有用户列表"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("""
                        SELECT id, username, email, role, is_active, created_at, last_login_at
                        FROM users ORDER BY created_at DESC
                    """)
                    return cur.fetchall()
        except Exception as e:
            logger.error(f"获取用户列表失败: {str(e)}")
            return []
    
    def update_user(self, user_id: int, is_active: bool = None, role: str = None) -> bool:
        """更新用户信息"""
        try:
            updates = []
            params = []
            if is_active is not None:
                updates.append("is_active = %s")
                params.append(is_active)
            if role is not None:
                updates.append("role = %s")
                params.append(role)
            
            if not updates:
                return True
            
            params.append(user_id)
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        UPDATE users SET {', '.join(updates)} WHERE id = %s
                    """, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新用户失败: {str(e)}")
            return False
    
    def delete_user(self, user_id: int) -> bool:
        """删除用户"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"删除用户失败: {str(e)}")
            return False
    
    # ========== 用户 API 密钥管理 ==========
    
    def generate_user_api_key(self, user_id: int) -> Optional[str]:
        """生成并保存新的用户 API 密钥"""
        try:
            import secrets
            # 生成 32 字节的随机密钥，编码为 64 字符的十六进制字符串
            api_key = secrets.token_hex(32)
            
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET api_key = %s WHERE id = %s",
                        (api_key, user_id)
                    )
                conn.commit()
            
            logger.info(f"已为用户 {user_id} 生成新的 API 密钥")
            return api_key
        except Exception as e:
            logger.error(f"生成 API 密钥失败: {str(e)}")
            return None
    
    def get_user_api_key(self, user_id: int) -> Optional[str]:
        """获取用户的 API 密钥"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT api_key FROM users WHERE id = %s", (user_id,))
                    result = cur.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"获取 API 密钥失败: {str(e)}")
            return None
    
    def get_user_by_api_key(self, api_key: str) -> Optional[Dict]:
        """根据 API 密钥获取用户"""
        if not api_key:
            return None
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT id, username, email, role, is_active FROM users WHERE api_key = %s AND is_active = TRUE",
                        (api_key,)
                    )
                    return cur.fetchone()
        except Exception as e:
            logger.error(f"根据 API 密钥获取用户失败: {str(e)}")
            return None
    
    def delete_user_api_key(self, user_id: int) -> bool:
        """删除用户的 API 密钥"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET api_key = NULL WHERE id = %s",
                        (user_id,)
                    )
                conn.commit()
            logger.info(f"已删除用户 {user_id} 的 API 密钥")
            return True
        except Exception as e:
            logger.error(f"删除 API 密钥失败: {str(e)}")
            return False
    
    def change_user_password(self, user_id: int, new_password: str) -> bool:
        """修改用户密码"""
        try:
            import secrets
            import hashlib
            
            salt = secrets.token_hex(16)
            pw_hash = hashlib.pbkdf2_hmac(
                'sha256', 
                new_password.encode('utf-8'), 
                salt.encode('utf-8'), 
                100000
            )
            password_hash = f"{salt}${pw_hash.hex()}"
            
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE users SET password_hash = %s WHERE id = %s",
                        (password_hash, user_id)
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"修改密码失败: {str(e)}")
            return False
    
    # ========== 重复检测 ==========
    
    def update_image_hash(self, image_id: int, file_hash: str) -> bool:
        """更新图片的文件哈希"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE images SET file_hash = %s WHERE id = %s",
                        (file_hash, image_id)
                    )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新图片哈希失败: {str(e)}")
            return False
    
    # ========== 分辨率管理 ==========
    
    def count_images_without_resolution(self) -> int:
        """统计缺少分辨率的图片数量"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM images WHERE width IS NULL")
                    return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"统计缺失分辨率图片失败: {str(e)}")
            return 0
    
    def get_images_without_resolution(self, limit: int = 100) -> List[Dict]:
        """获取缺少分辨率的图片列表"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("""
                        SELECT id, image_url, file_path 
                        FROM images 
                        WHERE width IS NULL 
                        ORDER BY id 
                        LIMIT %s
                    """, (limit,))
                    return list(cur.fetchall())
        except Exception as e:
            logger.error(f"获取缺失分辨率图片失败: {str(e)}")
            return []
    
    def update_image_resolution(self, image_id: int, width: int, height: int) -> bool:
        """更新图片的分辨率"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE images SET width = %s, height = %s WHERE id = %s",
                        (width, height, image_id)
                    )
                conn.commit()
                logger.debug(f"更新图片 {image_id} 分辨率: {width}x{height}")
                return True
        except Exception as e:
            logger.error(f"更新图片分辨率失败: {str(e)}")
            return False
    
    def find_image_by_hash(self, file_hash: str) -> Optional[Dict]:
        """根据哈希查找图片"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        "SELECT id, image_url, description FROM images WHERE file_hash = %s LIMIT 1",
                        (file_hash,)
                    )
                    return cur.fetchone()
        except Exception as e:
            logger.error(f"查找图片哈希失败: {str(e)}")
            return None
    
    def find_duplicate_images(self) -> List[Dict]:
        """查找重复的图片（按 file_hash 分组）"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    # 查找有重复 hash 的图片
                    cur.execute("""
                        SELECT file_hash, COUNT(*) as count
                        FROM images 
                        WHERE file_hash IS NOT NULL AND file_hash != ''
                        GROUP BY file_hash
                        HAVING COUNT(*) > 1
                        ORDER BY count DESC
                    """)
                    duplicate_hashes = cur.fetchall()
                    
                    result = []
                    for item in duplicate_hashes:
                        # 获取每组重复的详细信息
                        cur.execute("""
                            SELECT id, image_url, description, created_at
                            FROM images
                            WHERE file_hash = %s
                            ORDER BY created_at ASC
                        """, (item['file_hash'],))
                        images = cur.fetchall()
                        
                        result.append({
                            'file_hash': item['file_hash'],
                            'count': item['count'],
                            'images': [dict(img) for img in images]
                        })
                    
                    return result
        except Exception as e:
            logger.error(f"查找重复图片失败: {str(e)}")
            return []
    
    def get_images_without_hash(self, limit: int = 100) -> List[Dict]:
        """获取没有哈希的图片（用于批量计算）"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("""
                        SELECT id, image_url, file_path
                        FROM images
                        WHERE file_hash IS NULL OR file_hash = ''
                        ORDER BY id
                        LIMIT %s
                    """, (limit,))
                    return cur.fetchall()
        except Exception as e:
            logger.error(f"获取无哈希图片失败: {str(e)}")
            return []
    
    def count_images_without_hash(self) -> int:
        """统计没有哈希的图片数量"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COUNT(*) FROM images
                        WHERE file_hash IS NULL OR file_hash = ''
                    """)
                    return cur.fetchone()[0]
        except Exception as e:
            logger.error(f"统计无哈希图片失败: {str(e)}")
            return 0
    
    # ========== 数据导出导入 ==========
    
    def export_all_images(self) -> List[Dict]:
        """导出所有图片数据（不含向量）"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("""
                        SELECT 
                            i.id,
                            i.image_url,
                            i.description,
                            i.original_url,
                            i.file_path,
                            i.created_at,
                            i.updated_at,
                            ARRAY(
                                SELECT t.name FROM tags t
                                JOIN image_tags it ON t.id = it.tag_id
                                WHERE it.image_id = i.id
                            ) as tags
                        FROM images i
                        ORDER BY i.id
                    """)
                    results = cur.fetchall()
                    # 转换 datetime 为字符串
                    images = []
                    for row in results:
                        img = dict(row)
                        if img.get('created_at'):
                            img['created_at'] = img['created_at'].isoformat()
                        if img.get('updated_at'):
                            img['updated_at'] = img['updated_at'].isoformat()
                        images.append(img)
                    return images
        except Exception as e:
            logger.error(f"导出图片失败: {str(e)}")
            return []
    
    def export_all_tags(self) -> List[Dict]:
        """导出所有标签"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT id, name FROM tags ORDER BY id")
                    return cur.fetchall()
        except Exception as e:
            logger.error(f"导出标签失败: {str(e)}")
            return []
    
    def export_all_collections(self) -> List[Dict]:
        """导出所有收藏夹（含关联图片）"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("""
                        SELECT 
                            c.id,
                            c.name,
                            c.description,
                            c.is_public,
                            c.user_id,
                            c.parent_id,
                            c.created_at,
                            ARRAY(
                                SELECT ic.image_id FROM image_collections ic
                                WHERE ic.collection_id = c.id
                            ) as image_ids
                        FROM collections c
                        ORDER BY c.id
                    """)
                    results = cur.fetchall()
                    collections = []
                    for row in results:
                        col = dict(row)
                        if col.get('created_at'):
                            col['created_at'] = col['created_at'].isoformat()
                        collections.append(col)
                    return collections
        except Exception as e:
            logger.error(f"导出收藏夹失败: {str(e)}")
            return []
    
    def export_all_users(self) -> List[Dict]:
        """导出所有用户（不含密码）"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("""
                        SELECT id, username, email, role, is_active, created_at
                        FROM users ORDER BY id
                    """)
                    results = cur.fetchall()
                    users = []
                    for row in results:
                        user = dict(row)
                        if user.get('created_at'):
                            user['created_at'] = user['created_at'].isoformat()
                        users.append(user)
                    return users
        except Exception as e:
            logger.error(f"导出用户失败: {str(e)}")
            return []
    
    def import_image(self, img_data: Dict) -> bool:
        """导入单张图片"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # 插入图片（embedding 为 NULL，待后续生成）
                    cur.execute("""
                        INSERT INTO images (image_url, description, embedding, original_url, file_path)
                        VALUES (%s, %s, NULL, %s, %s)
                        ON CONFLICT (image_url) DO UPDATE SET
                            description = EXCLUDED.description,
                            original_url = EXCLUDED.original_url,
                            file_path = EXCLUDED.file_path
                        RETURNING id
                    """, (
                        img_data.get('image_url'),
                        img_data.get('description', ''),
                        img_data.get('original_url'),
                        img_data.get('file_path')
                    ))
                    image_id = cur.fetchone()[0]
                    
                    # 导入标签关联
                    tags = img_data.get('tags', [])
                    for tag_name in tags:
                        # 确保标签存在（导入标签 level=2）
                        cur.execute("""
                            INSERT INTO tags (name, level) VALUES (%s, 2)
                            ON CONFLICT (name) DO NOTHING
                        """, (tag_name,))
                        cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
                        tag_id = cur.fetchone()[0]
                        cur.execute("""
                            INSERT INTO image_tags (image_id, tag_id, source)
                            VALUES (%s, %s, 'import')
                            ON CONFLICT DO NOTHING
                        """, (image_id, tag_id))
                    
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"导入图片失败: {str(e)}")
            return False
    
    def import_tag(self, tag_data: Dict) -> bool:
        """导入标签"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # 导入标签 level=2
                    cur.execute("""
                        INSERT INTO tags (name, level) VALUES (%s, 2)
                        ON CONFLICT (name) DO NOTHING
                    """, (tag_data.get('name'),))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"导入标签失败: {str(e)}")
            return False
    
    def import_collection(self, col_data: Dict) -> bool:
        """导入收藏夹"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    # 插入收藏夹
                    cur.execute("""
                        INSERT INTO collections (name, description, is_public, user_id, parent_id)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING id
                    """, (
                        col_data.get('name'),
                        col_data.get('description', ''),
                        col_data.get('is_public', True),
                        col_data.get('user_id'),
                        col_data.get('parent_id')
                    ))
                    result = cur.fetchone()
                    if result:
                        collection_id = result[0]
                        # 关联图片
                        for image_id in col_data.get('image_ids', []):
                            cur.execute("""
                                INSERT INTO image_collections (collection_id, image_id)
                                VALUES (%s, %s)
                                ON CONFLICT DO NOTHING
                            """, (collection_id, image_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"导入收藏夹失败: {str(e)}")
            return False
    
    # ========== 审批管理 ==========
    
    def create_approval(
        self,
        type: str,
        requester_id: int,
        payload: Dict,
        target_type: str = None,
        target_ids: List[int] = None
    ) -> Optional[int]:
        """创建审批请求"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO approvals (type, requester_id, target_type, target_ids, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id;
                    """, (type, requester_id, target_type, target_ids, Json(payload)))
                    new_id = cur.fetchone()[0]
                conn.commit()
                return new_id
        except Exception as e:
            logger.error(f"创建审批请求失败: {str(e)}")
            return None
    
    def get_pending_approvals(self, limit: int = 50, offset: int = 0) -> Dict:
        """获取待审批列表"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    # 获取总数
                    cur.execute("SELECT COUNT(*) FROM approvals WHERE status = 'pending'")
                    total = cur.fetchone()["count"]
                    
                    # 获取列表
                    cur.execute("""
                    SELECT a.*, u.username as requester_name
                    FROM approvals a
                    LEFT JOIN users u ON a.requester_id = u.id
                    WHERE a.status = 'pending'
                    ORDER BY a.created_at DESC
                    LIMIT %s OFFSET %s
                    """, (limit, offset))
                    approvals = cur.fetchall()
                    
                    return {
                        "approvals": [dict(a) for a in approvals],
                        "total": total,
                        "limit": limit,
                        "offset": offset
                    }
        except Exception as e:
            logger.error(f"获取待审批列表失败: {str(e)}")
            return {"approvals": [], "total": 0}
    
    def approve_request(self, approval_id: int, reviewer_id: int, comment: str = None) -> bool:
        """批准审批请求"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    UPDATE approvals 
                    SET status = 'approved', reviewer_id = %s, review_comment = %s, reviewed_at = NOW()
                    WHERE id = %s AND status = 'pending'
                    """, (reviewer_id, comment, approval_id))
                    success = cur.rowcount > 0
                conn.commit()
                return success
        except Exception as e:
            logger.error(f"批准请求失败: {str(e)}")
            return False
    
    def reject_request(self, approval_id: int, reviewer_id: int, comment: str = None) -> bool:
        """拒绝审批请求"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    UPDATE approvals 
                    SET status = 'rejected', reviewer_id = %s, review_comment = %s, reviewed_at = NOW()
                    WHERE id = %s AND status = 'pending'
                    """, (reviewer_id, comment, approval_id))
                    success = cur.rowcount > 0
                conn.commit()
                return success
        except Exception as e:
            logger.error(f"拒绝请求失败: {str(e)}")
            return False
    
    def get_approval(self, approval_id: int) -> Optional[Dict]:
        """获取审批详情"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute("SELECT * FROM approvals WHERE id = %s", (approval_id,))
                    return cur.fetchone()
        except Exception as e:
            logger.error(f"获取审批详情失败: {str(e)}")
            return None
    
    # ========== 审计日志 ==========
    
    def add_audit_log(
        self,
        user_id: int,
        action: str,
        target_type: str = None,
        target_id: int = None,
        old_value: Dict = None,
        new_value: Dict = None,
        ip_address: str = None
    ) -> Optional[int]:
        """添加审计日志"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    INSERT INTO audit_logs (user_id, action, target_type, target_id, old_value, new_value, ip_address)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """, (
                        user_id, action, target_type, target_id,
                        Json(old_value) if old_value else None,
                        Json(new_value) if new_value else None,
                        ip_address
                    ))
                    new_id = cur.fetchone()[0]
                conn.commit()
                return new_id
        except Exception as e:
            logger.error(f"添加审计日志失败: {str(e)}")
            return None
    
    def get_audit_logs(self, limit: int = 50, offset: int = 0, user_id: int = None) -> Dict:
        """获取审计日志"""
        try:
            with self._get_connection() as conn:
                from psycopg.rows import dict_row
                with conn.cursor(row_factory=dict_row) as cur:
                    where_clause = ""
                    params = []
                    
                    if user_id:
                        where_clause = "WHERE user_id = %s"
                        params.append(user_id)
                    
                    # 获取总数
                    cur.execute(f"SELECT COUNT(*) FROM audit_logs {where_clause}", params)
                    total = cur.fetchone()["count"]
                    
                    # 获取列表
                    params.extend([limit, offset])
                    cur.execute(f"""
                    SELECT a.*, u.username
                    FROM audit_logs a
                    LEFT JOIN users u ON a.user_id = u.id
                    {where_clause}
                    ORDER BY a.created_at DESC
                    LIMIT %s OFFSET %s
                    """, params)
                    logs = cur.fetchall()
                    
                    return {
                        "logs": [dict(l) for l in logs],
                        "total": total,
                        "limit": limit,
                        "offset": offset
                    }
        except Exception as e:
            logger.error(f"获取审计日志失败: {str(e)}")
            return {"logs": [], "total": 0}

    # ============= 标签层级管理 =============
    
    def get_main_categories(self) -> List[Dict]:
        """获取主分类标签（level=0）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT id, name, description, sort_order, 
                           (SELECT COUNT(*) FROM image_tags WHERE tag_id = tags.id) as usage_count
                    FROM tags 
                    WHERE level = 0 
                    ORDER BY sort_order ASC, id ASC;
                    """)
                    results = cursor.fetchall()
                    return [
                        {
                            "id": row[0],
                            "name": row[1],
                            "description": row[2],
                            "sort_order": row[3],
                            "usage_count": row[4]
                        }
                        for row in results
                    ]
        except Exception as e:
            logger.error(f"获取主分类失败: {str(e)}")
            return []
    
    def get_resolution_tags(self) -> List[Dict]:
        """获取分辨率标签（level=1）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT id, name, description, sort_order
                    FROM tags 
                    WHERE level = 1 
                    ORDER BY sort_order ASC, id ASC;
                    """)
                    results = cursor.fetchall()
                    return [
                        {
                            "id": row[0],
                            "name": row[1],
                            "description": row[2],
                            "sort_order": row[3]
                        }
                        for row in results
                    ]
        except Exception as e:
            logger.error(f"获取分辨率标签失败: {str(e)}")
            return []
    
    def create_main_category(self, name: str, description: str = None, sort_order: int = 0) -> Optional[int]:
        """创建主分类标签（仅管理员）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 检查是否已存在
                    cursor.execute("SELECT id FROM tags WHERE name = %s", (name,))
                    if cursor.fetchone():
                        logger.warning(f"标签 '{name}' 已存在")
                        return None
                    
                    # 获取最大 level=0 的 ID（保持在 1-99 范围）
                    cursor.execute("SELECT COALESCE(MAX(id), 0) FROM tags WHERE level = 0")
                    max_id = cursor.fetchone()[0]
                    new_id = max_id + 1 if max_id < 99 else None
                    
                    if new_id is None:
                        logger.error("主分类 ID 已用尽（最多 99 个）")
                        return None
                    
                    cursor.execute("""
                    INSERT INTO tags (id, name, level, source, description, sort_order)
                    VALUES (%s, %s, 0, 'system', %s, %s)
                    RETURNING id;
                    """, (new_id, name, description, sort_order))
                    result = cursor.fetchone()
                conn.commit()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"创建主分类失败: {str(e)}")
            return None
    
    def delete_main_category(self, tag_id: int) -> Tuple[bool, str]:
        """删除主分类标签
        
        Returns:
            Tuple[bool, str]: (成功与否, 消息)
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 检查是否是主分类
                    cursor.execute("SELECT level FROM tags WHERE id = %s", (tag_id,))
                    result = cursor.fetchone()
                    if not result:
                        return False, "标签不存在"
                    if result[0] != 0:
                        return False, "只能删除主分类标签"
                    
                    # 检查是否被使用
                    cursor.execute("SELECT COUNT(*) FROM image_tags WHERE tag_id = %s", (tag_id,))
                    usage_count = cursor.fetchone()[0]
                    if usage_count > 0:
                        return False, f"该分类已被 {usage_count} 张图片使用，无法删除"
                    
                    # 删除
                    cursor.execute("DELETE FROM tags WHERE id = %s", (tag_id,))
                conn.commit()
                return True, "删除成功"
        except Exception as e:
            logger.error(f"删除主分类失败: {str(e)}")
            return False, str(e)
    
    def can_create_user_tag(self, name: str) -> Tuple[bool, str]:
        """检查是否可以创建用户标签（不能与 level 0/1 同名）
        
        Returns:
            Tuple[bool, str]: (可以创建, 原因)
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT level FROM tags WHERE name = %s AND level IN (0, 1)
                    """, (name,))
                    result = cursor.fetchone()
                    if result:
                        level_name = "主分类" if result[0] == 0 else "分辨率"
                        return False, f"'{name}' 是系统{level_name}标签，不允许创建"
                    return True, ""
        except Exception as e:
            logger.error(f"检查标签名称失败: {str(e)}")
            return False, str(e)
    
    def get_category_by_name(self, name: str) -> Optional[Dict]:
        """根据名称获取主分类信息"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT id, name, description, sort_order
                    FROM tags WHERE name = %s AND level = 0
                    """, (name,))
                    result = cursor.fetchone()
                    if result:
                        return {
                            "id": result[0],
                            "name": result[1],
                            "description": result[2],
                            "sort_order": result[3]
                        }
                    return None
        except Exception as e:
            logger.error(f"获取分类失败: {str(e)}")
            return None
    
    def get_resolution_tag_by_level(self, resolution_level: str) -> Optional[int]:
        """根据分辨率等级获取对应的 tag_id"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT id FROM tags WHERE name = %s AND level = 1
                    """, (resolution_level,))
                    result = cursor.fetchone()
                    return result[0] if result else None
        except Exception as e:
            logger.error(f"获取分辨率标签失败: {str(e)}")
            return None
    
    def get_resolution_level_for_dimensions(self, width: int, height: int) -> str:
        """根据图片尺寸计算分辨率等级
        
        Resolution levels:
        - 8K: ≥7680px (max dimension)
        - 4K: ≥3840px
        - 2K: ≥2560px
        - 1080p: ≥1920px
        - 720p: ≥1280px
        - SD: <1280px
        """
        max_dim = max(width or 0, height or 0)
        if max_dim >= 7680:
            return "8K"
        elif max_dim >= 3840:
            return "4K"
        elif max_dim >= 2560:
            return "2K"
        elif max_dim >= 1920:
            return "1080p"
        elif max_dim >= 1280:
            return "720p"
        else:
            return "SD"
    
    def auto_assign_system_tags(self, image_id: int, width: int = None, height: int = None, category_id: int = None):
        """自动为图片分配系统标签（level 0 分类 + level 1 分辨率）
        
        - Level 0: 用户指定 category_id，否则默认 "待分类" (ID=10)
        - Level 1: 根据分辨率自动计算
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 分配 level 0 分类标签
                    # 使用用户指定的 category_id，否则用默认 ID=10 (待分类)
                    final_category_id = category_id if category_id else 10
                    
                    # 验证 category_id 是否为有效的 level=0 标签
                    if category_id:
                        cursor.execute("SELECT level FROM tags WHERE id = %s", (category_id,))
                        result = cursor.fetchone()
                        if not result or result[0] != 0:
                            logger.warning(f"无效的分类 ID {category_id}，使用默认值 10")
                            final_category_id = 10
                    
                    cursor.execute("""
                    INSERT INTO image_tags (image_id, tag_id, source)
                    VALUES (%s, %s, 'system')
                    ON CONFLICT (image_id, tag_id) DO NOTHING;
                    """, (image_id, final_category_id))
                    
                    # 2. 根据分辨率分配 level 1 标签
                    if width and height:
                        resolution_level = self.get_resolution_level_for_dimensions(width, height)
                        # 获取对应的 tag_id
                        cursor.execute("""
                        SELECT id FROM tags WHERE name = %s AND level = 1
                        """, (resolution_level,))
                        result = cursor.fetchone()
                        if result:
                            cursor.execute("""
                            INSERT INTO image_tags (image_id, tag_id, source)
                            VALUES (%s, %s, 'system')
                            ON CONFLICT (image_id, tag_id) DO NOTHING;
                            """, (image_id, result[0]))
                            logger.debug(f"图片 {image_id} 自动分配分辨率标签: {resolution_level}")
                
                conn.commit()
                logger.debug(f"图片 {image_id} 自动分配系统标签完成 (category_id={final_category_id})")
        except Exception as e:
            logger.error(f"自动分配系统标签失败: {str(e)}")
    
    def get_category_by_id(self, tag_id: int) -> Optional[Dict]:
        """根据 ID 获取标签信息"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT id, name, level, description, sort_order
                    FROM tags WHERE id = %s
                    """, (tag_id,))
                    result = cursor.fetchone()
                    if result:
                        return {
                            "id": result[0],
                            "name": result[1],
                            "level": result[2],
                            "description": result[3],
                            "sort_order": result[4]
                        }
                    return None
        except Exception as e:
            logger.error(f"获取标签失败: {str(e)}")
            return None
    
    def set_image_category(self, image_id: int, category_id: int) -> bool:
        """设置图片的主分类（level=0）
        
        会先删除图片现有的 level=0 标签，再添加新的分类标签。
        
        Args:
            image_id: 图片 ID
            category_id: 目标主分类 tag_id
            
        Returns:
            bool: 是否成功
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 删除现有的 level=0 标签
                    cursor.execute("""
                    DELETE FROM image_tags
                    WHERE image_id = %s AND tag_id IN (
                        SELECT id FROM tags WHERE level = 0
                    );
                    """, (image_id,))
                    
                    # 2. 添加新的主分类标签
                    cursor.execute("""
                    INSERT INTO image_tags (image_id, tag_id, source)
                    VALUES (%s, %s, 'user')
                    ON CONFLICT (image_id, tag_id) DO NOTHING;
                    """, (image_id, category_id))
                
                conn.commit()
                logger.debug(f"图片 {image_id} 主分类设置为 {category_id}")
                return True
        except Exception as e:
            logger.error(f"设置图片分类失败: {str(e)}")
            return False
    
    # ==================== URL 优先级方法 ====================
    
    def get_display_url(self, image_url: str, s3_path: str, local_exists: bool) -> str:
        """
        获取显示 URL（优先级可配置：auto / local / cdn）
        
        Args:
            image_url: 本地 URL
            s3_path: S3 对象键
            local_exists: 本地文件是否存在
            
        Returns:
            str: 最终显示 URL
        """
        from imgtag.db.config_db import config_db
        
        priority = config_db.get("image_url_priority", "auto")
        s3_enabled = config_db.get("s3_enabled", "false").lower() == "true"
        
        # 自动模式：根据 S3 启用状态决定
        if priority == "auto":
            priority = "cdn" if (s3_enabled and s3_path) else "local"
        
        # 构建 CDN/S3 URL
        def build_cdn_url():
            if not s3_path:
                return None
            public_prefix = config_db.get("s3_public_url_prefix", "").rstrip("/")
            if public_prefix:
                return f"{public_prefix}/{s3_path}"
            # 无自定义前缀时，构建默认 S3 URL
            endpoint = config_db.get("s3_endpoint_url", "").rstrip("/")
            bucket = config_db.get("s3_bucket_name", "")
            if endpoint and bucket:
                return f"{endpoint}/{bucket}/{s3_path}"
            return None
        
        if priority == "cdn":
            # CDN 优先：有 S3 路径就用 CDN URL
            cdn_url = build_cdn_url()
            if cdn_url:
                return cdn_url
            # 降级到本地
            return image_url or ""
        else:
            # 本地优先
            if local_exists and image_url:
                return image_url
            # 本地不存在，尝试 CDN
            cdn_url = build_cdn_url()
            if cdn_url:
                return cdn_url
            return image_url or ""
    
    # ==================== 存储管理方法 ====================
    
    def get_storage_status(self) -> Dict[str, Any]:
        """
        获取存储状态统计
        
        Returns:
            dict: {total, local_only, s3_only, both, pending_sync}
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE local_exists = true AND (s3_path IS NULL OR s3_path = '')) as local_only,
                        COUNT(*) FILTER (WHERE local_exists = false AND s3_path IS NOT NULL AND s3_path != '') as s3_only,
                        COUNT(*) FILTER (WHERE local_exists = true AND s3_path IS NOT NULL AND s3_path != '') as both
                    FROM images;
                    """)
                    row = cursor.fetchone()
                    return {
                        "total": row[0],
                        "local_only": row[1],
                        "s3_only": row[2],
                        "both": row[3],
                        "pending_sync": row[1]  # 待同步 = 仅本地
                    }
        except Exception as e:
            logger.error(f"获取存储状态失败: {str(e)}")
            return {"total": 0, "local_only": 0, "s3_only": 0, "both": 0, "pending_sync": 0}
    
    def get_storage_files(
        self,
        filter_type: str = "all",
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        获取文件存储状态列表
        
        Args:
            filter_type: all/local_only/s3_only/both
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            dict: {files, total, limit, offset}
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 构建过滤条件
                    filter_conditions = {
                        "all": "1=1",
                        "local_only": "local_exists = true AND (s3_path IS NULL OR s3_path = '')",
                        "s3_only": "local_exists = false AND s3_path IS NOT NULL AND s3_path != ''",
                        "both": "local_exists = true AND s3_path IS NOT NULL AND s3_path != ''"
                    }
                    condition = filter_conditions.get(filter_type, "1=1")
                    
                    # 获取总数
                    cursor.execute(f"SELECT COUNT(*) FROM images WHERE {condition}")
                    total = cursor.fetchone()[0]
                    
                    # 获取文件列表
                    cursor.execute(f"""
                    SELECT id, image_url, s3_path, local_exists, storage_type, created_at
                    FROM images
                    WHERE {condition}
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s;
                    """, (limit, offset))
                    
                    files = []
                    for row in cursor.fetchall():
                        # 从 image_url 提取文件名
                        image_url = row[1] or ""
                        filename = image_url.split("/")[-1] if image_url else ""
                        
                        files.append({
                            "id": row[0],
                            "filename": filename,
                            "image_url": row[1],
                            "s3_path": row[2],
                            "local_exists": row[3],
                            "storage_type": row[4],
                            "created_at": row[5].isoformat() if row[5] else None
                        })
                    
                    return {
                        "files": files,
                        "total": total,
                        "limit": limit,
                        "offset": offset
                    }
        except Exception as e:
            logger.error(f"获取存储文件列表失败: {str(e)}")
            return {"files": [], "total": 0, "limit": limit, "offset": offset}
    
    def update_storage_info(
        self,
        image_id: int,
        s3_path: str = None,
        local_exists: bool = None,
        storage_type: str = None
    ) -> bool:
        """
        更新图片存储信息
        
        Args:
            image_id: 图片 ID
            s3_path: S3 对象键
            local_exists: 本地文件是否存在
            storage_type: 存储类型 (local/s3/both)
            
        Returns:
            bool: 是否成功
        """
        try:
            updates = []
            params = []
            
            if s3_path is not None:
                updates.append("s3_path = %s")
                params.append(s3_path)
            if local_exists is not None:
                updates.append("local_exists = %s")
                params.append(local_exists)
            if storage_type is not None:
                updates.append("storage_type = %s")
                params.append(storage_type)
            
            if not updates:
                return True
            
            params.append(image_id)
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(f"""
                    UPDATE images
                    SET {", ".join(updates)}
                    WHERE id = %s;
                    """, params)
                conn.commit()
                logger.debug(f"图片 {image_id} 存储信息已更新")
                return True
        except Exception as e:
            logger.error(f"更新存储信息失败: {str(e)}")
            return False
    
    def get_local_file_path(self, image_id: int) -> Optional[str]:
        """
        获取图片的本地文件路径
        
        Args:
            image_id: 图片 ID
            
        Returns:
            str: 本地文件完整路径，不存在返回 None
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT image_url, local_exists
                    FROM images WHERE id = %s;
                    """, (image_id,))
                    row = cursor.fetchone()
                    
                    if not row or not row[1]:  # local_exists is False
                        return None
                    
                    image_url = row[0]
                    # 从 URL 提取相对路径并拼接本地 uploads 目录
                    if "/uploads/" in image_url:
                        relative_path = image_url.split("/uploads/")[-1]
                        from imgtag.core.config import settings
                        return str(settings.get_upload_path() / relative_path)
                    return None
        except Exception as e:
            logger.error(f"获取本地文件路径失败: {str(e)}")
            return None

    @classmethod
    def close_pool(cls):
        """关闭连接池"""
        if cls._pool:
            logger.info("关闭数据库连接池")
            cls._pool.close()
            cls._pool = None


# 全局实例
db = PGVectorDB()
