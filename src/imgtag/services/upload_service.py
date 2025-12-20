#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
上传服务
处理本地文件上传和远程图片获取
"""

import time
import uuid
import mimetypes
from pathlib import Path
from typing import Tuple, Optional
import aiofiles
import httpx

from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger, get_perf_logger

logger = get_logger(__name__)
perf_logger = get_perf_logger()


class UploadService:
    """上传服务类"""
    
    _instance = None
    
    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(UploadService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化上传服务"""
        if getattr(self, "_initialized", False):
            return
        
        logger.info("初始化上传服务")
        self._upload_dir = settings.get_upload_path()
        self._initialized = True
    
    def _get_extension(self, filename: str) -> str:
        """获取文件扩展名"""
        ext = Path(filename).suffix.lower().lstrip(".")
        return ext if ext else "jpg"
    
    def _validate_extension(self, extension: str) -> bool:
        """验证文件扩展名是否允许"""
        return extension.lower() in settings.ALLOWED_EXTENSIONS
    
    def _generate_filename(self, extension: str) -> str:
        """生成唯一文件名"""
        return f"{uuid.uuid4().hex}.{extension}"
    
    async def save_uploaded_file(
        self, 
        file_content: bytes, 
        original_filename: str
    ) -> Tuple[str, str]:
        """保存上传的文件
        
        Args:
            file_content: 文件内容
            original_filename: 原始文件名
            
        Returns:
            Tuple[str, str]: (保存的文件路径, 访问 URL)
        """
        start_time = time.time()
        logger.info(f"保存上传文件: {original_filename}, 大小: {len(file_content)} 字节")
        
        try:
            # 验证文件大小
            if len(file_content) > settings.MAX_UPLOAD_SIZE:
                raise ValueError(f"文件太大，最大允许 {settings.MAX_UPLOAD_SIZE / 1024 / 1024:.1f}MB")
            
            # 获取并验证扩展名
            extension = self._get_extension(original_filename)
            if not self._validate_extension(extension):
                raise ValueError(f"不支持的文件类型: {extension}")
            
            # 生成新文件名
            new_filename = self._generate_filename(extension)
            file_path = self._upload_dir / new_filename
            
            # 异步写入文件
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(file_content)
            
            # 生成访问 URL
            access_url = f"/uploads/{new_filename}"
            
            process_time = time.time() - start_time
            perf_logger.info(f"文件保存耗时: {process_time:.4f}秒")
            logger.info(f"文件保存成功: {file_path}")
            
            return str(file_path), access_url
            
        except Exception as e:
            logger.error(f"保存文件失败: {str(e)}")
            raise
    
    async def fetch_remote_image(self, url: str) -> Tuple[bytes, str]:
        """获取远程图片
        
        Args:
            url: 图片 URL
            
        Returns:
            Tuple[bytes, str]: (图片内容, MIME 类型)
        """
        start_time = time.time()
        logger.info(f"获取远程图片: {url}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                content = response.content
                
                # 获取 MIME 类型
                content_type = response.headers.get("content-type", "image/jpeg")
                mime_type = content_type.split(";")[0].strip()
                
                # 验证是否为图片
                if not mime_type.startswith("image/"):
                    raise ValueError(f"URL 返回的不是图片: {mime_type}")
                
                process_time = time.time() - start_time
                perf_logger.info(f"远程图片获取耗时: {process_time:.4f}秒, 大小: {len(content)} 字节")
                
                return content, mime_type
                
        except httpx.HTTPError as e:
            logger.error(f"获取远程图片失败: {str(e)}")
            raise ValueError(f"无法获取远程图片: {str(e)}")
        except Exception as e:
            logger.error(f"获取远程图片失败: {str(e)}")
            raise
    
    async def save_remote_image(self, url: str) -> Tuple[str, str, bytes]:
        """获取并保存远程图片
        
        Args:
            url: 图片 URL
            
        Returns:
            Tuple[str, str, bytes]: (保存的文件路径, 访问 URL, 图片内容)
        """
        start_time = time.time()
        logger.info(f"获取并保存远程图片: {url}")
        
        try:
            # 获取远程图片
            content, mime_type = await self.fetch_remote_image(url)
            
            # 根据 MIME 类型确定扩展名
            ext_map = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/gif": "gif",
                "image/webp": "webp",
                "image/bmp": "bmp",
            }
            extension = ext_map.get(mime_type, "jpg")
            
            # 验证扩展名
            if not self._validate_extension(extension):
                raise ValueError(f"不支持的图片类型: {mime_type}")
            
            # 生成新文件名
            new_filename = self._generate_filename(extension)
            file_path = self._upload_dir / new_filename
            
            # 异步写入文件
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)
            
            # 生成访问 URL
            access_url = f"/uploads/{new_filename}"
            
            process_time = time.time() - start_time
            perf_logger.info(f"远程图片保存总耗时: {process_time:.4f}秒")
            logger.info(f"远程图片保存成功: {file_path}")
            
            return str(file_path), access_url, content
            
        except Exception as e:
            logger.error(f"保存远程图片失败: {str(e)}")
            raise
    
    def get_mime_type(self, filename: str) -> str:
        """获取文件的 MIME 类型"""
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or "image/jpeg"


# 全局实例
upload_service = UploadService()
