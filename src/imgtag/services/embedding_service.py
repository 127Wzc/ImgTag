#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
嵌入模型服务
支持在线 API 和本地 ONNX 模型两种模式
"""

import os
from typing import List, Optional
from pathlib import Path

import numpy as np

from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

# ONNX 模型映射：模型名称 -> (HuggingFace 仓库, 维度)
ONNX_MODEL_MAP = {
    "BAAI/bge-small-zh-v1.5": ("Xenova/bge-small-zh-v1.5", 512),
    "BAAI/bge-base-zh-v1.5": ("Xenova/bge-base-zh-v1.5", 768),
    "shibing624/text2vec-base-chinese": ("GanymedeNil/text2vec-base-chinese-onnx", 768),
}


class ONNXEmbeddingModel:
    """ONNX 嵌入模型封装"""
    
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.session = None
        self.tokenizer = None
        self.dimensions = 512
        
        # 获取 ONNX 模型信息
        if model_name in ONNX_MODEL_MAP:
            self.onnx_repo, self.dimensions = ONNX_MODEL_MAP[model_name]
        else:
            # 默认尝试使用 Xenova 的转换版本
            self.onnx_repo = f"Xenova/{model_name.split('/')[-1]}"
            self.dimensions = 512
        
        self._load_model()
    
    def _load_model(self):
        """加载 ONNX 模型和分词器"""
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
        except ImportError:
            raise ImportError(
                "本地嵌入模式需要安装 ONNX 依赖。\n"
                "请运行: uv sync --extra local\n"
                "或切换到 '在线 API' 模式"
            )
        
        # 记录加载信息（只在这里记录，不在外层重复）
        
        # 下载/加载分词器
        self.tokenizer = AutoTokenizer.from_pretrained(self.onnx_repo)
        
        # 下载/加载 ONNX 模型
        from huggingface_hub import hf_hub_download
        
        try:
            # 尝试下载 ONNX 模型文件
            onnx_path = hf_hub_download(
                repo_id=self.onnx_repo,
                filename="onnx/model.onnx",
            )
        except Exception:
            # 备用路径
            try:
                onnx_path = hf_hub_download(
                    repo_id=self.onnx_repo,
                    filename="model.onnx",
                )
            except Exception as e:
                logger.error(f"下载 ONNX 模型失败: {e}")
                raise
        
        # 创建 ONNX 推理会话
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        self.session = ort.InferenceSession(
            onnx_path,
            sess_options,
            providers=['CPUExecutionProvider']
        )
        
        logger.info(f"ONNX 模型加载成功，维度: {self.dimensions}")
    
    def encode(self, text: str, normalize_embeddings: bool = True) -> np.ndarray:
        """编码文本为向量"""
        # 分词
        inputs = self.tokenizer(
            text,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np"
        )
        
        # ONNX 推理
        ort_inputs = {
            "input_ids": inputs["input_ids"].astype(np.int64),
            "attention_mask": inputs["attention_mask"].astype(np.int64),
        }
        
        # 某些模型需要 token_type_ids
        if "token_type_ids" in inputs:
            ort_inputs["token_type_ids"] = inputs["token_type_ids"].astype(np.int64)
        
        outputs = self.session.run(None, ort_inputs)
        
        # 获取句子嵌入 (通常是 [CLS] token 或 mean pooling)
        # 不同模型输出格式可能不同，这里使用 mean pooling
        token_embeddings = outputs[0]  # [batch, seq_len, hidden_size]
        attention_mask = inputs["attention_mask"]
        
        # Mean pooling
        input_mask_expanded = np.expand_dims(attention_mask, -1)
        sum_embeddings = np.sum(token_embeddings * input_mask_expanded, axis=1)
        sum_mask = np.clip(input_mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        embeddings = sum_embeddings / sum_mask
        
        # 取第一个结果（单条文本）
        embedding = embeddings[0]
        
        # 归一化
        if normalize_embeddings:
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
        
        return embedding
    
    def get_sentence_embedding_dimension(self) -> int:
        """获取向量维度"""
        return self.dimensions


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
    
    def _get_local_model(self) -> ONNXEmbeddingModel:
        """获取本地 ONNX 模型实例"""
        if EmbeddingService._local_model is None:
            from imgtag.db import config_db
            model_name = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
            
            # 获取 ONNX 模型仓库名
            if model_name in ONNX_MODEL_MAP:
                onnx_repo = ONNX_MODEL_MAP[model_name][0]
            else:
                onnx_repo = f"Xenova/{model_name.split('/')[-1]}"
            
            logger.info(f"加载本地嵌入模型: {model_name} -> {onnx_repo}")
            try:
                EmbeddingService._local_model = ONNXEmbeddingModel(model_name)
                logger.info(f"模型加载成功，维度: {EmbeddingService._local_model.get_sentence_embedding_dimension()}")
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
            if model_name in ONNX_MODEL_MAP:
                return ONNX_MODEL_MAP[model_name][1]
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
        """使用本地 ONNX 模型生成向量"""
        logger.info(f"使用本地 ONNX 模型生成向量: {text[:50]}...")
        
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
