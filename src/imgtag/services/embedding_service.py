#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
嵌入模型服务
支持在线 API 和本地模型两种模式
"""

from typing import List, Optional

import numpy as np

from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)


class EmbeddingService:
    """嵌入模型服务类"""
    
    _local_model = None
    
    def __init__(self):
        """初始化嵌入模型服务"""
        logger.info("初始化嵌入模型服务")
    
    def _get_mode(self) -> str:
        """获取嵌入模式 (api 或 local)"""
        from imgtag.db import config_db
        return config_db.get("embedding_mode", "local")
    
    def _get_local_model(self):
        """获取本地模型实例"""
        if EmbeddingService._local_model is None:
            # 检查是否安装了 sentence-transformers
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "本地嵌入模式需要安装 sentence-transformers。\n"
                    "请运行: uv sync --extra local\n"
                    "或切换到 '在线 API' 模式"
                )
            
            from imgtag.db import config_db
            model_name = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
            
            logger.info(f"加载本地嵌入模型: {model_name}")
            try:
                EmbeddingService._local_model = SentenceTransformer(model_name)
                logger.info(f"本地模型加载成功，维度: {EmbeddingService._local_model.get_sentence_embedding_dimension()}")
            except Exception as e:
                logger.error(f"加载本地模型失败: {str(e)}")
                raise
        
        return EmbeddingService._local_model
    
    def get_dimensions(self) -> int:
        """获取向量维度"""
        from imgtag.db import config_db
        mode = self._get_mode()
        
        if mode == "local":
            # 本地模型的维度由模型决定
            model_name = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
            if "small" in model_name:
                return 512
            elif "base" in model_name:
                return 768
            elif "large" in model_name:
                return 1024
            return 512  # 默认
        else:
            return config_db.get_int("embedding_dimensions", 1536)
    
    async def get_embedding(self, text: str) -> List[float]:
        """获取文本的向量嵌入"""
        if not text or not text.strip():
            return [0.0] * self.get_dimensions()
        
        mode = self._get_mode()
        
        if mode == "local":
            return await self._get_embedding_local(text)
        else:
            return await self._get_embedding_api(text)
    
    async def _get_embedding_local(self, text: str) -> List[float]:
        """使用本地模型生成向量"""
        logger.info(f"使用本地模型生成向量: {text[:50]}...")
        
        try:
            model = self._get_local_model()
            embedding = model.encode(text.strip(), normalize_embeddings=True)
            
            logger.info(f"本地向量生成成功，维度: {len(embedding)}")
            return embedding.tolist()
            
        except Exception as e:
            logger.error(f"本地向量生成失败: {str(e)}")
            raise
    
    async def _get_embedding_api(self, text: str) -> List[float]:
        """使用 API 生成向量"""
        from imgtag.db import config_db
        from openai import AsyncOpenAI
        
        api_base = config_db.get("embedding_api_base_url", "https://api.openai.com/v1")
        api_key = config_db.get("embedding_api_key", "")
        
        if not api_key:
            raise ValueError("嵌入模型 API 密钥未配置，请在系统设置中配置")
        
        client = AsyncOpenAI(api_key=api_key, base_url=api_base)
        model = config_db.get("embedding_model", "text-embedding-3-small")
        dimensions = config_db.get_int("embedding_dimensions", 1536)
        
        logger.info(f"使用 API 生成向量: {text[:50]}...")
        
        try:
            response = await client.embeddings.create(
                model=model,
                input=text.strip(),
                dimensions=dimensions
            )
            
            embedding = response.data[0].embedding
            logger.info(f"API 向量生成成功，维度: {len(embedding)}")
            return embedding
            
        except Exception as e:
            logger.error(f"API 向量生成失败: {str(e)}")
            raise
    
    async def get_embedding_combined(
        self, 
        text: str, 
        tags: Optional[List[str]] = None
    ) -> List[float]:
        """获取结合文本和标签的向量嵌入"""
        parts = []
        
        if text and text.strip():
            parts.append(text.strip())
        
        if tags:
            valid_tags = [t.strip() for t in tags if t and t.strip()]
            if valid_tags:
                parts.append("标签: " + ", ".join(valid_tags))
        
        combined_text = " | ".join(parts) if parts else ""
        return await self.get_embedding(combined_text)
    
    @classmethod
    def reload_model(cls):
        """重新加载本地模型"""
        if cls._local_model is not None:
            del cls._local_model
            cls._local_model = None
            logger.info("本地模型已卸载，将在下次使用时重新加载")


# 全局实例
embedding_service = EmbeddingService()
