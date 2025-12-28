#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
S3 存储服务
管理员备份文件到 S3 兼容存储
"""

import os
import time
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from pathlib import Path

from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger

if TYPE_CHECKING:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

logger = get_logger(__name__)


class S3Service:
    """S3 存储服务 - 单例模式"""
    
    _instance = None
    _client = None
    
    # 配置缓存
    _config_cache: dict = {}
    _config_cache_time: float = 0
    _config_cache_ttl: float = 30.0  # 30 秒缓存
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(S3Service, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化（懒加载，不立即连接）"""
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._client = None
        logger.info("S3 服务初始化（懒加载模式）")
    
    async def _load_config(self) -> dict:
        """加载并缓存所有 S3 配置"""
        now = time.time()
        
        # 检查缓存是否有效
        if now - self._config_cache_time < self._config_cache_ttl and self._config_cache:
            return self._config_cache
        
        # 批量获取配置
        self._config_cache = {
            "enabled": (await config_cache.get("s3_enabled", "false") or "false").lower() == "true",
            "endpoint_url": await config_cache.get("s3_endpoint_url", "") or "",
            "access_key_id": await config_cache.get("s3_access_key_id", "") or "",
            "secret_access_key": await config_cache.get("s3_secret_access_key", "") or "",
            "bucket_name": await config_cache.get("s3_bucket_name", "") or "",
            "region": await config_cache.get("s3_region", "us-east-1") or "us-east-1",
            "public_url_prefix": (await config_cache.get("s3_public_url_prefix", "") or "").rstrip("/"),
            "path_prefix": (await config_cache.get("s3_path_prefix", "imgtag/") or "imgtag/").rstrip("/"),
        }
        self._config_cache_time = now
        return self._config_cache
    
    async def _get_client(self):
        """获取 boto3 客户端（懒加载）"""
        if self._client is not None:
            return self._client
        
        # 延迟导入 boto3（可选依赖）
        import boto3
        
        cfg = await self._load_config()
        
        if not cfg["endpoint_url"] or not cfg["access_key_id"] or not cfg["secret_access_key"]:
            raise ValueError("S3 配置不完整，请检查 endpoint_url, access_key_id, secret_access_key")
        
        self._client = boto3.client(
            "s3",
            endpoint_url=cfg["endpoint_url"],
            aws_access_key_id=cfg["access_key_id"],
            aws_secret_access_key=cfg["secret_access_key"],
            region_name=cfg["region"]
        )
        logger.info(f"S3 客户端已创建: {cfg['endpoint_url']}")
        return self._client
    
    async def is_enabled(self) -> bool:
        """检查 S3 是否启用"""
        cfg = await self._load_config()
        return cfg["enabled"]
    
    async def get_bucket_name(self) -> str:
        """获取存储桶名称"""
        cfg = await self._load_config()
        return cfg["bucket_name"]
    
    async def generate_s3_key(self, filename: str) -> str:
        """
        根据文件名生成 S3 对象键
        
        格式: {prefix}/{year}/{month}/{filename}
        例如: imgtag/2024/12/abc123.jpg
        """
        cfg = await self._load_config()
        now = datetime.now()
        return f"{cfg['path_prefix']}/{now.year}/{now.month:02d}/{filename}"
    
    async def get_public_url(self, s3_key: str) -> str:
        """获取公开访问 URL"""
        cfg = await self._load_config()
        
        if cfg["public_url_prefix"]:
            return f"{cfg['public_url_prefix']}/{s3_key}"
        
        # 无自定义前缀时，构建默认 S3 URL
        return f"{cfg['endpoint_url'].rstrip('/')}/{cfg['bucket_name']}/{s3_key}"
    
    async def upload_file(self, local_path: str, s3_key: str) -> str:
        """
        上传文件到 S3
        
        Args:
            local_path: 本地文件路径
            s3_key: S3 对象键
            
        Returns:
            str: 公开访问 URL
        """
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"本地文件不存在: {local_path}")
        
        client = await self._get_client()
        bucket = await self.get_bucket_name()
        
        if not bucket:
            raise ValueError("S3 存储桶名称未配置")
        
        try:
            # 根据文件扩展名设置 Content-Type
            content_type = self._get_content_type(local_path)
            extra_args = {"ContentType": content_type}
            
            client.upload_file(local_path, bucket, s3_key, ExtraArgs=extra_args)
            url = await self.get_public_url(s3_key)
            logger.info(f"文件已上传到 S3: {s3_key}")
            return url
        except Exception as e:
            # 捕获 botocore.exceptions.ClientError
            logger.error(f"S3 上传失败: {str(e)}")
            raise
    
    async def download_file(self, s3_key: str, local_path: str) -> str:
        """
        从 S3 下载文件到本地
        
        Args:
            s3_key: S3 对象键
            local_path: 本地保存路径
            
        Returns:
            str: 本地文件路径
        """
        client = await self._get_client()
        bucket = await self.get_bucket_name()
        
        if not bucket:
            raise ValueError("S3 存储桶名称未配置")
        
        try:
            # 确保目录存在
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            
            client.download_file(bucket, s3_key, local_path)
            logger.info(f"文件已从 S3 下载: {s3_key} -> {local_path}")
            return local_path
        except Exception as e:
            # 捕获 botocore.exceptions.ClientError
            logger.error(f"S3 下载失败: {str(e)}")
            raise
    
    async def delete_file(self, s3_key: str) -> bool:
        """
        删除 S3 对象
        
        Args:
            s3_key: S3 对象键
            
        Returns:
            bool: 是否成功
        """
        client = await self._get_client()
        bucket = await self.get_bucket_name()
        
        try:
            client.delete_object(Bucket=bucket, Key=s3_key)
            logger.info(f"S3 对象已删除: {s3_key}")
            return True
        except Exception as e:
            # 捕获 botocore.exceptions.ClientError
            logger.error(f"S3 删除失败: {str(e)}")
            return False
    
    async def exists(self, s3_key: str) -> bool:
        """
        检查 S3 对象是否存在
        
        Args:
            s3_key: S3 对象键
            
        Returns:
            bool: 是否存在
        """
        client = await self._get_client()
        bucket = await self.get_bucket_name()
        
        try:
            client.head_object(Bucket=bucket, Key=s3_key)
            return True
        except Exception:
            # 捕获 botocore.exceptions.ClientError
            return False
    
    async def test_connection(self) -> Dict[str, Any]:
        """
        测试 S3 连接
        
        Returns:
            dict: 测试结果 {success, message, bucket_exists, object_count}
        """
        try:
            client = await self._get_client()
            bucket = await self.get_bucket_name()
            
            if not bucket:
                return {
                    "success": False,
                    "message": "存储桶名称未配置"
                }
            
            # 测试桶是否存在
            try:
                client.head_bucket(Bucket=bucket)
                bucket_exists = True
            except Exception:
                # 捕获 botocore.exceptions.ClientError
                bucket_exists = False
            
            if not bucket_exists:
                return {
                    "success": False,
                    "message": f"存储桶 '{bucket}' 不存在或无权访问"
                }
            
            # 获取对象数量（只获取前1000个统计）
            response = client.list_objects_v2(Bucket=bucket, MaxKeys=1000)
            object_count = response.get("KeyCount", 0)
            
            return {
                "success": True,
                "message": "连接成功",
                "bucket": bucket,
                "object_count": object_count
            }
            
        except ImportError:
            return {
                "success": False,
                "message": "boto3 未安装，请运行: pip install boto3"
            }
        except ValueError as e:
            return {
                "success": False,
                "message": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"连接失败: {str(e)}"
            }
    
    def _get_content_type(self, filepath: str) -> str:
        """根据文件扩展名获取 Content-Type"""
        ext = Path(filepath).suffix.lower()
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml"
        }
        return content_types.get(ext, "application/octet-stream")
    
    def reset_client(self):
        """重置客户端和配置缓存（配置更新后调用）"""
        self._client = None
        self._config_cache = {}
        self._config_cache_time = 0
        logger.info("S3 客户端和配置缓存已重置")


# 全局实例
s3_service = S3Service()
