#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
队列管理 API 端点
管理图片分析任务队列
"""

from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from imgtag.services.task_queue import task_queue
from imgtag.db import config_db
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


class AddTasksRequest(BaseModel):
    """添加任务请求"""
    image_ids: List[int]


class ConfigWorkerRequest(BaseModel):
    """配置工作线程数"""
    max_workers: int


@router.get("/status", response_model=Dict[str, Any])
async def get_queue_status():
    """获取队列状态"""
    return task_queue.get_status()


@router.post("/add", response_model=Dict[str, Any])
async def add_tasks(request: AddTasksRequest, background_tasks: BackgroundTasks):
    """添加任务到队列"""
    if not request.image_ids:
        raise HTTPException(status_code=400, detail="图片 ID 列表不能为空")
    
    added = task_queue.add_tasks(request.image_ids)
    
    # 自动启动队列处理
    if not task_queue._running:
        background_tasks.add_task(start_queue_async)
    
    return {
        "message": f"已添加 {added} 个任务到队列",
        "added": added,
        "total_pending": task_queue.get_status()["pending_count"]
    }


@router.post("/start", response_model=Dict[str, str])
async def start_queue(background_tasks: BackgroundTasks):
    """启动队列处理"""
    if task_queue._running:
        return {"message": "队列已在运行中"}
    
    background_tasks.add_task(start_queue_async)
    return {"message": "队列处理已启动"}


@router.post("/stop", response_model=Dict[str, str])
async def stop_queue():
    """停止队列处理"""
    task_queue.stop_processing()
    return {"message": "队列处理已停止"}


@router.delete("/clear", response_model=Dict[str, str])
async def clear_queue():
    """清空待处理队列"""
    task_queue.clear_queue()
    return {"message": "队列已清空"}


@router.delete("/clear-completed", response_model=Dict[str, str])
async def clear_completed():
    """清空已完成列表"""
    task_queue.clear_completed()
    return {"message": "已完成列表已清空"}


@router.put("/config", response_model=Dict[str, Any])
async def config_workers(request: ConfigWorkerRequest):
    """配置最大工作线程数"""
    if request.max_workers < 1:
        raise HTTPException(status_code=400, detail="最大线程数必须大于 0")
    if request.max_workers > 10:
        raise HTTPException(status_code=400, detail="最大线程数不能超过 10")
    
    config_db.set("queue_max_workers", str(request.max_workers))
    
    return {
        "message": f"最大工作线程数已设置为 {request.max_workers}",
        "max_workers": request.max_workers
    }


@router.post("/add-untagged", response_model=Dict[str, Any])
async def add_untagged_images(background_tasks: BackgroundTasks):
    """添加所有未打标签的图片到队列"""
    from imgtag.db import db
    
    try:
        # 查找没有描述或标签的图片
        with db._get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                SELECT id FROM images 
                WHERE description IS NULL OR description = '' 
                   OR tags IS NULL OR array_length(tags, 1) IS NULL
                ORDER BY id;
                """)
                results = cursor.fetchall()
        
        image_ids = [row[0] for row in results]
        
        if not image_ids:
            return {"message": "没有未打标签的图片", "added": 0}
        
        added = task_queue.add_tasks(image_ids)
        
        # 自动启动队列
        if not task_queue._running:
            background_tasks.add_task(start_queue_async)
        
        return {
            "message": f"已添加 {added} 个未打标签的图片到队列",
            "added": added,
            "total_pending": task_queue.get_status()["pending_count"]
        }
    except Exception as e:
        logger.error(f"添加未打标签图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def start_queue_async():
    """异步启动队列"""
    await task_queue.start_processing()
