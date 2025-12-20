#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
任务 API 端点
处理异步任务的查询和管理
"""

from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Query

from imgtag.services.task_service import task_service
from imgtag.schemas import Task, TaskResponse
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=Dict[str, Any])
async def get_tasks(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str = Query(None, description="任务状态筛选")
):
    """获取任务列表"""
    return task_service.get_tasks(limit, offset, status)


@router.get("/{task_id}", response_model=Task)
async def get_task(task_id: str):
    """获取任务详情"""
    task = task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/cleanup", response_model=Dict[str, Any])
async def cleanup_tasks(days: int = Query(7, ge=1, description="保留天数")):
    """清理旧任务"""
    count = task_service.cleanup_old_tasks(days)
    return {"message": f"已清理 {count} 个旧任务"}


@router.post("/vectorize", response_model=TaskResponse)
async def create_vectorize_task(
    image_ids: List[int],
    force: bool = Query(False, description="是否强制重新生成")
):
    """创建批量向量化任务"""
    task_id = task_service.create_task(
        "vectorize_batch",
        {"image_ids": image_ids, "force": force}
    )
    return {"task_id": task_id, "message": "批量向量化任务已提交"}
