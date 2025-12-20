#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ImgTag 主程序入口点
启动 FastAPI 应用
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from imgtag.api import api_router
from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.db import db, PGVectorDB

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动，初始化资源")
    
    # 确保上传目录存在
    upload_path = settings.get_upload_path()
    logger.info(f"上传目录: {upload_path}")
    
    yield
    
    # 应用关闭时释放资源
    logger.info("应用关闭，释放资源")
    PGVectorDB.close_pool()


# 创建 FastAPI 应用
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.PROJECT_VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境中应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(api_router, prefix=settings.API_V1_STR)

# 挂载静态文件目录 (上传的图片)
upload_path = settings.get_upload_path()
app.mount("/uploads", StaticFiles(directory=str(upload_path)), name="uploads")


@app.get("/")
async def root():
    """根路由，返回服务信息和 API 文档链接"""
    return {
        "name": settings.PROJECT_NAME,
        "description": settings.PROJECT_DESCRIPTION,
        "version": settings.PROJECT_VERSION,
        "documentation": f"{settings.API_V1_STR}/docs",
        "redoc": f"{settings.API_V1_STR}/redoc"
    }


if __name__ == "__main__":
    logger.info(f"启动 {settings.PROJECT_NAME} 服务")
    uvicorn.run(
        "imgtag.main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True
    )
