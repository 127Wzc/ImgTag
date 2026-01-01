#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
上传服务
处理本地文件上传和远程图片获取
"""

import asyncio
import io
import time
import uuid
import mimetypes
from pathlib import Path
from typing import Tuple, Optional
import aiofiles
import httpx
import os

from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.core.storage_constants import get_extension_from_mime

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
    
    @property
    def temp_dir(self) -> Path:
        """临时文件目录（用于远程端点上传时解析图片信息）"""
        tmp_path = self._upload_dir.parent / "tmp"
        tmp_path.mkdir(exist_ok=True)
        return tmp_path
    
    async def save_temp_file(
        self, 
        file_content: bytes, 
        file_hash: str, 
        extension: str
    ) -> str:
        """保存临时文件（用于解析图片信息）
        
        Args:
            file_content: 文件内容
            file_hash: 文件哈希
            extension: 文件扩展名
            
        Returns:
            str: 临时文件路径
        """
        tmp_filename = f"{file_hash}.{extension}"
        tmp_path = self.temp_dir / tmp_filename
        
        async with aiofiles.open(tmp_path, "wb") as f:
            await f.write(file_content)
        
        logger.debug(f"保存临时文件: {tmp_path}")
        return str(tmp_path)
    
    async def delete_temp_file(self, tmp_path: str) -> bool:
        """删除临时文件
        
        Args:
            tmp_path: 临时文件路径
            
        Returns:
            bool: 是否成功删除
        """
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                logger.debug(f"删除临时文件: {tmp_path}")
                return True
            return False
        except Exception as e:
            logger.warning(f"删除临时文件失败: {tmp_path}, 错误: {e}")
            return False
    
    def cleanup_temp_dir(self, max_age_hours: int = 24) -> int:
        """清理临时目录中的旧文件
        
        Args:
            max_age_hours: 最大保留时间（小时）
            
        Returns:
            int: 删除的文件数量
        """
        deleted = 0
        cutoff_time = time.time() - (max_age_hours * 3600)
        
        if not self.temp_dir.exists():
            return 0
        
        for file_path in self.temp_dir.iterdir():
            if file_path.is_file():
                try:
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        deleted += 1
                except Exception as e:
                    logger.warning(f"清理临时文件失败: {file_path}, 错误: {e}")
        
        if deleted > 0:
            logger.info(f"清理了 {deleted} 个过期临时文件 (>{max_age_hours}h)")
        
        return deleted
    
    def extract_image_dimensions(self, file_content: bytes) -> Tuple[Optional[int], Optional[int]]:
        """从图片内容提取宽高
        
        Args:
            file_content: 图片字节数据
            
        Returns:
            Tuple[Optional[int], Optional[int]]: (宽度, 高度)，失败返回 (None, None)
        """
        try:
            from PIL import Image
            # 设置解压缩炸弹保护（默认约 178M 像素，约 16K x 16K）
            Image.MAX_IMAGE_PIXELS = 178956970
            with Image.open(io.BytesIO(file_content)) as img:
                width, height = img.size
                logger.debug(f"提取图片分辨率: {width}x{height}")
                return width, height
        except Image.DecompressionBombError:
            logger.warning("图片尺寸过大，跳过分辨率提取")
            return None, None
        except Exception as e:
            logger.warning(f"提取图片分辨率失败: {str(e)}")
            return None, None
    
    @staticmethod
    def get_resolution_level(width: Optional[int], height: Optional[int]) -> str:
        """根据宽高获取分辨率等级
        
        Args:
            width: 图片宽度
            height: 图片高度
            
        Returns:
            str: 分辨率等级 (8K/4K/2K/1080p/720p/SD/unknown)
        """
        if width is None or height is None:
            return "unknown"
        
        max_dim = max(width, height)
        
        if max_dim >= 7680:
            return "8K"
        elif max_dim >= 3840:
            return "4K"
        elif max_dim >= 2560:
            return "2K"
        elif max_dim >= 1920:
            return "1080p"
        elif max_dim >= 1280:
            return "720p"
        else:
            return "SD"
    
    async def save_uploaded_file(
        self, 
        file_content: bytes, 
        original_filename: str
    ) -> Tuple[str, str, str, Optional[int], Optional[int]]:
        """保存上传的文件
        
        Args:
            file_content: 文件内容
            original_filename: 原始文件名
            
        Returns:
            Tuple[str, str, str, Optional[int], Optional[int]]: 
                (保存的文件路径, 访问 URL, 真实文件类型, 宽度, 高度)
        """
        start_time = time.time()
        logger.info(f"保存上传文件: {original_filename}, 大小: {len(file_content)} 字节")
        
        try:
            # 使用配置常量获取最大上传大小 (默认 10MB)
            max_size_bytes = settings.MAX_UPLOAD_SIZE
            
            # 验证文件大小
            if len(file_content) > max_size_bytes:
                raise ValueError(f"文件太大，最大允许 {max_size_mb}MB")
            
            # 获取并验证扩展名
            extension = self._get_extension(original_filename)
            if not self._validate_extension(extension):
                raise ValueError(f"不支持的文件类型: {extension}")
            
            # 使用 PIL 检测真实的图片格式和分辨率（线程池执行，避免阻塞）
            real_format = extension  # 默认使用扩展名
            width, height = None, None
            try:
                def _detect_format_and_dimensions(content: bytes):
                    from PIL import Image
                    img = Image.open(io.BytesIO(content))
                    w, h = img.size
                    detected_format = img.format.lower() if img.format else None
                    return w, h, detected_format
                
                width, height, detected_format = await asyncio.to_thread(
                    _detect_format_and_dimensions, file_content
                )
                logger.debug(f"图片分辨率: {width}x{height}")
                
                # 检测格式
                if detected_format:
                    # 标准化格式名称（PIL 内部格式 -> 常用扩展名）
                    format_map = {
                        'jpeg': 'jpg',
                        'mpo': 'jpg',       # 多图 JPEG
                        'png': 'png',
                        'gif': 'gif',
                        'webp': 'webp',
                        'bmp': 'bmp',
                        'tiff': 'tiff',
                        'ico': 'ico',
                        'heif': 'heic',     # HEIF/HEIC 格式
                        'heic': 'heic',
                        'avif': 'avif',     # AV1 图像格式
                        'svg': 'svg',
                        'psd': 'psd',       # Photoshop
                        'pcx': 'pcx',
                        'ppm': 'ppm',
                        'tga': 'tga',
                        'dds': 'dds',       # DirectDraw Surface
                        'icns': 'icns',     # macOS 图标
                    }
                    real_format = format_map.get(detected_format, detected_format)
                    logger.debug(f"PIL 检测到格式: {detected_format} -> {real_format}")
            except Exception as e:
                logger.warning(f"PIL 检测图片失败: {str(e)}，使用扩展名: {extension}")
            
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
            logger.info(f"文件保存成功: {file_path}, 格式: {real_format}, 分辨率: {width}x{height}")
            
            return str(file_path), access_url, real_format, width, height
            
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
            
            # 根据 MIME 类型确定扩展名（使用统一常量）
            extension = get_extension_from_mime(mime_type)
            
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
