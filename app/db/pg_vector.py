#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PostgreSQL向量数据库操作
包含对images表的增删改查操作
使用连接池管理数据库连接
"""

import psycopg
from psycopg_pool import ConnectionPool
import time
from app.core.logging_config import get_logger, get_perf_logger
from app.core.config import settings

# 获取日志记录器
logger = get_logger(__name__)
perf_logger = get_perf_logger()

class PGVectorDB:
    """PostgreSQL向量数据库操作类（使用连接池）"""
    
    # 类变量，存储单例实例
    _instance = None
    # 连接池
    _pool = None
    
    def __new__(cls, connection_string=None):
        """创建单例实例
        
        Args:
            connection_string: 数据库连接字符串，默认使用配置中的PG_CONNECTION_STRING
        """
        if cls._instance is None:
            logger.info("创建PGVectorDB单例实例")
            cls._instance = super(PGVectorDB, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, connection_string=None):
        """初始化数据库连接池
        
        Args:
            connection_string: 数据库连接字符串，默认使用配置中的PG_CONNECTION_STRING
        """
        # 如果已经初始化，直接返回
        if getattr(self, "_initialized", False):
            return
            
        if connection_string is None:
            connection_string = settings.PG_CONNECTION_STRING
        
        start_time = time.time()
        logger.info("初始化数据库连接池")
        
        try:
            # 创建连接池
            PGVectorDB._pool = ConnectionPool(
                connection_string,
                min_size=5,  # 连接池最小连接数
                max_size=20,  # 连接池最大连接数
                name="pg_vector_pool"
            )
            
            # 初始化表结构
            with PGVectorDB._pool.connection() as conn:
                conn.autocommit = True
                with conn.cursor() as cursor:
                    self._init_tables(cursor)
            
            init_time = time.time() - start_time
            logger.info("数据库连接池初始化成功")
            perf_logger.info(f"数据库连接池初始化耗时: {init_time:.4f}秒")
            
            # 标记为已初始化
            self._initialized = True
        except Exception as e:
            logger.error(f"数据库连接池初始化失败: {str(e)}")
            raise
    
    def _get_connection(self):
        """获取连接池中的连接
        
        Returns:
            连接上下文管理器
        """
        return PGVectorDB._pool.connection()
    
    def _init_tables(self, cursor):
        """初始化数据库表
        
        Args:
            cursor: 数据库游标
            
        检查public.images表是否存在，不存在则创建
        """
        start_time = time.time()
        logger.info("检查数据库表结构")
        
        try:
            # 检查vector扩展是否存在
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'vector' AND installed_version IS NOT NULL
            );
            """)
            
            vector_extension_exists = cursor.fetchone()[0]
            
            if not vector_extension_exists:
                logger.info("安装vector扩展")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # 检查images表是否存在
            cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'images'
            );
            """)
            
            table_exists = cursor.fetchone()[0]
            
            if not table_exists:
                logger.info("创建images表")
                
                # 创建表
                cursor.execute("""
                CREATE TABLE public.images (
                    id SERIAL PRIMARY KEY,
                    image_url TEXT NOT NULL,
                    tags TEXT[] NOT NULL,
                    embedding vector(512) NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                );
                """)
                
                # 创建索引
                cursor.execute("""
                CREATE INDEX idx_images_tags ON public.images USING GIN (tags);
                """)
                
                cursor.execute("""
                CREATE INDEX idx_images_embedding ON public.images USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
                """)
                
                logger.info("images表创建成功")
            else:
                logger.info("images表已存在，跳过创建")
            
            init_time = time.time() - start_time
            perf_logger.info(f"表结构初始化耗时: {init_time:.4f}秒")
            
        except Exception as e:
            logger.error(f"初始化表结构失败: {str(e)}")
            raise
    
    def insert_image(self, image_url, tags, embedding, description=None):
        """插入一条图像记录
        
        Args:
            image_url: 图像URL
            tags: 标签列表
            embedding: 向量嵌入，numpy数组
            description: 图像描述文本，可选
        
        Returns:
            新插入记录的ID
        """
        start_time = time.time()
        logger.debug(f"插入图像记录: {image_url}")
        
        try:
            # 将numpy数组转换为PostgreSQL向量格式的字符串
            vector_str = ','.join(map(str, embedding))
            
            query = """
            INSERT INTO images (image_url, tags, embedding, description)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (image_url, tags, f"[{vector_str}]", description))
                    new_id = cursor.fetchone()[0]
                conn.commit()
            
            process_time = time.time() - start_time
            logger.info(f"插入成功，ID: {new_id}, 耗时: {process_time:.4f}秒")
            
            return new_id
        except Exception as e:
            logger.error(f"插入失败: {str(e)}")
            return None
    
    def search_by_tags(self, tags, limit=settings.DEFAULT_SEARCH_LIMIT):
        """通过标签搜索图像
        
        Args:
            tags: 标签列表
            limit: 返回结果数量上限
        
        Returns:
            符合条件的图像记录列表
        """
        start_time = time.time()
        logger.info(f"按标签搜索: {tags}, 限制: {limit}")
        
        try:
            query = """
            SELECT id, image_url, tags, description
            FROM images
            WHERE tags @> %s
            LIMIT %s;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (tags, limit))
                    results = cursor.fetchall()
            
            images = []
            for id, url, img_tags, description in results:
                images.append({
                    "id": id,
                    "image_url": url,
                    "tags": img_tags,
                    "description": description
                })
            
            process_time = time.time() - start_time
            logger.info(f"标签搜索完成，找到{len(images)}条记录，耗时: {process_time:.4f}秒")
            
            return images
        except Exception as e:
            logger.error(f"标签搜索失败: {str(e)}")
            return []
    
    def search_similar_vectors(self, query_vector, limit=settings.DEFAULT_SEARCH_LIMIT, threshold=settings.DEFAULT_SIMILARITY_THRESHOLD):
        """向量相似度搜索
        
        Args:
            query_vector: 查询向量，numpy数组
            limit: 返回结果数量上限
            threshold: 相似度阈值
        
        Returns:
            相似图像列表，按相似度降序排列
        """
        start_time = time.time()
        logger.info(f"向量相似度搜索，阈值: {threshold}, 限制: {limit}")
        
        try:
            vector_str = ','.join(map(str, query_vector))
            
            query = """
            SELECT id, image_url, tags, description, 1 - (embedding <=> %s) as similarity
            FROM images
            WHERE 1 - (embedding <=> %s) > %s
            ORDER BY similarity DESC
            LIMIT %s;
            """
            
            query_start = time.time()
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (f"[{vector_str}]", f"[{vector_str}]", threshold, limit))
                    results = cursor.fetchall()
            
            query_time = time.time() - query_start
            perf_logger.info(f"向量搜索SQL执行耗时: {query_time:.4f}秒")
            
            images = []
            for id, url, tags, description, similarity in results:
                images.append({
                    "id": id,
                    "image_url": url,
                    "tags": tags,
                    "description": description,
                    "similarity": similarity
                })
            
            total_time = time.time() - start_time
            logger.info(f"向量搜索完成，找到{len(images)}条记录，耗时: {total_time:.4f}秒")
            
            # 记录最高相似度
            if images:
                max_similarity = max(img["similarity"] for img in images)
                perf_logger.info(f"最高相似度: {max_similarity:.4f}")
            
            return images
        except Exception as e:
            logger.error(f"向量搜索失败: {str(e)}")
            return []
            
    def update_image_tags(self, image_id, new_tags):
        """更新图像标签
        
        Args:
            image_id: 图像ID
            new_tags: 新的标签列表
            
        Returns:
            是否更新成功
        """
        start_time = time.time()
        logger.info(f"更新图像ID:{image_id}的标签: {new_tags}")
        
        try:
            query = """
            UPDATE images
            SET tags = %s
            WHERE id = %s;
            """
            
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, (new_tags, image_id))
                conn.commit()
            
            process_time = time.time() - start_time
            logger.info(f"标签更新完成，耗时: {process_time:.4f}秒")
            
            return True
        except Exception as e:
            logger.error(f"标签更新失败: {str(e)}")
            return False
    
    def count_images(self):
        """获取图像总数
        
        Returns:
            图像总数
        """
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM images;")
                    count = cursor.fetchone()[0]
            return count
        except Exception as e:
            logger.error(f"获取图像总数失败: {str(e)}")
            return 0
    
    @classmethod
    def close_pool(cls):
        """关闭连接池"""
        if cls._pool:
            logger.info("关闭数据库连接池")
            cls._pool.close()
            cls._pool = None 