#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ImgTag 主程序入口点
启动 FastAPI 应用，同时托管前端静态文件
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from imgtag.api import api_router
from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger
from imgtag.db import db, PGVectorDB

logger = get_logger(__name__)

# 前端静态文件目录（Docker 构建时会放置在此）
STATIC_DIR = os.getenv("STATIC_DIR", None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动，初始化资源")
    
    # 确保上传目录存在
    upload_path = settings.get_upload_path()
    logger.info(f"上传目录: {upload_path}")
    
    if STATIC_DIR:
        logger.info(f"前端静态文件目录: {STATIC_DIR}")
    
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
    docs_url="/docs",
    redoc_url="/redoc",
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

# 如果存在前端静态文件目录，则托管前端
if STATIC_DIR and Path(STATIC_DIR).exists():
    # 挂载 assets 目录
    assets_path = Path(STATIC_DIR) / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """SPA 路由：所有非 API 请求返回 index.html"""
        # 排除 API 和已挂载的路径
        if full_path.startswith(("api/", "uploads/", "assets/", "docs", "redoc", "openapi.json")):
            return None
        
        index_path = Path(STATIC_DIR) / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"error": "Frontend not found"}
else:
    @app.get("/")
    async def root():
        """根路由，返回服务信息和 API 文档链接"""
        return {
            "name": settings.PROJECT_NAME,
            "description": settings.PROJECT_DESCRIPTION,
            "version": settings.PROJECT_VERSION,
            "documentation": "/docs",
            "redoc": "/redoc"
        }


if __name__ == "__main__":
    logger.info(f"启动 {settings.PROJECT_NAME} 服务")
    uvicorn.run(
        "imgtag.main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True
    )

