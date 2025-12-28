#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""System API endpoints.

System status, health checks, and maintenance operations.
"""

import asyncio
import hashlib
import json
import os
from datetime import date, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.config import settings
from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository
from imgtag.services.embedding_service import embedding_service
from imgtag.services.task_queue import task_queue

logger = get_logger(__name__)

router = APIRouter()


@router.get("/status", response_model=dict[str, Any])
async def get_system_status(
    session: AsyncSession = Depends(get_async_session),
):
    """Get system status.

    Args:
        session: Database session.

    Returns:
        System status.
    """
    logger.info("获取系统状态")

    try:
        image_count = await image_repository.count_images(session)

        vision_model = await config_cache.get("vision_model", settings.VISION_MODEL)
        embedding_mode = await config_cache.get("embedding_mode", "local")

        if embedding_mode == "local":
            embedding_model = await config_cache.get(
                "embedding_local_model", "BAAI/bge-small-zh-v1.5"
            )
        else:
            embedding_model = await config_cache.get("embedding_model", settings.EMBEDDING_MODEL)

        return {
            "status": "running",
            "version": settings.PROJECT_VERSION,
            "image_count": image_count,
            "vision_model": vision_model,
            "embedding_model": embedding_model,
            "embedding_dimensions": await embedding_service.get_dimensions(),
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        Health status.
    """
    return {"status": "healthy"}


@router.get("/dashboard", response_model=dict[str, Any])
async def get_dashboard_stats(
    session: AsyncSession = Depends(get_async_session),
):
    """Get dashboard statistics.

    Uses Repository methods with efficient single queries.

    Args:
        session: Database session.

    Returns:
        Dashboard stats.
    """
    logger.info("获取仪表盘统计数据")

    try:
        # Image stats - 3 queries
        total_images = await image_repository.count_images(session)
        pending_images = await image_repository.count_pending_images(session)
        analyzed_images = total_images - pending_images

        # Today stats - pass date object directly
        today = date.today()
        today_uploaded = await image_repository.count_by_date(
            session, today, "uploaded"
        )
        today_analyzed = await image_repository.count_by_date(
            session, today, "analyzed"
        )

        # Queue stats
        queue_status = await task_queue.get_status()
        total_tasks = (
            queue_status.get("pending_count", 0)
            + queue_status.get("processing_count", 0)
            + queue_status.get("completed_count", 0)
        )

        # System config
        vision_model = await config_cache.get("vision_model", settings.VISION_MODEL)
        embedding_mode = await config_cache.get("embedding_mode", "local")

        if embedding_mode == "local":
            embedding_model = await config_cache.get(
                "embedding_local_model", "BAAI/bge-small-zh-v1.5"
            )
        else:
            embedding_model = await config_cache.get("embedding_model", settings.EMBEDDING_MODEL)

        return {
            "images": {
                "total": total_images,
                "pending": pending_images,
                "analyzed": analyzed_images,
            },
            "today": {
                "uploaded": today_uploaded,
                "analyzed": today_analyzed,
            },
            "queue": {
                "total": total_tasks,
                "processing": queue_status.get("processing_count", 0),
                "pending": queue_status.get("pending_count", 0),
                "running": queue_status.get("running", False),
            },
            "system": {
                "vision_model": vision_model,
                "embedding_model": embedding_model,
                "embedding_dimensions": await embedding_service.get_dimensions(),
                "version": settings.PROJECT_VERSION,
            },
        }
    except Exception as e:
        logger.error(f"获取仪表盘统计失败: {e}")
        return {
            "error": str(e),
            "images": {"total": 0, "pending": 0, "analyzed": 0},
            "today": {"uploaded": 0, "analyzed": 0},
            "queue": {"total": 0, "processing": 0, "pending": 0, "running": False},
            "system": {
                "vision_model": "-",
                "embedding_model": "-",
                "embedding_dimensions": 0,
                "version": "-",
            },
        }


@router.get("/config", response_model=dict[str, Any])
async def get_config():
    """Get current config (non-sensitive).

    Returns:
        Public config values.
    """
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


@router.get("/models")
async def get_available_models():
    """Get available model list.

    Returns:
        Available models from API.
    """
    logger.info("获取可用模型列表")

    try:
        api_base_url = await config_cache.get("vision_api_base_url", settings.VISION_API_BASE_URL)
        api_key = await config_cache.get("vision_api_key", "")

        if not api_base_url or not api_key:
            return {"models": [], "error": "未配置 API 地址或密钥"}

        models_url = f"{api_base_url.rstrip('/')}/models"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                models_url, headers={"Authorization": f"Bearer {api_key}"}
            )

            if response.status_code == 200:
                data = response.json()
                models = []
                if "data" in data:
                    models = [m.get("id") for m in data["data"] if m.get("id")]
                elif isinstance(data, list):
                    models = [m.get("id") for m in data if m.get("id")]
                return {"models": sorted(models)}
            else:
                return {"models": [], "error": f"API 返回 {response.status_code}"}

    except httpx.TimeoutException:
        return {"models": [], "error": "请求超时"}
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}")
        return {"models": [], "error": str(e)}


# ========== Export/Import (keep legacy db calls for now) ==========


@router.get("/export")
async def export_database(admin: dict = Depends(require_admin)):
    """Export database records (admin).

    Note: This feature is temporarily disabled during async refactoring.

    Args:
        admin: Admin user.

    Returns:
        Error message.
    """
    logger.warning("导出功能暂时不可用（异步重构中）")
    return {
        "error": "导出功能暂时不可用，请使用数据库备份工具",
        "message": "此功能正在重构中，请使用 pg_dump 进行备份"
    }


