#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Vector management API endpoints.

Handles vector data maintenance and rebuilding.
"""

import asyncio
import subprocess
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.db import get_async_session
from imgtag.db.database import engine
from imgtag.db.repositories import image_repository, config_repository
from imgtag.services import embedding_service
from imgtag.services.vector_rebuild_service import vector_rebuild_service

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()

# 重建状态由 Service 统一维护。
rebuild_status = vector_rebuild_service.status

# Install status
install_status = {
    "is_running": False,
    "success": None,
    "message": "",
    "output": "",
}


async def get_db_vector_dimensions(session: AsyncSession) -> int:
    """读取数据库向量维度。"""
    return await image_repository.get_embedding_dimensions(session)


@router.get("/status", response_model=dict[str, Any])
async def get_vector_status(
    session: AsyncSession = Depends(get_async_session),
):
    """Get vector data status.

    Args:
        session: Database session.

    Returns:
        Vector status including counts and dimensions.
    """
    try:
        image_count = await image_repository.count_images(session)
        mode = await config_cache.get("embedding_mode", "local") or "local"

        if mode == "local":
            model = await config_cache.get("embedding_local_model", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5"
            if "small" in model:
                dimensions = 512
            elif "base" in model:
                dimensions = 768
            else:
                dimensions = 512
        else:
            model = await config_cache.get("embedding_model", "text-embedding-3-small") or "text-embedding-3-small"
            dim_str = await config_cache.get("embedding_dimensions", "1536")
            dimensions = int(dim_str) if dim_str else 1536

        db_dimensions = await get_db_vector_dimensions(session)

        return {
            "image_count": image_count,
            "embedding_mode": mode,
            "embedding_model": model,
            "embedding_dimensions": dimensions,
            "db_dimensions": db_dimensions,
            "dimensions_match": dimensions == db_dimensions,
            "rebuild_status": rebuild_status,
        }
    except Exception as e:
        logger.error(f"获取向量状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check-local", response_model=dict[str, Any])
async def check_local_dependencies(
    admin: dict = Depends(require_admin),
):
    """Check local embedding model dependencies (admin only).

    Args:
        admin: Admin user.

    Returns:
        Dependency status.
    """
    result = {
        "installed": False,
        "model_loaded": False,
        "model_name": None,
        "dimensions": None,
        "error": None,
    }

    try:
        import onnxruntime
        import transformers

        result["installed"] = True

        model_name = await config_cache.get("embedding_local_model", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5"
        result["model_name"] = model_name

        try:
            model = await embedding_service._get_local_model()
            result["model_loaded"] = True
            result["dimensions"] = model.get_sentence_embedding_dimension()
        except Exception as e:
            result["error"] = f"模型加载失败: {e}"

    except ImportError:
        result["error"] = "ONNX 依赖未安装。请运行: uv sync --extra local"

    return result


@router.post("/install-local", response_model=dict[str, Any])
async def install_local_dependencies(
    background_tasks: BackgroundTasks,
    admin: dict = Depends(require_admin),
):
    """Install local embedding dependencies (admin only).

    Note: Not recommended for production. Use: uv sync --extra local

    Args:
        background_tasks: FastAPI background tasks.
        admin: Admin user.

    Returns:
        Installation status.
    """
    global install_status

    try:
        import onnxruntime
        import transformers

        return {
            "status": "already_installed",
            "message": "ONNX 依赖已安装",
            "installed": True,
        }
    except ImportError:
        pass

    logger.warning("通过 Web API 安装依赖存在安全风险，建议手动运行: uv sync --extra local")

    if install_status["is_running"]:
        return {
            "status": "installing",
            "message": "依赖正在安装中，请稍候...",
            "installed": False,
        }

    install_status = {
        "is_running": True,
        "success": None,
        "message": "正在安装 ONNX Runtime（约 200MB）...",
        "output": "",
    }

    background_tasks.add_task(install_local_task)

    return {
        "status": "started",
        "message": "依赖安装已启动（建议手动运行: uv sync --extra local）",
        "installed": False,
    }


@router.get("/install-local/status", response_model=dict[str, Any])
async def get_install_status():
    """Get local dependency installation status.

    Returns:
        Installation status.
    """
    installed = False
    try:
        import onnxruntime
        import transformers

        installed = True
    except ImportError:
        pass

    return {**install_status, "installed": installed}


async def install_local_task():
    """Background task: install local dependencies."""
    global install_status

    logger.info("开始安装本地嵌入模型依赖...")

    try:
        result = subprocess.run(
            ["uv", "sync", "--extra", "local"],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode == 0:
            install_status["success"] = True
            install_status["message"] = "依赖安装成功！"
            install_status["output"] = result.stdout
            logger.info("本地嵌入模型依赖安装成功")
        else:
            install_status["success"] = False
            install_status["message"] = f"安装失败: {result.stderr}"
            install_status["output"] = result.stderr
            logger.error(f"依赖安装失败: {result.stderr}")

    except subprocess.TimeoutExpired:
        install_status["success"] = False
        install_status["message"] = "安装超时（超过10分钟）"
        logger.error("依赖安装超时")
    except FileNotFoundError:
        install_status["success"] = False
        install_status["message"] = "找不到 uv 命令，请确保 uv 已安装"
        logger.error("找不到 uv 命令")
    except Exception as e:
        install_status["success"] = False
        install_status["message"] = f"安装出错: {e}"
        logger.error(f"依赖安装出错: {e}")
    finally:
        install_status["is_running"] = False


@router.post("/resize-table", response_model=dict[str, str])
async def resize_vector_table(
    background_tasks: BackgroundTasks,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Resize vector table to match current dimensions (admin only).

    Args:
        admin: Admin user.
        session: Database session.

    Returns:
        Resize result.
    """
    try:
        mode = await config_cache.get("embedding_mode", "local") or "local"

        if mode == "local":
            model_name = await config_cache.get("embedding_local_model", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5"
            if "small" in model_name:
                new_dim = 512
            elif "base" in model_name:
                new_dim = 768
            else:
                new_dim = 512
        else:
            dim_str = await config_cache.get("embedding_dimensions", "1536")
            new_dim = int(dim_str) if dim_str else 1536

        current_dim = await get_db_vector_dimensions(session)

        if current_dim == new_dim:
            return {"message": f"数据库维度已经是 {new_dim}，无需修改"}

        logger.info(f"修改向量维度: {current_dim} -> {new_dim}")

        # Use raw connection for DDL
        conn = await session.connection()
        await conn.execute(text("DROP INDEX IF EXISTS idx_images_embedding"))
        await conn.execute(text(f"""
            ALTER TABLE images 
            ALTER COLUMN embedding TYPE vector({new_dim})
            USING (ARRAY_FILL(0::float, ARRAY[{new_dim}])::vector({new_dim}))
        """))
        await conn.execute(text(f"""
            CREATE INDEX idx_images_embedding ON public.images 
            USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
        """))

        await config_repository.set_value(session, "embedding_dimensions", str(new_dim))
        await session.commit()
        await config_cache.refresh()

        # ALTER TABLE 会导致 asyncpg 预编译语句缓存失效；主动回收连接池，避免后续请求随机 500
        background_tasks.add_task(engine.dispose)

        logger.info(f"向量维度修改成功: {new_dim}")
        return {"message": f"数据库向量维度已修改为 {new_dim}，请重建向量数据"}

    except Exception as e:
        logger.error(f"修改向量维度失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rebuild", response_model=dict[str, str])
async def start_rebuild(
    background_tasks: BackgroundTasks,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """准备并启动全库向量重建，需管理员权限。"""
    try:
        expected_dim = await vector_rebuild_service.prepare(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="准备向量重建失败，请检查数据库") from exc
    background_tasks.add_task(rebuild_vectors_task)
    return {"message": f"向量重建任务已启动 (维度: {expected_dim})"}


@router.get("/rebuild/status", response_model=dict[str, Any])
async def get_rebuild_status():
    """Get rebuild task status.

    Returns:
        Rebuild status.
    """
    return rebuild_status


@router.delete("/clear", response_model=dict[str, str])
async def clear_vectors(
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Clear all vector data (admin only).

    Args:
        admin: Admin user.
        session: Database session.

    Returns:
        Clear result.
    """
    try:
        await session.execute(text("""
            UPDATE images SET embedding = NULL, updated_at = NOW()
        """))
        await session.commit()

        logger.info("向量数据已清空")
        return {"message": "向量数据已清空（设为 NULL）"}
    except Exception as e:
        logger.error(f"清空向量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def rebuild_vectors_task():
    """后台运行由 Service 管理的重建任务。"""
    await vector_rebuild_service.run()
