#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
任务队列服务
管理图片分析的异步队列处理
"""

import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import threading

from imgtag.core.logging_config import get_logger
from imgtag.db import db, config_db

logger = get_logger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AnalysisTask:
    """分析任务"""
    image_id: int
    status: TaskStatus = TaskStatus.PENDING
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskQueueService:
    """任务队列服务"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TaskQueueService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        
        self._queue: List[AnalysisTask] = []
        self._processing: Dict[int, AnalysisTask] = {}
        self._completed: List[AnalysisTask] = []
        self._lock = threading.Lock()
        self._running = False
        self._workers: List[asyncio.Task] = []
        self._initialized = True
        
        logger.info("任务队列服务初始化完成")
    
    def get_max_workers(self) -> int:
        """获取最大并发数"""
        return config_db.get_int("queue_max_workers", 2)
    
    def add_tasks(self, image_ids: List[int]) -> int:
        """添加任务到队列"""
        with self._lock:
            added = 0
            for image_id in image_ids:
                # 检查是否已在队列中
                if any(t.image_id == image_id for t in self._queue):
                    continue
                if image_id in self._processing:
                    continue
                
                task = AnalysisTask(image_id=image_id)
                self._queue.append(task)
                added += 1
            
            logger.info(f"添加了 {added} 个任务到队列")
            return added
    
    def get_status(self) -> Dict[str, Any]:
        """获取队列状态"""
        with self._lock:
            pending = [t for t in self._queue]
            processing = list(self._processing.values())
            
            # 只保留最近 50 个完成的任务
            recent_completed = self._completed[-50:]
            
            return {
                "running": self._running,
                "max_workers": self.get_max_workers(),
                "pending_count": len(pending),
                "processing_count": len(processing),
                "completed_count": len(self._completed),
                "pending": [
                    {"image_id": t.image_id, "status": t.status.value}
                    for t in pending[:20]
                ],
                "processing": [
                    {"image_id": t.image_id, "status": t.status.value, "started_at": t.started_at.isoformat() if t.started_at else None}
                    for t in processing
                ],
                "recent_completed": [
                    {"image_id": t.image_id, "status": t.status.value, "error": t.error}
                    for t in recent_completed[-10:]
                ]
            }
    
    async def start_processing(self):
        """启动队列处理"""
        if self._running:
            logger.info("队列已在运行中")
            return
        
        self._running = True
        logger.info("启动队列处理")
        
        # 启动工作协程
        max_workers = self.get_max_workers()
        for i in range(max_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
    
    def stop_processing(self):
        """停止队列处理"""
        self._running = False
        logger.info("停止队列处理")
    
    def clear_queue(self):
        """清空待处理队列"""
        with self._lock:
            self._queue.clear()
            logger.info("队列已清空")
    
    def clear_completed(self):
        """清空已完成列表"""
        with self._lock:
            self._completed.clear()
            logger.info("已完成列表已清空")
    
    async def _worker(self, worker_id: int):
        """工作协程"""
        logger.info(f"Worker {worker_id} 启动")
        
        while self._running:
            task = self._get_next_task()
            
            if task is None:
                await asyncio.sleep(0.5)
                continue
            
            try:
                await self._process_task(task, worker_id)
            except Exception as e:
                logger.error(f"Worker {worker_id} 处理任务失败: {str(e)}")
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = datetime.now()
                
                with self._lock:
                    if task.image_id in self._processing:
                        del self._processing[task.image_id]
                    self._completed.append(task)
        
        logger.info(f"Worker {worker_id} 停止")
    
    def _get_next_task(self) -> Optional[AnalysisTask]:
        """获取下一个待处理任务"""
        with self._lock:
            if not self._queue:
                return None
            
            task = self._queue.pop(0)
            task.status = TaskStatus.PROCESSING
            task.started_at = datetime.now()
            self._processing[task.image_id] = task
            return task
    
    async def _process_task(self, task: AnalysisTask, worker_id: int):
        """处理单个任务"""
        from imgtag.services import vision_service, embedding_service
        
        logger.info(f"Worker {worker_id} 处理图片 ID: {task.image_id}")
        
        try:
            # 获取图片信息
            image = db.get_image(task.image_id)
            if not image:
                raise Exception(f"图片 {task.image_id} 不存在")
            
            image_url = image.get("image_url", "")
            
            # 如果已有描述和标签，直接生成向量
            if image.get("description") and image.get("tags"):
                logger.info(f"图片 {task.image_id} 已有标签，只生成向量")
                embedding = await embedding_service.get_embedding_combined(
                    image["description"],
                    image["tags"]
                )
            else:
                # 分析图片
                if image_url.startswith("/uploads/"):
                    # 本地文件，需要读取文件内容
                    from imgtag.core.config import settings
                    import os
                    
                    file_path = image.get("file_path") or os.path.join(
                        settings.UPLOAD_DIR, 
                        image_url.replace("/uploads/", "")
                    )
                    
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            file_content = f.read()
                        
                        from imgtag.services.upload_service import UploadService
                        mime_type = UploadService().get_mime_type(file_path)
                        analysis = await vision_service.analyze_image_base64(file_content, mime_type)
                    else:
                        raise Exception(f"文件不存在: {file_path}")
                else:
                    # 远程 URL
                    analysis = await vision_service.analyze_image_url(image_url)
                
                # 生成向量
                embedding = await embedding_service.get_embedding_combined(
                    analysis.description,
                    analysis.tags
                )
                
                # 更新数据库
                db.update_image(
                    image_id=task.image_id,
                    tags=analysis.tags,
                    description=analysis.description,
                    embedding=embedding
                )
            
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            
            with self._lock:
                if task.image_id in self._processing:
                    del self._processing[task.image_id]
                self._completed.append(task)
            
            logger.info(f"图片 {task.image_id} 处理完成")
            
        except Exception as e:
            logger.error(f"处理图片 {task.image_id} 失败: {str(e)}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = datetime.now()
            
            with self._lock:
                if task.image_id in self._processing:
                    del self._processing[task.image_id]
                self._completed.append(task)


# 全局实例
task_queue = TaskQueueService()
