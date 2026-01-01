#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
核心配置文件
使用 Pydantic Settings 管理所有配置项
"""

import os
from pathlib import Path
from typing import Optional
from importlib.metadata import version, PackageNotFoundError

from pydantic_settings import BaseSettings
from pydantic import Field

# 从 pyproject.toml 读取版本号
try:
    _version = version("imgtag")
except PackageNotFoundError:
    _version = "0.0.5"


class Settings(BaseSettings):
    """应用配置类"""
    
    # API 配置
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "ImgTag API"
    PROJECT_DESCRIPTION: str = "图像标签与向量搜索系统 - 支持OpenAI标准视觉模型"
    PROJECT_VERSION: str = _version
    
    # 数据库配置
    PG_CONNECTION_STRING: str = Field(
        default="postgres://postgres:postgres@localhost:5432/imgtag",
        description="PostgreSQL 连接字符串"
    )
    
    # 视觉模型配置 (OpenAI 兼容)
    VISION_API_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        description="视觉模型 API 基础 URL"
    )
    VISION_API_KEY: str = Field(
        default="",
        description="视觉模型 API 密钥"
    )
    VISION_MODEL: str = Field(
        default="gpt-4o-mini",
        description="视觉模型名称"
    )
    
    # 嵌入模型配置 (OpenAI 兼容)
    EMBEDDING_API_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        description="嵌入模型 API 基础 URL"
    )
    EMBEDDING_API_KEY: str = Field(
        default="",
        description="嵌入模型 API 密钥"
    )
    EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-small",
        description="嵌入模型名称"
    )
    EMBEDDING_DIMENSIONS: int = Field(
        default=1536,
        description="嵌入向量维度"
    )
    
    # 文件存储配置
    DATA_DIR: Path = Field(
        default=Path("data"),
        description="统一数据存储目录（所有本地 bucket 的基础目录）"
    )
    UPLOAD_DIR: Path = Field(
        default=Path("uploads"),
        description="默认上传目录（相对于 DATA_DIR）"
    )
    MAX_UPLOAD_SIZE: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="最大上传文件大小 (字节)"
    )
    ALLOWED_EXTENSIONS: set = Field(
        default={"jpg", "jpeg", "png", "gif", "webp", "bmp"},
        description="允许的图片扩展名"
    )
    
    # 应用配置
    DEFAULT_SEARCH_LIMIT: int = 10
    DEFAULT_SIMILARITY_THRESHOLD: float = 0.3  # BGE-small 中文模型相似度通常较低
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    
    # 图像分析配置
    VISION_PROMPT: str = Field(
        default="""请分析这张图片，并按以下格式返回JSON响应:
{
    "tags": ["标签1", "标签2", "标签3", ...],
    "description": "详细的图片描述文本"
}

要求：
1. tags: 提取5-10个关键标签，使用中文
2. description: 用中文详细描述图片内容，包括主体、场景、颜色、氛围等

请只返回JSON格式，不要添加任何其他文字。""",
        description="视觉模型分析提示词"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
    
    def get_data_path(self) -> Path:
        """获取统一数据目录的绝对路径
        
        所有本地存储 bucket 都在此目录下，Docker 只需挂载此目录。
        """
        data_path = self.DATA_DIR
        if not data_path.is_absolute():
            # 相对于项目根目录
            data_path = Path(__file__).parent.parent.parent.parent / data_path
        data_path.mkdir(parents=True, exist_ok=True)
        return data_path
    
    def get_upload_path(self) -> Path:
        """获取默认上传目录的绝对路径
        
        默认上传目录位于 DATA_DIR/UPLOAD_DIR 下。
        """
        upload_path = self.get_data_path() / self.UPLOAD_DIR
        upload_path.mkdir(parents=True, exist_ok=True)
        return upload_path


# 创建全局配置实例
settings = Settings()
