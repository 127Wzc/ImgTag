#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
ImgTag 主程序入口点
启动 FastAPI 应用，同时托管前端静态文件
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from imgtag.api import api_router
from imgtag.core.config import settings
from imgtag.core.config_cache import config_cache
from imgtag.core.exception_translate import translate_exception
from imgtag.core.exceptions import APIError
from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import get_mime_type, StorageProvider
from imgtag.db.database import close_db, async_session_maker, engine
from imgtag.db.repositories import task_repository, config_repository, storage_endpoint_repository
from imgtag.services.task_queue import task_queue, QUEUE_TASK_TYPES
from imgtag.services.auth_service import init_default_admin
from imgtag.services.backup_service import schedule_daily_backup
from imgtag.services.storage_sync_service import storage_sync_service
from imgtag.services.upload_service import upload_service

logger = get_logger(__name__)

# 前端静态文件目录（Docker 构建时会放置在此）
STATIC_DIR = os.getenv("STATIC_DIR", None)


def run_migrations_sync():
    """同步运行数据库迁移（使用子进程避免事件循环冲突）"""
    import subprocess
    import sys
    
    # 获取项目根目录
    current_file = Path(__file__)
    project_root = current_file.parent.parent.parent
    alembic_ini = project_root / "alembic.ini"
    
    if not alembic_ini.exists():
        logger.warning(f"未找到 alembic.ini: {alembic_ini}，跳过自动迁移")
        return False
    
    try:
        logger.info("检查并运行数据库迁移...")
        
        # 使用子进程调用 alembic，避免在同一进程中产生事件循环冲突
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120  # 2分钟超时
        )
        
        if result.returncode == 0:
            logger.info("数据库迁移完成")
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        logger.info(f"  {line}")
            return True
        else:
            logger.error(f"数据库迁移失败: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("数据库迁移超时")
        return False
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动，初始化资源")
    
    # 自动运行数据库迁移（在线程池中同步执行）
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, run_migrations_sync)
    except Exception as e:
        logger.error(f"数据库迁移执行失败: {e}")
    
    
    # 确保上传目录存在
    upload_path = settings.get_upload_path()
    logger.info(f"上传目录: {upload_path}")
    
    # 清理残留的临时文件（远程上传解析用）
    try:
        cleaned = upload_service.cleanup_temp_dir(max_age_hours=1)  # 清理1小时前的临时文件
        if cleaned > 0:
            logger.info(f"启动时清理了 {cleaned} 个残留临时文件")
    except Exception as e:
        logger.warning(f"清理临时文件失败: {e}")
    
    if STATIC_DIR:
        logger.info(f"前端静态文件目录: {STATIC_DIR}")
    
    # 确保默认配置存在
    try:
        async with async_session_maker() as session:
            await config_repository.ensure_defaults(session)
            await session.commit()
        logger.info("默认配置已确保存在")
        
        # 预加载配置到缓存（确保 get_sync 能正常工作）
        await config_cache.preload()
    except Exception as e:
        logger.warning(f"初始化默认配置失败: {e}")
    
    # 确保默认管理员用户存在
    try:
        async with async_session_maker() as session:
            await init_default_admin(session)
            await session.commit()
    except Exception as e:
        logger.warning(f"初始化默认管理员失败: {e}")
    
    # 恢复未完成的任务
    try:
        async with async_session_maker() as session:
            # 获取未完成的任务（pending 或 processing 状态）
            pending_tasks = await task_repository.get_pending_and_processing(session)
        
        if pending_tasks:
            logger.info(f"发现 {len(pending_tasks)} 个未完成的任务")
            
            # 统计各类型任务数量
            analysis_count = sum(1 for t in pending_tasks if t.type in QUEUE_TASK_TYPES)
            sync_count = sum(1 for t in pending_tasks if t.type == "storage_sync")
            
            # 处理 storage_sync 任务（单独的服务）
            for task_data in pending_tasks:
                if task_data.type == "storage_sync":
                    asyncio.create_task(storage_sync_service._process_sync_task(task_data.id))
            
            # PostgreSQL 队列的 start_processing 内置了恢复机制
            # 会自动处理 analyze_image/rebuild_vector 类型的任务
            if analysis_count > 0:
                asyncio.create_task(task_queue.start_processing())
                logger.info(f"启动队列处理，{analysis_count} 个分析任务待处理")
            
            if sync_count > 0:
                logger.info(f"已启动 {sync_count} 个同步任务")
        else:
            logger.info(f"没有未完成的任务需要恢复")
    except Exception as e:
        logger.error(f"恢复未完成任务失败: {str(e)}")
    
    # 启动每日备份定时任务
    try:
        asyncio.create_task(schedule_daily_backup())
        logger.info("已启动每日备份定时任务（凌晨1点执行）")
    except Exception as e:
        logger.warning(f"启动备份定时任务失败: {e}")
    
    yield
    
    # 应用关闭时释放资源
    logger.info("应用关闭，释放资源")
    await close_db()


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

