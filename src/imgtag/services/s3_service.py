#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
S3 存储服务
管理员备份文件到 S3 兼容存储
"""

import os
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from imgtag.db.config_db import config_db
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)


class S3Service:
    """S3 存储服务 - 单例模式"""
    
    _instance = None
    _client = None
    
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
    
    def _get_client(self):
        """获取 boto3 客户端（懒加载）"""
        if self._client is not None:
            return self._client
        
        endpoint_url = config_db.get("s3_endpoint_url", "")
        access_key = config_db.get("s3_access_key_id", "")
        secret_key = config_db.get("s3_secret_access_key", "")
        region = config_db.get("s3_region", "us-east-1")
        
        if not endpoint_url or not access_key or not secret_key:
            raise ValueError("S3 配置不完整，请检查 endpoint_url, access_key_id, secret_access_key")
        
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
        logger.info(f"S3 客户端已创建: {endpoint_url}")
        return self._client
    
    def is_enabled(self) -> bool:
        """检查 S3 是否启用"""
        return config_db.get("s3_enabled", "false").lower() == "true"
    
    def get_bucket_name(self) -> str:
        """获取存储桶名称"""
        return config_db.get("s3_bucket_name", "")
    
    def generate_s3_key(self, filename: str) -> str:
        """
        根据文件名生成 S3 对象键
        
        格式: {prefix}/{year}/{month}/{filename}
        例如: imgtag/2024/12/abc123.jpg
        """
        prefix = config_db.get("s3_path_prefix", "imgtag/").rstrip("/")
        now = datetime.now()
        return f"{prefix}/{now.year}/{now.month:02d}/{filename}"
    
    def get_public_url(self, s3_key: str) -> str:
        """获取公开访问 URL"""
        public_prefix = config_db.get("s3_public_url_prefix", "").rstrip("/")
        if public_prefix:
            return f"{public_prefix}/{s3_key}"
        
        # 无自定义前缀时，构建默认 S3 URL
        endpoint = config_db.get("s3_endpoint_url", "").rstrip("/")
        bucket = self.get_bucket_name()
        return f"{endpoint}/{bucket}/{s3_key}"
    
    def upload_file(self, local_path: str, s3_key: str) -> str:
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
        
        client = self._get_client()
        bucket = self.get_bucket_name()
        
        if not bucket:
            raise ValueError("S3 存储桶名称未配置")
        
        try:
            # 根据文件扩展名设置 Content-Type
            content_type = self._get_content_type(local_path)
            extra_args = {"ContentType": content_type}
            
            client.upload_file(local_path, bucket, s3_key, ExtraArgs=extra_args)
            url = self.get_public_url(s3_key)
            logger.info(f"文件已上传到 S3: {s3_key}")
            return url
        except ClientError as e:
            logger.error(f"S3 上传失败: {str(e)}")
            raise
    
    def download_file(self, s3_key: str, local_path: str) -> str:
        """
        从 S3 下载文件到本地
        
        Args:
            s3_key: S3 对象键
            local_path: 本地保存路径
            
        Returns:
            str: 本地文件路径
        """
        client = self._get_client()
        bucket = self.get_bucket_name()
        
        if not bucket:
            raise ValueError("S3 存储桶名称未配置")
        
        try:
            # 确保目录存在
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            
            client.download_file(bucket, s3_key, local_path)
            logger.info(f"文件已从 S3 下载: {s3_key} -> {local_path}")
            return local_path
        except ClientError as e:
            logger.error(f"S3 下载失败: {str(e)}")
            raise
    
    def delete_file(self, s3_key: str) -> bool:
        """
        删除 S3 对象
        
        Args:
            s3_key: S3 对象键
            
        Returns:
            bool: 是否成功
        """
        client = self._get_client()
        bucket = self.get_bucket_name()
        
        try:
            client.delete_object(Bucket=bucket, Key=s3_key)
            logger.info(f"S3 对象已删除: {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"S3 删除失败: {str(e)}")
            return False
    
    def exists(self, s3_key: str) -> bool:
        """
        检查 S3 对象是否存在
        
        Args:
            s3_key: S3 对象键
            
        Returns:
            bool: 是否存在
        """
        client = self._get_client()
        bucket = self.get_bucket_name()
        
        try:
            client.head_object(Bucket=bucket, Key=s3_key)
            return True
        except ClientError:
            return False
    
    def test_connection(self) -> Dict[str, Any]:
        """
        测试 S3 连接
        
        Returns:
            dict: 测试结果 {success, message, bucket_exists, object_count}
        """
        try:
            client = self._get_client()
            bucket = self.get_bucket_name()
            
            if not bucket:
                return {
                    "success": False,
                    "message": "存储桶名称未配置"
                }
            
            # 测试桶是否存在
            try:
                client.head_bucket(Bucket=bucket)
                bucket_exists = True
            except ClientError:
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
            
        except NoCredentialsError:
            return {
                "success": False,
                "message": "S3 凭证无效"
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
        """重置客户端（配置更新后调用）"""
        self._client = None
        logger.info("S3 客户端已重置")


# 全局实例
s3_service = S3Service()
