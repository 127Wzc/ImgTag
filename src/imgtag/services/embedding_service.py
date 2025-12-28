#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
嵌入模型服务
支持在线 API 和本地 ONNX 模型两种模式
"""

import os
from typing import List, Optional, TYPE_CHECKING
from pathlib import Path

import httpx
import requests

from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger

if TYPE_CHECKING:
    import numpy as np

logger = get_logger(__name__)

# ONNX 模型映射：模型名称 -> (HuggingFace 仓库, 维度)
ONNX_MODEL_MAP = {
    "BAAI/bge-small-zh-v1.5": ("Xenova/bge-small-zh-v1.5", 512),
    "BAAI/bge-base-zh-v1.5": ("Xenova/bge-base-zh-v1.5", 768),
    "shibing624/text2vec-base-chinese": ("GanymedeNil/text2vec-base-chinese-onnx", 768),
}

# Tokenizer 所需的文件列表
TOKENIZER_FILES = [
    ("tokenizer.json", True),        # (文件名, 是否必需)
    ("tokenizer_config.json", True),
    ("special_tokens_map.json", True),
    ("vocab.txt", False),            # 某些模型可能没有
]


def _download_file(url: str, dest_path: Path, timeout: int = 300, stream: bool = False) -> bool:
    """
    下载单个文件到指定路径
    
    Args:
        url: 下载地址
        dest_path: 保存路径
        timeout: 超时时间（秒）
        stream: 是否使用流式下载（用于大文件）
    
    Returns:
        是否下载成功
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        response = requests.get(url, stream=stream, timeout=timeout)
        response.raise_for_status()
        
        if stream:
            # 流式下载大文件，带进度显示
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        # 每 10MB 打印一次进度
                        if total_size > 0 and downloaded % (10 * 1024 * 1024) < 8192:
                            percent = downloaded * 100 / total_size
                            logger.info(f"  下载进度: {percent:.1f}%")
        else:
            # 直接下载小文件
            dest_path.write_bytes(response.content)
        
        return True
        
    except requests.exceptions.Timeout:
        logger.warning(f"下载超时: {url}")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"下载失败: {url} - {e}")
        return False


