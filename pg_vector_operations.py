#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PostgreSQL向量数据库操作
包含对images表的增删改查操作
"""

import psycopg2
import time
from logging_config import get_logger, get_perf_logger
from config import DB_CONNECTION_STRING, DEFAULT_SEARCH_LIMIT, DEFAULT_SIMILARITY_THRESHOLD

# 获取日志记录器
logger = get_logger(__name__)
perf_logger = get_perf_logger()

class PGVectorDB:
    """PostgreSQL向量数据库操作类"""
    
    def __init__(self, connection_string=DB_CONNECTION_STRING):
        """初始化数据库连接
        
        Args:
            connection_string: 数据库连接字符串，默认使用配置中的DB_CONNECTION_STRING
        """
        start_time = time.time()
        logger.info("初始化数据库连接")
        
        try:
            self.conn = psycopg2.connect(connection_string)
            self.cursor = self.conn.cursor()
            
            init_time = time.time() - start_time
            logger.info("数据库连接成功")
            perf_logger.info(f"数据库连接耗时: {init_time:.4f}秒")
            
            # 初始化表结构
            self.init_tables()
        except Exception as e:
            logger.error(f"数据库连接失败: {str(e)}")
            raise
    
    def __del__(self):
        """析构函数，关闭数据库连接"""
        if hasattr(self, 'cursor') and self.cursor:
            self.cursor.close()
        if hasattr(self, 'conn') and self.conn:
            self.conn.close()
            logger.info("数据库连接已关闭")
    
    def init_tables(self):
        """初始化数据库表
        
        检查public.images表是否存在，不存在则创建
        """
        start_time = time.time()
        logger.info("检查数据库表结构")
        
        try:
            # 检查vector扩展是否存在
            self.cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM pg_available_extensions WHERE name = 'vector' AND installed_version IS NOT NULL
            );
            """)
            
            vector_extension_exists = self.cursor.fetchone()[0]
            
            if not vector_extension_exists:
                logger.info("安装vector扩展")
                self.cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                self.conn.commit()
            
            # 检查images表是否存在
            self.cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'images'
            );
            """)
            
            table_exists = self.cursor.fetchone()[0]
            
            if not table_exists:
                logger.info("创建images表")
                
                # 创建表
                self.cursor.execute("""
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
                self.cursor.execute("""
                CREATE INDEX idx_images_tags ON public.images USING GIN (tags);
                """)
                
                self.cursor.execute("""
                CREATE INDEX idx_images_embedding ON public.images USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
                """)
                
                self.conn.commit()
                logger.info("images表创建成功")
            else:
                logger.info("images表已存在，跳过创建")
            
            init_time = time.time() - start_time
            perf_logger.info(f"表结构初始化耗时: {init_time:.4f}秒")
            
        except Exception as e:
            self.conn.rollback()
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
            
            self.cursor.execute(query, (image_url, tags, f"[{vector_str}]", description))
            new_id = self.cursor.fetchone()[0]
            self.conn.commit()
            
            process_time = time.time() - start_time
            logger.info(f"插入成功，ID: {new_id}, 耗时: {process_time:.4f}秒")
            
            return new_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"插入失败: {str(e)}")
            return None
    
    def search_by_tags(self, tags, limit=DEFAULT_SEARCH_LIMIT):
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
            
            self.cursor.execute(query, (tags, limit))
            results = self.cursor.fetchall()
            
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
    
    def search_similar_vectors(self, query_vector, limit=DEFAULT_SEARCH_LIMIT, threshold=DEFAULT_SIMILARITY_THRESHOLD):
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
            self.cursor.execute(query, (f"[{vector_str}]", f"[{vector_str}]", threshold, limit))
            results = self.cursor.fetchall()
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
            new_tags: 新标签列表
        
        Returns:
            是否更新成功
        """
        try:
            query = """
            UPDATE images
            SET tags = %s
            WHERE id = %s;
            """
            
            self.cursor.execute(query, (new_tags, image_id))
            affected_rows = self.cursor.rowcount
            self.conn.commit()
            
            if affected_rows > 0:
                logger.info(f"更新标签成功，ID: {image_id}")
                return True
            else:
                logger.warning(f"未找到ID为{image_id}的记录")
                return False
        except Exception as e:
            self.conn.rollback()
            logger.error(f"更新标签失败: {str(e)}")
            return False
    
    def count_images(self):
        """统计图像总数
        
        Returns:
            图像记录总数
        """
        start_time = time.time()
        logger.debug("统计图像总数")
        
        try:
            self.cursor.execute("SELECT COUNT(*) FROM images;")
            count = self.cursor.fetchone()[0]
            
            process_time = time.time() - start_time
            logger.info(f"图像总数: {count}, 耗时: {process_time:.4f}秒")
            
            return count
        except Exception as e:
            logger.error(f"统计失败: {str(e)}")
            return 0


if __name__ == "__main__":
    """简单测试"""
    from text_embedding import TextEmbedding
    
    # 创建数据库连接
    db = PGVectorDB()
    
    # 统计记录数
    count = db.count_images()
    print(f"当前数据库中有 {count} 条图像记录")
    
    if count > 0:
        # 测试标签搜索
        results = db.search_by_tags(["自然"], limit=2)
        print(f"\n标签搜索结果: {len(results)} 条记录")
        for img in results:
            print(f"- {img['image_url']} ({img['tags']})")
            print(f"  描述: {img['description']}")
    else:
        # 如果没有记录，插入测试数据
        print("插入测试数据...")
        text_embedding = TextEmbedding()
        text = "测试图像描述"
        embedding = text_embedding.get_embedding(text)
        
        db.insert_image(
            "https://example.com/test.jpg",
            ["测试", "示例"],
            embedding,
            "这是一个测试图像"
        ) 