#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ImgTag主程序入口点
启动FastAPI应用
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from contextlib import asynccontextmanager

from app.api.api_v1 import api_router
from app.core.config import settings
from app.core.logging_config import get_logger
from app.db.pg_vector import PGVectorDB
from app.services.text_embedding import TextEmbedding

# 获取日志记录器
logger = get_logger(__name__)

# 应用启动和关闭时的生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理
    
    在应用启动时初始化必要的资源，在应用关闭时释放资源
    """
    # 应用启动时执行
    logger.info("应用启动，初始化资源")
    
    # 预初始化数据库连接和模型，确保它们在第一个请求前就准备好
    db = PGVectorDB()
    embedding_model = TextEmbedding()
    
    yield
    
    # 应用关闭时执行
    logger.info("应用关闭，释放资源")
    # 关闭数据库连接池
    PGVectorDB.close_pool()

# 创建FastAPI应用
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.PROJECT_DESCRIPTION,
    version=settings.PROJECT_VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
    lifespan=lifespan
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有源，生产环境中应该限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册API路由
app.include_router(api_router, prefix=settings.API_V1_STR)

# 根路由
@app.get("/")
async def root():
    """根路由，返回服务信息和API文档链接"""
    return {
        "name": settings.PROJECT_NAME,
        "description": settings.PROJECT_DESCRIPTION,
        "version": settings.PROJECT_VERSION,
        "documentation": f"{settings.API_V1_STR}/docs",
        "redoc": f"{settings.API_V1_STR}/redoc"
    }

# 程序入口点
if __name__ == "__main__":
    logger.info(f"启动 {settings.PROJECT_NAME} 服务")
    # 禁用热重载可以避免双重初始化问题，但会影响开发体验
    # 建议在生产环境中使用reload=False
    reload_mode = True  # 开发环境设置为True，生产环境设置为False
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload_mode) 