# ============= 全局异常处理器 =============

@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    """Handle custom APIError with structured response."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle FastAPI HTTPException with unified format (backward compatibility)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail,
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """全局兜底异常处理器（统一错误格式 + 可扩展翻译）。"""
    translated = translate_exception(exc)
    if translated:
        if translated.log_level == "warning":
            logger.warning(f"请求异常(已翻译): path={request.url.path}, error={exc}", exc_info=True)
        elif translated.log_level == "info":
            logger.info(f"请求异常(已翻译): path={request.url.path}, error={exc}")
        elif translated.log_level == "debug":
            logger.debug(f"请求异常(已翻译): path={request.url.path}, error={exc}")
        else:
            logger.error(f"请求异常(已翻译): path={request.url.path}, error={exc}", exc_info=True)

        if translated.dispose_engine:
            try:
                await engine.dispose()
            except Exception as e:
                logger.warning(f"回收数据库连接池失败: {e}")

        api_error = translated.api_error
        return JSONResponse(
            status_code=api_error.status_code,
            content=api_error.to_dict(),
        )

    logger.error(f"未处理异常: path={request.url.path}, error={exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误，请稍后重试",
            }
        },
    )

# 注册 API 路由
app.include_router(api_router, prefix=settings.API_V1_STR)


# ============= 动态本地文件服务 =============
# 统一的文件服务路由，支持任意 bucket 名称，无需重启
# 安全特性：只服务已注册的本地端点，防止目录遍历攻击

@app.get("/data/{bucket}/{file_path:path}")
async def serve_local_file(bucket: str, file_path: str):
    """动态服务本地存储端点的文件。
    
    优点：
    - 无需重启：新建端点立即可用
    - 安全：只服务数据库中注册的 bucket
    - 防止目录遍历攻击
    
    Args:
        bucket: 存储桶名称（对应端点的 bucket_name）
        file_path: 文件路径
    """
    # 规范化路径，防止目录遍历攻击
    # 移除 .. 和多余的 /
    normalized_path = os.path.normpath(file_path).lstrip("/")
    if ".." in normalized_path or normalized_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")
    
    # 查询数据库验证 bucket 是否为注册的本地端点
    async with async_session_maker() as session:
        endpoints = await storage_endpoint_repository.get_all(session)
        
        # 查找匹配的本地端点
        target_endpoint = None
        for ep in endpoints:
            if ep.provider == StorageProvider.LOCAL and ep.bucket_name == bucket:
                target_endpoint = ep
                break
        
        if not target_endpoint:
            raise HTTPException(status_code=404, detail="Storage bucket not found")
        
        # 解析物理路径（所有 bucket 都在 DATA_DIR 下）
        data_path = settings.get_data_path()
        if os.path.isabs(bucket):
            base_path = Path(bucket)
        else:
            base_path = data_path / bucket
        
        full_path = base_path / normalized_path
        
        # 安全检查：确保路径在 base_path 内（防止符号链接逃逸）
        try:
            full_path = full_path.resolve()
            base_path = base_path.resolve()
            if not str(full_path).startswith(str(base_path)):
                raise HTTPException(status_code=403, detail="Access denied")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid path")
        
        # 检查文件是否存在
        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        
        # 返回文件
        return FileResponse(
            str(full_path),
            media_type=_get_media_type(full_path.suffix),
        )


def _get_media_type(suffix: str) -> str:
    """根据文件扩展名返回 MIME 类型。"""
    return get_mime_type(suffix)

# 如果存在前端静态文件目录，则托管前端
if STATIC_DIR and Path(STATIC_DIR).exists():
    # 挂载 assets 目录
    assets_path = Path(STATIC_DIR) / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """SPA 路由：优先返回静态文件，否则返回 index.html"""
        # 排除 API 和已挂载的路径
        if full_path.startswith(("api/", "uploads/", "data/", "assets/", "docs", "redoc", "openapi.json")):
            return None
        
        # 检查是否为静态文件（logo.png, vite.svg 等）
        static_file = Path(STATIC_DIR) / full_path
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))
        
        # 其他路径返回 index.html（SPA 前端路由）
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


def main():
    """命令行入口点"""
    logger.info(f"启动 {settings.PROJECT_NAME} 服务")
    uvicorn.run(
        "imgtag.main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True
    )


if __name__ == "__main__":
    main()
