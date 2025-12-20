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
from typing import List, Optional, Dict, Any

from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.core.config import settings

logger = get_logger(__name__)
perf_logger = get_perf_logger()


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
        """初始化数据库表"""
        start_time = time.time()
        logger.info("检查数据库表结构")
        
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
                    tags TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
                    embedding vector({vector_dim}) NOT NULL,
                    description TEXT,
                    source_type VARCHAR(20) DEFAULT 'url',
                    file_path TEXT,
                    original_url TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                """)
                
                # 创建索引
                cursor.execute("""
                CREATE INDEX idx_images_tags ON public.images USING GIN (tags);
                """)
                
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
                # 检查并添加新字段
                self._check_and_add_columns(cursor)
            
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
                logger.info("创建 tags 表")
                cursor.execute("""
                CREATE TABLE public.tags (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100) UNIQUE NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                """)
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
            
            init_time = time.time() - start_time
            perf_logger.info(f"表结构初始化耗时: {init_time:.4f}秒")
            
        except Exception as e:
            logger.error(f"初始化表结构失败: {str(e)}")
            raise
    
    def _check_and_add_columns(self, cursor):
        """检查并添加新列"""
        new_columns = [
            ("source_type", "VARCHAR(20) DEFAULT 'url'"),
            ("file_path", "TEXT"),
            ("original_url", "TEXT"),
            ("updated_at", "TIMESTAMP WITH TIME ZONE DEFAULT NOW()"),
        ]
        
        for col_name, col_type in new_columns:
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'images' 
                AND column_name = %s
            );
            """, (col_name,))
            
            if not cursor.fetchone()[0]:
                logger.info(f"添加新列: {col_name}")
                cursor.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_type};")
    
    def insert_image(
        self,
        image_url: str,
        tags: List[str],
        embedding: List[float],
        description: str = None,
        source_type: str = "url",
        file_path: str = None,
        original_url: str = None
    ) -> Optional[int]:
        """插入一条图像记录"""
        start_time = time.time()
        logger.debug(f"插入图像记录: {image_url}")
        
        try:
            vector_str = ','.join(map(str, embedding))
            
            query = """
            INSERT INTO images (image_url, tags, embedding, description, source_type, file_path, original_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (
                        image_url, tags, f"[{vector_str}]", description,
                        source_type, file_path, original_url
                    ))
                    new_id = cursor.fetchone()[0]
                conn.commit()
            
            process_time = time.time() - start_time
            logger.info(f"插入成功，ID: {new_id}, 耗时: {process_time:.4f}秒")
            
            return new_id
        except Exception as e:
            logger.error(f"插入失败: {str(e)}")
            return None
    
    def search_by_tags(self, tags: List[str], limit: int = None) -> List[Dict]:
        """通过标签搜索图像"""
        if limit is None:
            limit = settings.DEFAULT_SEARCH_LIMIT
            
        start_time = time.time()
        logger.info(f"按标签搜索: {tags}, 限制: {limit}")
        
        try:
            query = """
            SELECT id, image_url, tags, description, source_type, original_url
            FROM images
            WHERE tags @> %s
            LIMIT %s;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (tags, limit))
                    results = cursor.fetchall()
            
            images = []
            for row in results:
                images.append({
                    "id": row[0],
                    "image_url": row[1],
                    "tags": row[2],
                    "description": row[3],
                    "source_type": row[4],
                    "original_url": row[5]
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
            SELECT id, image_url, tags, description, source_type, original_url,
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
            
            query_time = time.time() - query_start
            perf_logger.info(f"向量搜索 SQL 执行耗时: {query_time:.4f}秒")
            
            images = []
            for row in results:
                images.append({
                    "id": row[0],
                    "image_url": row[1],
                    "tags": row[2],
                    "description": row[3],
                    "source_type": row[4],
                    "original_url": row[5],
                    "similarity": row[6]
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
        tag_weight: float = 0.3
    ) -> List[Dict]:
        """混合搜索：向量相似度 + 标签匹配"""
        if limit is None:
            limit = settings.DEFAULT_SEARCH_LIMIT
        if threshold is None:
            threshold = settings.DEFAULT_SIMILARITY_THRESHOLD
            
        start_time = time.time()
        logger.info(f"混合搜索: '{query_text}', 阈值: {threshold}")
        
        try:
            vector_str = ','.join(map(str, query_vector))
            
            # 混合搜索查询
            # 1. 计算向量相似度 (0-1)
            # 2. 计算标签匹配度 (1 if query_text in tags else 0)
            # 3. 加权求和
            query = """
            SELECT id, image_url, tags, description, source_type, original_url,
                   (1 - (embedding <=> %s)) as vector_score,
                   (CASE WHEN %s = ANY(tags) THEN 1.0 ELSE 0.0 END) as tag_score
            FROM images
            WHERE (1 - (embedding <=> %s)) > %s OR (%s = ANY(tags))
            ORDER BY ((1 - (embedding <=> %s)) * %s + (CASE WHEN %s = ANY(tags) THEN 1.0 ELSE 0.0 END) * %s) DESC
            LIMIT %s;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (
                        f"[{vector_str}]", 
                        query_text, 
                        f"[{vector_str}]", 
                        threshold, 
                        query_text,
                        f"[{vector_str}]",
                        vector_weight,
                        query_text,
                        tag_weight,
                        limit
                    ))
                    results = cursor.fetchall()
            
            images = []
            for row in results:
                vector_score = float(row[6])
                tag_score = float(row[7])
                final_score = vector_score * vector_weight + tag_score * tag_weight
                
                images.append({
                    "id": row[0],
                    "image_url": row[1],
                    "tags": row[2],
                    "description": row[3],
                    "source_type": row[4],
                    "original_url": row[5],
                    "similarity": final_score, # 返回混合分数作为相似度
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
    
    def search_images(
        self,
        tags: List[str] = None,
        url_contains: str = None,
        description_contains: str = None,
        limit: int = 10,
        offset: int = 0,
        sort_by: str = "id",
        sort_desc: bool = False
    ) -> Dict[str, Any]:
        """高级图像搜索"""
        start_time = time.time()
        logger.info(f"高级图像搜索: 标签:{tags}, URL包含:{url_contains}")
        
        try:
            conditions = []
            params = []
            
            if tags and len(tags) > 0:
                conditions.append("tags && %s")
                params.append(tags)
            
            if url_contains:
                conditions.append("image_url ILIKE %s")
                params.append(f"%{url_contains}%")
            
            if description_contains:
                conditions.append("description ILIKE %s")
                params.append(f"%{description_contains}%")
            
            valid_sort_fields = {"id": "id", "url": "image_url", "created_at": "created_at"}
            sort_field = valid_sort_fields.get(sort_by, "id")
            sort_order = "DESC" if sort_desc else "ASC"
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            query = f"""
            SELECT id, image_url, tags, description, source_type, original_url
            FROM images
            WHERE {where_clause}
            ORDER BY {sort_field} {sort_order}
            LIMIT %s OFFSET %s;
            """
            
            params.append(limit)
            params.append(offset)
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    results = cursor.fetchall()
            
            images = []
            for row in results:
                images.append({
                    "id": row[0],
                    "image_url": row[1],
                    "tags": row[2],
                    "description": row[3],
                    "source_type": row[4],
                    "original_url": row[5]
                })
            
            # 获取总数
            count_query = f"""
            SELECT COUNT(*) FROM images WHERE {where_clause};
            """
            
            total_count = 0
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(count_query, params[:-2] if len(params) > 2 else [])
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

    def sync_tags(self) -> int:
        """同步 tags 表与 images 表中的标签"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 清空 tags 表计数
                    cursor.execute("UPDATE tags SET usage_count = 0;")
                    
                    # 2. 从 images 表聚合标签并插入/更新 tags 表
                    cursor.execute("""
                    WITH all_tags AS (
                        SELECT unnest(tags) as tag_name
                        FROM images
                    ),
                    tag_counts AS (
                        SELECT tag_name, COUNT(*) as count
                        FROM all_tags
                        GROUP BY tag_name
                    )
                    INSERT INTO tags (name, usage_count)
                    SELECT tag_name, count FROM tag_counts
                    ON CONFLICT (name) 
                    DO UPDATE SET usage_count = EXCLUDED.usage_count;
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

    def rename_tag(self, old_name: str, new_name: str) -> bool:
        """重命名标签（同时更新 images 表）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 更新 tags 表
                    cursor.execute("""
                    INSERT INTO tags (name, usage_count) VALUES (%s, 0)
                    ON CONFLICT (name) DO NOTHING;
                    """, (new_name,))
                    
                    # 2. 更新 images 表中的标签数组
                    cursor.execute("""
                    UPDATE images 
                    SET tags = array_replace(tags, %s, %s)
                    WHERE %s = ANY(tags);
                    """, (old_name, new_name, old_name))
                    
                    # 3. 删除旧标签
                    cursor.execute("DELETE FROM tags WHERE name = %s;", (old_name,))
                    
                    # 4. 重新同步计数
                    self.sync_tags()
                    
                    return True
        except Exception as e:
            logger.error(f"重命名标签失败: {str(e)}")
            return False

    def delete_tag(self, tag_name: str) -> bool:
        """删除标签（从所有图片中移除）"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 1. 从 images 表中移除标签
                    cursor.execute("""
                    UPDATE images 
                    SET tags = array_remove(tags, %s)
                    WHERE %s = ANY(tags);
                    """, (tag_name, tag_name))
                    
                    # 2. 从 tags 表删除
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
        embedding: List[float] = None
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
                
            if tags is not None:
                update_fields.append("tags = %s")
                params.append(tags)
                
            if description is not None:
                update_fields.append("description = %s")
                params.append(description)
                
            if embedding is not None:
                vector_str = ','.join(map(str, embedding))
                update_fields.append("embedding = %s")
                params.append(f"[{vector_str}]")
            
            update_fields.append("updated_at = NOW()")
            
            if len(update_fields) == 1:
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
                    if cursor.rowcount == 0:
                        logger.warning(f"未找到 ID 为 {image_id} 的图像记录")
                        return False
                conn.commit()
            
            process_time = time.time() - start_time
            logger.info(f"图像信息更新完成，耗时: {process_time:.4f}秒")
            
            return True
        except Exception as e:
            logger.error(f"图像信息更新失败: {str(e)}")
            return False
    
    def delete_image(self, image_id: int) -> bool:
        """删除图像"""
        start_time = time.time()
        logger.info(f"删除图像 ID:{image_id}")
        
        try:
            query = """
            DELETE FROM images
            WHERE id = %s
            RETURNING id;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (image_id,))
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
            query = """
            SELECT id, image_url, tags, description, source_type, file_path, original_url
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
            
            image = {
                "id": result[0],
                "image_url": result[1],
                "tags": result[2],
                "description": result[3],
                "source_type": result[4],
                "file_path": result[5],
                "original_url": result[6]
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
        """从收藏夹中获取随机图片"""
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
                    query = """
                    SELECT i.id, i.image_url, i.tags, i.description, i.source_type, 
                           i.file_path, i.original_url
                    FROM images i
                    JOIN image_collections ic ON i.id = ic.image_id
                    WHERE ic.collection_id = ANY(%s)
                    """
                    params = [collection_ids]
                    
                    # 添加标签过滤
                    if tags:
                        query += " AND i.tags && %s"
                        params.append(tags)
                    
                    query += " ORDER BY RANDOM() LIMIT 1;"
                    
                    cursor.execute(query, params)
                    result = cursor.fetchone()
            
            if not result:
                return None
                
            return {
                "id": result[0],
                "image_url": result[1],
                "tags": result[2],
                "description": result[3],
                "source_type": result[4],
                "file_path": result[5],
                "original_url": result[6]
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
        """获取收藏夹内的图片"""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    # 获取图片列表
                    cursor.execute("""
                    SELECT i.id, i.image_url, i.tags, i.description, i.source_type, i.file_path, i.original_url
                    FROM images i
                    JOIN image_collections ic ON i.id = ic.image_id
                    WHERE ic.collection_id = %s
                    ORDER BY ic.added_at DESC
                    LIMIT %s OFFSET %s;
                    """, (collection_id, limit, offset))
                    results = cursor.fetchall()
                    
                    # 获取总数
                    cursor.execute("""
                    SELECT COUNT(*) FROM image_collections WHERE collection_id = %s;
                    """, (collection_id,))
                    total = cursor.fetchone()[0]
            
            images = [{
                "id": row[0],
                "image_url": row[1],
                "tags": row[2],
                "description": row[3],
                "source_type": row[4],
                "file_path": row[5],
                "original_url": row[6]
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

    @classmethod
    def close_pool(cls):
        """关闭连接池"""
        if cls._pool:
            logger.info("关闭数据库连接池")
            cls._pool.close()
            cls._pool = None


# 全局实例
db = PGVectorDB()