class ONNXEmbeddingModel:
    """СONNX 嵌入模型封装"""
    
    def __init__(self, model_name: str, hf_endpoint: str = "https://hf-mirror.com"):
        self.model_name = model_name
        self.hf_endpoint = hf_endpoint
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
        """加载 ONNX 模型和分词器
        
        优先从本地 models/ 目录加载完整模型（tokenizer + ONNX），实现完全离线运行。
        如果本地没有模型文件，则从配置的镜像站下载。
        
        本地模型目录结构：
        models/{model_name}/
        ├── tokenizer.json
        ├── tokenizer_config.json
        ├── vocab.txt
        ├── special_tokens_map.json
        └── onnx/
            └── model.onnx
        """
        
        try:
            import onnxruntime as ort
            from transformers import AutoTokenizer
        except ImportError:
            raise ImportError(
                "本地嵌入模式需要安装 ONNX 依赖。\n"
                "请运行: uv sync --extra local\n"
                "或切换到 '在线 API' 模式"
            )
        
        # 检查本地 models 目录是否有预置的完整模型
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        local_model_dir = project_root / "models" / self.model_name
        local_onnx_path = local_model_dir / "onnx" / "model.onnx"
        local_onnx_path_alt = local_model_dir / "model.onnx"  # 备用位置
        
        logger.info(f"检查本地模型目录: {local_model_dir}")
        logger.info(f"  - 目录存在: {local_model_dir.exists()}")
        logger.info(f"  - tokenizer.json 存在: {(local_model_dir / 'tokenizer.json').exists()}")
        logger.info(f"  - onnx/model.onnx 存在: {local_onnx_path.exists()}")
        logger.info(f"  - model.onnx 存在: {local_onnx_path_alt.exists()}")
        
        # 判断是否可以完全离线加载
        has_local_tokenizer = local_model_dir.exists() and (local_model_dir / "tokenizer.json").exists()
        has_local_onnx = local_onnx_path.exists() or local_onnx_path_alt.exists()
        can_load_offline = has_local_tokenizer and has_local_onnx
        
        if can_load_offline:
            logger.info("✓ 发现完整的本地模型，将完全离线加载（无需网络）")
        else:
            logger.info("✗ 本地模型不完整，需要从网络下载")
            if not has_local_tokenizer:
                logger.info("  - 缺少 tokenizer 文件")
            if not has_local_onnx:
                logger.info("  - 缺少 ONNX 模型文件")
        
        # ===== 加载 Tokenizer =====
        tokenizer_loaded = False
        if has_local_tokenizer:
            logger.info(f"从本地加载 tokenizer: {local_model_dir}")
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(
                    str(local_model_dir),
                    local_files_only=True,
                    trust_remote_code=False
                )
                tokenizer_loaded = True
                logger.info("✓ 本地 tokenizer 加载成功")
            except Exception as e:
                logger.warning(f"本地 tokenizer 加载失败: {e}")
        
        if not tokenizer_loaded:
            # 使用 requests 下载 tokenizer 文件到本地目录
            logger.info(f"使用镜像站下载 tokenizer: {self.hf_endpoint}/{self.onnx_repo}")
            
            local_model_dir.mkdir(parents=True, exist_ok=True)
            
            download_ok = True
            for filename, required in TOKENIZER_FILES:
                dest_path = local_model_dir / filename
                if dest_path.exists():
                    logger.info(f"  ✓ 已存在: {filename}")
                    continue
                
                url = f"{self.hf_endpoint}/{self.onnx_repo}/resolve/main/{filename}"
                logger.info(f"  下载: {filename}")
                
                if _download_file(url, dest_path, timeout=60):
                    logger.info(f"  ✓ {filename} 下载成功")
                elif required:
                    download_ok = False
                else:
                    logger.info(f"  - {filename} 不存在（可选文件）")
            
            if not download_ok:
                raise RuntimeError("Tokenizer 下载失败，请检查网络或手动下载")
            
            # 从下载的本地文件加载 tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(local_model_dir),
                local_files_only=True,
                trust_remote_code=False
            )
            logger.info("✓ 网络 tokenizer 下载并加载成功")
        
        # ===== 加载 ONNX 模型 =====
        onnx_path = None
        
        if has_local_onnx:
            # 优先使用本地 ONNX 文件
            if local_onnx_path.exists():
                onnx_path = str(local_onnx_path)
            else:
                onnx_path = str(local_onnx_path_alt)
            logger.info(f"从本地加载 ONNX 模型: {onnx_path}")
        else:
            # 从网络下载 ONNX 模型
            logger.info(f"使用镜像站下载 ONNX 模型: {self.hf_endpoint}")
            
            target_onnx_path = local_model_dir / "onnx" / "model.onnx"
            
            # 尝试多个可能的路径
            onnx_urls = [
                f"{self.hf_endpoint}/{self.onnx_repo}/resolve/main/onnx/model.onnx",
                f"{self.hf_endpoint}/{self.onnx_repo}/resolve/main/model.onnx",
            ]
            
            download_success = False
            for url in onnx_urls:
                logger.info(f"尝试下载: {url}")
                if _download_file(url, target_onnx_path, timeout=600, stream=True):
                    onnx_path = str(target_onnx_path)
                    logger.info(f"✓ ONNX 模型下载成功: {onnx_path}")
                    download_success = True
                    break
            
            if not download_success:
                logger.error("")
                logger.error("========== 离线模型下载说明 ==========")
                logger.error(f"请手动下载模型并放到: {local_model_dir}/")
                logger.error("")
                logger.error("方法1: 使用下载脚本")
                logger.error("  python scripts/download_model.py")
                logger.error("")
                logger.error("方法2: 手动下载")
                logger.error(f"  从 https://hf-mirror.com/{self.onnx_repo} 下载以下文件:")
                logger.error("  - tokenizer.json, tokenizer_config.json, special_tokens_map.json")
                logger.error("  - onnx/model.onnx")
                logger.error("======================================")
                raise RuntimeError("无法加载嵌入模型，请查看上方说明手动下载模型文件")
        
        # ===== 创建 ONNX 推理会话 =====
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        self.session = ort.InferenceSession(
            onnx_path,
            sess_options,
            providers=['CPUExecutionProvider']
        )
        
        logger.info(f"✓ ONNX 模型加载成功，维度: {self.dimensions}")
    
    def encode(self, text: str, normalize_embeddings: bool = True):
        """编码文本为向量"""
        import numpy as np
        
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
    
    async def _get_mode(self) -> str:
        """获取嵌入模式 (api 或 local)"""
        return await config_cache.get("embedding_mode", "local") or "local"
    
    async def _get_local_model(self) -> ONNXEmbeddingModel:
        """获取本地 ONNX 模型实例"""
        if EmbeddingService._local_model is None:
            model_name = await config_cache.get("embedding_local_model", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5"
            hf_endpoint = await config_cache.get("hf_endpoint", "https://hf-mirror.com") or "https://hf-mirror.com"
            
            # 获取 ONNX 模型仓库名
            if model_name in ONNX_MODEL_MAP:
                onnx_repo = ONNX_MODEL_MAP[model_name][0]
            else:
                onnx_repo = f"Xenova/{model_name.split('/')[-1]}"
            
            logger.info(f"加载本地嵌入模型: {model_name} -> {onnx_repo}")
            try:
                EmbeddingService._local_model = ONNXEmbeddingModel(model_name, hf_endpoint)
                logger.info(f"模型加载成功，维度: {EmbeddingService._local_model.get_sentence_embedding_dimension()}")
            except Exception as e:
                logger.error(f"加载本地模型失败: {str(e)}")
                raise
        
        return EmbeddingService._local_model
    
    async def get_dimensions(self) -> int:
        """获取向量维度"""
        mode = await self._get_mode()
        
        if mode == "local":
            # 本地模型的维度由模型决定
            model_name = await config_cache.get("embedding_local_model", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5"
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
            dim_str = await config_cache.get("embedding_dimensions", "1536")
            return int(dim_str) if dim_str else 1536
    
    async def get_embedding(self, text: str) -> List[float]:
        """获取文本的向量嵌入"""
        if not text or not text.strip():
            return [0.0] * await self.get_dimensions()
        
        mode = await self._get_mode()
        
        if mode == "local":
            return await self._get_embedding_local(text)
        else:
            return await self._get_embedding_api(text)
    
    async def _get_embedding_local(self, text: str) -> List[float]:
        """使用本地 ONNX 模型生成向量"""
        logger.info(f"使用本地 ONNX 模型生成向量: {text[:50]}...")
        
        try:
            model = await self._get_local_model()
            embedding = model.encode(text.strip(), normalize_embeddings=True)
            
            logger.info(f"本地向量生成成功，维度: {len(embedding)}")
            return embedding.tolist()
            
        except Exception as e:
            logger.error(f"本地向量生成失败: {str(e)}")
            raise
    
    async def _get_embedding_api(self, text: str) -> list[float]:
        """Generate embedding using API.

        Args:
            text: Text to embed.

        Returns:
            List of floats representing the embedding vector.

        Raises:
            ValueError: If API is not configured or request fails.
        """
        api_base = await config_cache.get("embedding_api_base_url", "https://api.openai.com/v1") or "https://api.openai.com/v1"
        api_key = await config_cache.get("embedding_api_key", "") or ""
        model = await config_cache.get("embedding_model", "text-embedding-3-small") or "text-embedding-3-small"
        dim_str = await config_cache.get("embedding_dimensions", "1536")
        dimensions = int(dim_str) if dim_str else 1536

        if not api_key:
            raise ValueError("嵌入模型 API 密钥未配置，请在系统设置中配置")

        logger.info(f"使用 API 生成向量: {text[:50]}...")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{api_base.rstrip('/')}/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "input": text.strip(),
                        "dimensions": dimensions,
                    },
                )

                if response.status_code != 200:
                    error_text = response.text[:500] if response.text else "无响应内容"
                    logger.error(f"API 请求失败: HTTP {response.status_code}, {error_text}")
                    raise ValueError(f"API 请求失败: HTTP {response.status_code}")

                data = response.json()
                embedding = data["data"][0]["embedding"]
                logger.info(f"API 向量生成成功，维度: {len(embedding)}")
                return embedding

        except httpx.ConnectError as e:
            logger.error(f"嵌入模型 API 连接失败: {e}")
            raise ValueError("无法连接到 API") from e
        except httpx.TimeoutException as e:
            logger.error(f"嵌入模型 API 请求超时: {e}")
            raise ValueError("API 请求超时") from e
        except Exception as e:
            logger.error(f"API 向量生成失败: {e}")
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
