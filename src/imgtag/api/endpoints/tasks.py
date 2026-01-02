#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
任务 API 端点
处理异步任务的查询和管理
"""

from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from imgtag.api.endpoints.auth import get_current_user
from imgtag.core.logging_config import get_logger
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import task_repository
from imgtag.schemas import Task, TaskResponse
from imgtag.services.task_queue import task_queue
from imgtag.services.task_service import task_service

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=Dict[str, Any])
async def get_tasks(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str = Query(None, description="任务状态筛选")
):
    """获取任务列表"""
    return await task_service.get_tasks(limit, offset, status)


@router.get("/{task_id}", response_model=Task)
async def get_task(task_id: str):
    """获取任务详情"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/cleanup", response_model=Dict[str, Any])
async def cleanup_tasks(days: int = Query(7, ge=1, description="保留天数"), user: Dict = Depends(get_current_user)):
    """清理旧任务（需登录）"""
    count = await task_service.cleanup_old_tasks(days)
    return {"message": f"已清理 {count} 个旧任务"}


@router.post("/vectorize", response_model=TaskResponse)
async def create_vectorize_task(
    image_ids: List[int],
    force: bool = Query(False, description="是否强制重新生成"),
    user: Dict = Depends(get_current_user)
):
    """创建批量向量化任务（需登录）"""
    task_id = await task_service.create_task(
        "vectorize_batch",
        {"image_ids": image_ids, "force": force}
    )
    return {"task_id": task_id, "message": "批量向量化任务已提交"}


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    task_ids: List[str]


@router.delete("/batch", response_model=Dict[str, Any])
async def batch_delete_tasks(
    request: BatchDeleteRequest,
    user: Dict = Depends(get_current_user)
):
    """批量删除任务（需登录）"""
    count = await task_service.batch_delete(request.task_ids)
    return {"message": f"已删除 {count} 个任务", "deleted_count": count}


# 支持重试的任务类型
RETRYABLE_TASK_TYPES = ["analyze_image", "rebuild_vector", "storage_sync"]


@router.post("/{task_id}/retry", response_model=Dict[str, Any])
async def retry_task(
    task_id: str,
    user: Dict = Depends(get_current_user)
):
    """重试失败的任务（需登录）
    
    仅支持以下任务类型的重试：
    - analyze_image: 图片分析
    - rebuild_vector: 向量重建
    - storage_sync: 存储同步
    """
    # 获取任务信息
    async with async_session_maker() as session:
        task = await task_repository.get_by_id(session, task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 检查任务类型是否支持重试
    if task.type not in RETRYABLE_TASK_TYPES:
        raise HTTPException(
            status_code=400, 
            detail=f"任务类型 {task.type} 不支持重试"
        )
    
    # 尝试重试
    success = await task_queue.retry_task(task_id)
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="任务状态不允许重试（仅支持重试失败的任务）"
        )
    
    return {"message": "任务已加入重试队列", "task_id": task_id}

