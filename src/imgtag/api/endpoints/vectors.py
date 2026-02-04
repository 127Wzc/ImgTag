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
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.db import get_async_session
from imgtag.db.database import async_session_maker, engine
from imgtag.db.repositories import image_repository, config_repository
from imgtag.services import embedding_service

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()

# Rebuild status (module-level state)
rebuild_status = {
    "is_running": False,
    "total": 0,
    "processed": 0,
    "failed": 0,
    "message": "",
}

# Install status
install_status = {
    "is_running": False,
    "success": None,
    "message": "",
    "output": "",
}


async def get_db_vector_dimensions(session: AsyncSession) -> int:
    """Get vector column dimensions from database.

    Args:
        session: Database session.

    Returns:
        Vector dimensions (default 1536).
    """
    try:
        result = await session.execute(text("""
            SELECT atttypmod FROM pg_attribute 
            WHERE attrelid = 'images'::regclass 
            AND attname = 'embedding'
        """))
        row = result.fetchone()
        if row and row[0]:
            return row[0]
        return 1536
    except Exception:
        return 1536


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
    """Start vector rebuild task (admin only).

    Args:
        background_tasks: FastAPI background tasks.
        admin: Admin user.
        session: Database session.

    Returns:
        Rebuild start message.
    """
    global rebuild_status

    if rebuild_status["is_running"]:
        raise HTTPException(status_code=400, detail="重建任务正在进行中")

    # Get expected dimensions
    mode = await config_cache.get("embedding_mode", "local") or "local"
    if mode == "local":
        model_name = await config_cache.get("embedding_local_model", "BAAI/bge-small-zh-v1.5") or "BAAI/bge-small-zh-v1.5"
        if "small" in model_name:
            expected_dim = 512
        elif "base" in model_name:
            expected_dim = 768
        else:
            expected_dim = 512
    else:
        dim_str = await config_cache.get("embedding_dimensions", "1536")
        expected_dim = int(dim_str) if dim_str else 1536

    db_dim = await get_db_vector_dimensions(session)

    # Auto-adjust dimensions if needed
    if expected_dim != db_dim:
        logger.info(f"自动调整向量维度: {db_dim} -> {expected_dim}")
        try:
            conn = await session.connection()
            await conn.execute(text("DROP INDEX IF EXISTS idx_images_embedding"))
            await conn.execute(text(f"""
                ALTER TABLE images 
                ALTER COLUMN embedding TYPE vector({expected_dim})
                USING (ARRAY_FILL(0::float, ARRAY[{expected_dim}])::vector({expected_dim}))
            """))
            await conn.execute(text(f"""
                CREATE INDEX idx_images_embedding ON public.images 
                USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
            """))
            await config_repository.set_value(session, "embedding_dimensions", str(expected_dim))
            await session.commit()
            await config_cache.refresh()
            logger.info(f"向量维度调整完成: {expected_dim}")
        except Exception as e:
            await session.rollback()
            logger.error(f"调整维度失败: {e}")
            raise HTTPException(status_code=500, detail=f"调整维度失败: {e}")

    # Force reload model to ensure we use the correct one matches config
    embedding_service.reload_model()

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
    """Background task: rebuild all image vectors."""
    global rebuild_status

    rebuild_status = {
        "is_running": True,
        "total": 0,
        "processed": 0,
        "failed": 0,
        "message": "正在获取图片列表...",
    }

    try:
        async with async_session_maker() as session:
            # Get all images with tags
            result = await session.execute(text("""
                SELECT i.id, i.description,
                       ARRAY(
                           SELECT t.name FROM tags t
                           JOIN image_tags it ON t.id = it.tag_id
                           WHERE it.image_id = i.id AND t.level = 2
                       ) as tags
                FROM images i ORDER BY i.id
            """))
            images = result.fetchall()

        rebuild_status["total"] = len(images)
        rebuild_status["message"] = f"开始重建 {len(images)} 张图片的向量..."

        logger.info(f"开始重建向量: 共 {len(images)} 张图片")

        for image_id, description, tags in images:
            try:
                # Skip if no description and no tags
                if not description and not tags:
                    logger.info(f"跳过图片 {image_id}: 无描述和标签")
                    rebuild_status["processed"] += 1
                    rebuild_status["message"] = (
                        f"已处理 {rebuild_status['processed']}/{rebuild_status['total']}"
                    )
                    continue

                # Generate embedding
                embedding = await embedding_service.get_embedding_combined(
                    description or "",
                    tags or [],
                )

                # Update database
                # Update database
                async with async_session_maker() as session:
                    image_model = await image_repository.get_by_id(session, image_id)
                    if image_model:
                        await image_repository.update_image(
                            session, image_model, embedding=embedding
                        )
                    await session.commit()

                rebuild_status["processed"] += 1
                rebuild_status["message"] = (
                    f"已处理 {rebuild_status['processed']}/{rebuild_status['total']}"
                )

            except Exception as e:
                logger.error(f"重建图片 {image_id} 向量失败: {e}")
                rebuild_status["failed"] += 1

        rebuild_status["is_running"] = False
        rebuild_status["message"] = (
            f"重建完成: 成功 {rebuild_status['processed']}, "
            f"失败 {rebuild_status['failed']}"
        )

        logger.info(
            f"向量重建完成: 成功 {rebuild_status['processed']}, "
            f"失败 {rebuild_status['failed']}"
        )

    except Exception as e:
        logger.error(f"重建向量任务失败: {e}")
        rebuild_status["is_running"] = False
        rebuild_status["message"] = f"重建失败: {e}"