@router.post("/import")
async def import_database(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin),
):
    """Import database records (admin).

    Note: This feature is temporarily disabled during async refactoring.

    Args:
        file: Upload file.
        admin: Admin user.

    Returns:
        Error message.
    """
    logger.warning("导入功能暂时不可用（异步重构中）")
    return {
        "error": "导入功能暂时不可用，请使用数据库恢复工具",
        "message": "此功能正在重构中，请使用 pg_restore 进行恢复"
    }


# ========== Duplicate Detection ==========


@router.get("/duplicates")
async def get_duplicate_images(
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get duplicate images with full details (admin).

    Args:
        admin: Admin user.
        session: Database session.

    Returns:
        Duplicate groups with image details.
    """
    logger.info("扫描重复图片")

    try:
        duplicates = await image_repository.find_duplicates(session)
        no_hash_count = await image_repository.count_without_hash(session)

        return {
            "duplicate_groups": duplicates,
            "total_groups": len(duplicates),
            "total_duplicates": sum(g["count"] - 1 for g in duplicates),
            "images_without_hash": no_hash_count,
        }
    except Exception as e:
        logger.error(f"扫描重复图片失败: {e}")
        return {"error": str(e)}


@router.post("/duplicates/calculate-hashes")
async def calculate_missing_hashes(
    limit: int = 100,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Calculate missing file hashes (admin).

    Batch processes images without hash.

    Args:
        limit: Max images to process.
        admin: Admin user.
        session: Database session.

    Returns:
        Processing result.
    """
    logger.info(f"开始计算文件哈希，限制 {limit} 张")

    try:
        images = await image_repository.get_without_hash(session, limit)

        # Batch collect updates
        hash_updates = []
        errors = []

        for img in images:
            try:
                file_hash = None

                # Local file
                file_path = img.get("file_path")
                if file_path and os.path.exists(file_path):
                    def _calc_hash(path):
                        with open(path, "rb") as f:
                            return hashlib.md5(f.read()).hexdigest()
                    file_hash = await asyncio.to_thread(_calc_hash, file_path)

                # URL image - download and hash
                elif img.get("image_url"):
                    url = img["image_url"]
                    if url.startswith("/"):
                        base_url = await config_cache.get("base_url", "http://localhost:8000")
                        url = base_url.rstrip("/") + url

                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(url)
                        if response.status_code == 200:
                            file_hash = hashlib.md5(response.content).hexdigest()

                if file_hash:
                    hash_updates.append({"id": img["id"], "hash": file_hash})

            except Exception as e:
                errors.append(f"图片 {img['id']}: {e}")

        # Batch update
        if hash_updates:
            await image_repository.batch_update_hashes(session, hash_updates)

        remaining = await image_repository.count_without_hash(session)

        return {
            "message": f"已处理 {len(hash_updates)} 张图片",
            "processed": len(hash_updates),
            "remaining": remaining,
            "errors": errors[:10],
        }
    except Exception as e:
        logger.error(f"计算哈希失败: {e}")
        return {"error": str(e)}


# ========== Resolution Backfill ==========


@router.get("/resolution/status")
async def get_resolution_status(
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Get resolution backfill status (admin).

    Args:
        admin: Admin user.
        session: Database session.

    Returns:
        Resolution status.
    """
    logger.info("获取分辨率补全状态")

    try:
        total = await image_repository.count_images(session)
        missing = await image_repository.count_without_resolution(session)
        completed = total - missing

        return {
            "total": total,
            "completed": completed,
            "missing": missing,
            "percentage": round((completed / total * 100) if total > 0 else 0, 1),
        }
    except Exception as e:
        logger.error(f"获取分辨率状态失败: {e}")
        return {"error": str(e)}


@router.post("/resolution/backfill")
async def backfill_resolution(
    limit: int = 100,
    admin: dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """Backfill missing image resolutions (admin).

    Batch processes images without width/height.

    Args:
        limit: Max images to process.
        admin: Admin user.
        session: Database session.

    Returns:
        Processing result.
    """
    logger.info(f"开始补全分辨率，限制 {limit} 张")

    try:
        images = await image_repository.get_without_resolution(session, limit)

        # Batch collect updates
        resolution_updates = []
        skipped = 0
        errors = []

        for img in images:
            try:
                file_path = img.get("file_path")

                if not file_path or not os.path.exists(file_path):
                    skipped += 1
                    continue

                # PIL 操作移至线程池，避免阻塞
                def _get_dimensions(path):
                    from PIL import Image as PILImage
                    with PILImage.open(path) as pil_img:
                        return pil_img.size
                
                width, height = await asyncio.to_thread(_get_dimensions, file_path)

                resolution_updates.append({
                    "id": img["id"],
                    "width": width,
                    "height": height,
                })

            except Exception as e:
                errors.append(f"图片 {img['id']}: {e}")

        # Batch update
        if resolution_updates:
            await image_repository.batch_update_resolutions(session, resolution_updates)

        remaining = await image_repository.count_without_resolution(session)

        return {
            "message": f"已处理 {len(resolution_updates)} 张图片，跳过 {skipped} 张",
            "processed": len(resolution_updates),
            "skipped": skipped,
            "remaining": remaining,
            "errors": errors[:10],
        }
    except Exception as e:
        logger.error(f"补全分辨率失败: {e}")
        return {"error": str(e)}


