#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
核心配置文件
集中管理所有配置项，包括API配置
"""

import os
from pydantic import BaseModel
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Settings(BaseModel):
    """应用配置类"""
    
    # API配置
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "ImgTag API"
    PROJECT_DESCRIPTION: str = "基于向量数据库的图像标签和描述搜索系统"
    PROJECT_VERSION: str = "1.0.0"
    
    # 数据库配置
    PG_CONNECTION_STRING: str = os.getenv("PG_CONNECTION_STRING", "")
    
    # 模型配置
    MODEL_NAME: str = "BAAI/bge-small-zh-v1.5"
    MODEL_DIR: str = "./models"
    
    # 应用配置
    DEFAULT_SAMPLE_COUNT: int = 10
    DEFAULT_SEARCH_LIMIT: int = 10
    DEFAULT_SIMILARITY_THRESHOLD: float = 0.7
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    PERFORMANCE_LOG_ENABLED: bool = True

# 创建全局配置实例
settings = Settings() 