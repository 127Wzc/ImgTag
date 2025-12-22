#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置数据库操作
管理系统配置的存取
"""

import time
from typing import Optional, Dict, Any

from imgtag.core.logging_config import get_logger
from imgtag.db.pg_vector import PGVectorDB

logger = get_logger(__name__)


class ConfigDB:
    """配置数据库操作类"""
    
    _instance = None
    _cache: Dict[str, str] = {}
    _cache_loaded = False
    
    # 默认配置值
    DEFAULT_CONFIG = {
        # 视觉模型配置
        "vision_api_base_url": "https://api.openai.com/v1",
        "vision_api_key": "",
        "vision_model": "gpt-4o-mini",
        "vision_prompt": """请分析这张图片，并按以下格式返回JSON响应:
{
    "tags": ["标签1", "标签2", "标签3", ...],
    "description": "详细的图片描述文本"
}

要求：
1. tags: 提取5-10个关键标签，使用中文
2. description: 用中文详细描述图片内容

请只返回JSON格式，不要添加任何其他文字。""",
        
        # 嵌入模型配置
        "embedding_mode": "local",  # local 或 api
        "embedding_local_model": "BAAI/bge-small-zh-v1.5",  # 本地模型名称
        "hf_endpoint": "https://hf-mirror.com",  # Hugging Face 镜像站地址
        "embedding_api_base_url": "https://api.openai.com/v1",
        "embedding_api_key": "",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": "512",  # 本地 bge-small 是 512 维
        
        # 队列配置
        "queue_max_workers": "2",  # 最大并发线程数
        "queue_batch_interval": "1",  # 每个任务完成后的间隔（秒）
    }
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(ConfigDB, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化配置数据库"""
        if getattr(self, "_initialized", False):
            return
        
        logger.info("初始化配置数据库")
        self._db = PGVectorDB()
        self._init_config_table()
        self._initialized = True
    
    def _init_config_table(self):
        """初始化配置表"""
        try:
            with self._db._get_connection() as conn:
                conn.autocommit = True
                with conn.cursor() as cursor:
                    # 检查配置表是否存在
                    cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = 'public' AND table_name = 'config'
                    );
                    """)
                    
                    table_exists = cursor.fetchone()[0]
                    
                    if not table_exists:
                        logger.info("创建 config 表")
                        
                        cursor.execute("""
                        CREATE TABLE public.config (
                            key VARCHAR(100) PRIMARY KEY,
                            value TEXT NOT NULL,
                            description TEXT,
                            is_secret BOOLEAN DEFAULT FALSE,
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        );
                        """)
                        
                        # 插入默认配置
                        for key, value in self.DEFAULT_CONFIG.items():
                            is_secret = "key" in key.lower()
                            cursor.execute("""
                            INSERT INTO config (key, value, is_secret)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (key) DO NOTHING;
                            """, (key, value, is_secret))
                        
                        logger.info("config 表创建成功，已插入默认配置")
                    else:
                        logger.info("config 表已存在")
                        # 确保所有默认配置项都存在
                        for key, value in self.DEFAULT_CONFIG.items():
                            is_secret = "key" in key.lower()
                            cursor.execute("""
                            INSERT INTO config (key, value, is_secret)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (key) DO NOTHING;
                            """, (key, value, is_secret))
                            
        except Exception as e:
            logger.error(f"初始化配置表失败: {str(e)}")
            raise
    
    def get(self, key: str, default: str = None) -> Optional[str]:
        """获取配置值"""
        try:
            # 先检查缓存
            if key in self._cache:
                return self._cache[key]
            
            with self._db._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT value FROM config WHERE key = %s;",
                        (key,)
                    )
                    result = cursor.fetchone()
                    
                    if result:
                        self._cache[key] = result[0]
                        return result[0]
                    
            return default
        except Exception as e:
            logger.error(f"获取配置失败 [{key}]: {str(e)}")
            return default
    
    def get_int(self, key: str, default: int = 0) -> int:
        """获取整数配置值"""
        value = self.get(key)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default
    
    def set(self, key: str, value: str, is_secret: bool = False) -> bool:
        """设置配置值"""
        try:
            with self._db._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    INSERT INTO config (key, value, is_secret, updated_at)
                    VALUES (%s, %s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET 
                        value = EXCLUDED.value,
                        is_secret = EXCLUDED.is_secret,
                        updated_at = NOW();
                    """, (key, value, is_secret))
                conn.commit()
            
            # 更新缓存
            self._cache[key] = value
            logger.info(f"配置已更新: {key}")
            return True
        except Exception as e:
            logger.error(f"设置配置失败 [{key}]: {str(e)}")
            return False
    
    def get_all(self, include_secrets: bool = False) -> Dict[str, Any]:
        """获取所有配置"""
        try:
            with self._db._get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                    SELECT key, value, is_secret FROM config ORDER BY key;
                    """)
                    results = cursor.fetchall()
            
            config = {}
            for key, value, is_secret in results:
                if is_secret and not include_secrets:
                    # 对于密钥，只显示是否已设置
                    config[key] = "******" if value else ""
                else:
                    config[key] = value
                    
            return config
        except Exception as e:
            logger.error(f"获取所有配置失败: {str(e)}")
            return {}
    
    def update_multiple(self, configs: Dict[str, str]) -> bool:
        """批量更新配置（带重试机制）"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                with self._db._get_connection() as conn:
                    with conn.cursor() as cursor:
                        for key, value in configs.items():
                            is_secret = "key" in key.lower()
                            cursor.execute("""
                            INSERT INTO config (key, value, is_secret, updated_at)
                            VALUES (%s, %s, %s, NOW())
                            ON CONFLICT (key) DO UPDATE SET 
                                value = EXCLUDED.value,
                                updated_at = NOW();
                            """, (key, value, is_secret))
                    conn.commit()
                
                # 更新缓存
                self._cache.update(configs)
                logger.info(f"批量更新配置成功: {list(configs.keys())}")
                return True
                
            except Exception as e:
                logger.warning(f"批量更新配置失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    # 等待后重试
                    time.sleep(0.5)
                    continue
                else:
                    logger.error(f"批量更新配置失败: {str(e)}")
                    return False
        
        return False
    
    def clear_cache(self):
        """清除配置缓存"""
        self._cache.clear()
        self._cache_loaded = False


# 全局实例
config_db = ConfigDB()
