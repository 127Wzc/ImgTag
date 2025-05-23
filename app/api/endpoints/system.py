#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
系统API端点
处理与系统相关的请求
"""

from fastapi import APIRouter, HTTPException, Depends

from app.models.image import StatusResponse
from app.db.pg_vector import PGVectorDB
from app.core.logging_config import get_logger
from app.core.config import settings

# 获取日志记录器
logger = get_logger(__name__)

# 创建全局数据库实例
db = PGVectorDB()

router = APIRouter()

# 依赖项
def get_db():
    """依赖项：获取数据库连接"""
    return db

@router.get("/status/", response_model=StatusResponse)
async def get_status(db: PGVectorDB = Depends(get_db)):
    """获取系统状态"""
    try:
        image_count = db.count_images()
        return StatusResponse(
            image_count=image_count,
            status="正常运行中",
            version=settings.PROJECT_VERSION
        )
    except Exception as e:
        logger.error(f"获取状态信息失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取状态信息失败: {str(e)}")

@router.get("/health/")
async def health_check():
    """健康检查端点"""
    return {"status": "ok"} 