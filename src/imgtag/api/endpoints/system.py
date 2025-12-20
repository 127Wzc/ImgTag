#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
系统 API 端点
系统状态和健康检查
"""

from typing import Dict, Any
from fastapi import APIRouter

from imgtag.db import db
from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


from imgtag.services.embedding_service import embedding_service

@router.get("/status", response_model=Dict[str, Any])
async def get_system_status():
    """获取系统状态"""
    logger.info("获取系统状态")
    
    try:
        image_count = db.count_images()
        
        return {
            "status": "running",
            "version": settings.PROJECT_VERSION,
            "image_count": image_count,
            "vision_model": settings.VISION_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_dimensions": embedding_service.get_dimensions(),
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy"}


@router.get("/config", response_model=Dict[str, Any])
async def get_config():
    """获取当前配置（不含敏感信息）"""
    return {
        "project_name": settings.PROJECT_NAME,
        "project_version": settings.PROJECT_VERSION,
        "vision_api_base_url": settings.VISION_API_BASE_URL,
        "vision_model": settings.VISION_MODEL,
        "embedding_api_base_url": settings.EMBEDDING_API_BASE_URL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
        "max_upload_size": settings.MAX_UPLOAD_SIZE,
        "allowed_extensions": list(settings.ALLOWED_EXTENSIONS),
    }
