#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Queue management API endpoints.

Manages image analysis task queue.
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import get_current_user
from imgtag.core.logging_config import get_logger
from imgtag.db import config_db, get_async_session
from imgtag.db.repositories import image_repository
from imgtag.services.task_queue import task_queue

logger = get_logger(__name__)

router = APIRouter()


class AddTasksRequest(BaseModel):
    """Add tasks request."""

    image_ids: list[int]


class ConfigWorkerRequest(BaseModel):
    """Configure worker count request."""

    max_workers: int


@router.get("/status", response_model=dict[str, Any])
async def get_queue_status():
    """Get queue status.

    Returns:
        Queue status dict.
    """
    return task_queue.get_status()


@router.post("/add", response_model=dict[str, Any])
async def add_tasks(
    request: AddTasksRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Add tasks to queue (requires login).

    Args:
        request: Image IDs to add.
        background_tasks: FastAPI background tasks.
        user: Current user.

    Returns:
        Add result.
    """
    if not request.image_ids:
        raise HTTPException(status_code=400, detail="图片 ID 列表不能为空")

    added = task_queue.add_tasks(request.image_ids)

    # Auto-start queue
    if not task_queue._running:
        background_tasks.add_task(start_queue_async)

    return {
        "message": f"已添加 {added} 个任务到队列",
        "added": added,
        "total_pending": task_queue.get_status()["pending_count"],
    }


@router.post("/start", response_model=dict[str, str])
async def start_queue(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Start queue processing (requires login).

    Args:
        background_tasks: FastAPI background tasks.
        user: Current user.

    Returns:
        Start message.
    """
    if task_queue._running:
        return {"message": "队列已在运行中"}

    background_tasks.add_task(start_queue_async)
    return {"message": "队列处理已启动"}


@router.post("/stop", response_model=dict[str, str])
async def stop_queue(user: dict = Depends(get_current_user)):
    """Stop queue processing (requires login).

    Args:
        user: Current user.

    Returns:
        Stop message.
    """
    task_queue.stop_processing()
    return {"message": "队列处理已停止"}


@router.delete("/clear", response_model=dict[str, str])
async def clear_queue(user: dict = Depends(get_current_user)):
    """Clear pending queue (requires login).

    Args:
        user: Current user.

    Returns:
        Clear message.
    """
    task_queue.clear_queue()
    return {"message": "队列已清空"}


@router.delete("/clear-completed", response_model=dict[str, str])
async def clear_completed(user: dict = Depends(get_current_user)):
    """Clear completed list (requires login).

    Args:
        user: Current user.

    Returns:
        Clear message.
    """
    task_queue.clear_completed()
    return {"message": "已完成列表已清空"}


@router.put("/config", response_model=dict[str, Any])
async def config_workers(
    request: ConfigWorkerRequest,
    user: dict = Depends(get_current_user),
):
    """Configure max workers (requires login).

    Args:
        request: Worker config.
        user: Current user.

    Returns:
        Config result.
    """
    if request.max_workers < 1:
        raise HTTPException(status_code=400, detail="最大线程数必须大于 0")
    if request.max_workers > 10:
        raise HTTPException(status_code=400, detail="最大线程数不能超过 10")

    config_db.set("queue_max_workers", str(request.max_workers))

    return {
        "message": f"最大工作线程数已设置为 {request.max_workers}",
        "max_workers": request.max_workers,
    }


@router.post("/add-untagged", response_model=dict[str, Any])
async def add_untagged_images(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Add all untagged images to queue (requires login).

    Uses single query to find images without embedding.

    Args:
        background_tasks: FastAPI background tasks.
        user: Current user.
        session: Database session.

    Returns:
        Add result.
    """
    try:
        # Single query to get pending image IDs
        image_ids = await image_repository.get_pending_analysis_ids(session)

        if not image_ids:
            return {"message": "没有待分析的图片", "added": 0}

        added = task_queue.add_tasks(image_ids)

        # Auto-start queue
        if not task_queue._running:
            background_tasks.add_task(start_queue_async)

        return {
            "message": f"已添加 {added} 个待分析图片到队列",
            "added": added,
            "total_pending": task_queue.get_status()["pending_count"],
        }
    except Exception as e:
        logger.error(f"添加待分析图片失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def start_queue_async():
    """Start queue processing async."""
    await task_queue.start_processing()
