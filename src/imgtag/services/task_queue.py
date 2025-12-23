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


import uuid

@dataclass
class AnalysisTask:
    """分析任务"""
    image_id: int
    task_type: str = "analyze_image"  # analyze_image / rebuild_vector
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
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
    
    def get_batch_interval(self) -> float:
        """获取任务间隔时间（秒）"""
        return float(config_db.get("queue_batch_interval", "1") or "1")
    
    def add_tasks(self, image_ids: List[int], task_type: str = "analyze_image") -> int:
        """添加任务到队列
        
        Args:
            image_ids: 图片 ID 列表
            task_type: 任务类型，可选值：
                - analyze_image: 分析图片（视觉模型 + 向量）
                - rebuild_vector: 重建向量（仅向量）
        """
        with self._lock:
            added = 0
            for image_id in image_ids:
                # 检查是否已在队列中
                if any(t.image_id == image_id for t in self._queue):
                    continue
                if image_id in self._processing:
                    continue
                
                # 创建任务对象
                task = AnalysisTask(image_id=image_id, task_type=task_type)
                self._queue.append(task)
                
                # 持久化到数据库
                try:
                    db.create_task(
                        task_id=task.id,
                        task_type=task_type,
                        payload={"image_id": image_id}
                    )
                except Exception as e:
                    logger.error(f"创建任务记录失败: {str(e)}")
                    
                added += 1
            
            logger.info(f"添加了 {added} 个任务到队列 (类型: {task_type})")
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
                    {"image_id": t.image_id, "status": t.status.value, "task_id": t.id}
                    for t in pending[:20]
                ],
                "processing": [
                    {"image_id": t.image_id, "status": t.status.value, "started_at": t.started_at.isoformat() if t.started_at else None, "task_id": t.id}
                    for t in processing
                ],
                "recent_completed": [
                    {"image_id": t.image_id, "status": t.status.value, "error": t.error, "task_id": t.id}
                    for t in recent_completed[-10:]
                ],
                "batch_interval": self.get_batch_interval()
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
                
                # 更新数据库状态
                try:
                    db.update_task_status(task.id, "failed", error=str(e))
                except Exception as db_e:
                    logger.error(f"更新任务 {task.id} 状态失败: {str(db_e)}")
                
                with self._lock:
                    if task.image_id in self._processing:
                        del self._processing[task.image_id]
                    self._completed.append(task)
            
            # 任务完成后等待间隔
            interval = self.get_batch_interval()
            if interval > 0:
                await asyncio.sleep(interval)
        
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
            
            # 更新数据库状态
            try:
                # 在锁内或者锁外更新？最好快速释放锁。
                # 这里为了简单直接更新，注意不要阻塞太久。
                # 实际上 db 操作可能较慢，建议移出锁外。
                # 但移出锁外需要重构 _get_next_task 逻辑，这里先这样。
                # 另起一个线程/任务更新？
                pass 
            except Exception:
                pass
            
            return task
    
    async def _process_task(self, task: AnalysisTask, worker_id: int):
        """处理单个任务"""
        from imgtag.services import vision_service, embedding_service
        
        logger.info(f"Worker {worker_id} 处理图片 ID: {task.image_id}")
        
        # 更新处理中状态
        try:
            db.update_task_status(task.id, "processing")
        except Exception as e:
            logger.error(f"更新任务 {task.id} 状态失败: {str(e)}")
        
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
                
                # 更新图片
                db.update_image(
                    image_id=task.image_id,
                    embedding=embedding
                )
                
            else:
                # 获取文件扩展名
                import os
                file_ext = ""
                if image_url.startswith("/uploads/"):
                    file_ext = os.path.splitext(image_url)[1].lower().lstrip(".")
                else:
                    # 从 URL 尝试获取扩展名
                    url_path = image_url.split("?")[0]
                    file_ext = os.path.splitext(url_path)[1].lower().lstrip(".")
                
                # 检查是否在允许处理的文件类型中
                allowed_extensions = config_db.get("vision_allowed_extensions", "jpg,jpeg,png,webp,bmp")
                allowed_list = [ext.strip().lower() for ext in allowed_extensions.split(",")]
                convert_gif = config_db.get("vision_convert_gif", "true").lower() == "true"
                
                # GIF 特殊处理
                if file_ext == "gif":
                    if not convert_gif:
                        logger.info(f"图片 {task.image_id} 是 GIF 格式，跳过分析")
                        # 只生成空向量，不分析
                        embedding = await embedding_service.get_embedding("")
                        db.update_image(image_id=task.image_id, embedding=embedding)
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = datetime.now()
                        try:
                            db.update_task_status(task.id, "completed", result={"image_id": task.image_id, "skipped": True, "reason": "GIF not converted"})
                        except Exception as e:
                            logger.error(f"更新任务 {task.id} 状态失败: {str(e)}")
                        with self._lock:
                            if task.image_id in self._processing:
                                del self._processing[task.image_id]
                            self._completed.append(task)
                        return
                    # GIF 转换为 PNG 后处理，稍后在读取文件时处理
                    
                elif file_ext and file_ext not in allowed_list:
                    logger.info(f"图片 {task.image_id} 格式 {file_ext} 不在允许列表中，跳过分析")
                    # 生成空向量
                    embedding = await embedding_service.get_embedding("")
                    db.update_image(image_id=task.image_id, embedding=embedding)
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    try:
                        db.update_task_status(task.id, "completed", result={"image_id": task.image_id, "skipped": True, "reason": f"Extension {file_ext} not allowed"})
                    except Exception as e:
                        logger.error(f"更新任务 {task.id} 状态失败: {str(e)}")
                    with self._lock:
                        if task.image_id in self._processing:
                            del self._processing[task.image_id]
                        self._completed.append(task)
                    return
                
                # 分析图片
                if image_url.startswith("/uploads/"):
                    # 本地文件，需要读取文件内容
                    from imgtag.core.config import settings
                    
                    file_path = image.get("file_path") or os.path.join(
                        settings.UPLOAD_DIR, 
                        image_url.replace("/uploads/", "")
                    )
                    
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as f:
                            file_content = f.read()
                        
                        # GIF 转换为 PNG
                        if file_ext == "gif" and convert_gif:
                            try:
                                from PIL import Image
                                import io
                                img = Image.open(io.BytesIO(file_content))
                                # 取第一帧
                                if hasattr(img, 'n_frames') and img.n_frames > 1:
                                    img.seek(0)
                                # 转换为 RGB（去掉透明通道）
                                if img.mode in ('RGBA', 'LA', 'P'):
                                    img = img.convert('RGB')
                                # 保存为 PNG
                                output = io.BytesIO()
                                img.save(output, format='PNG')
                                file_content = output.getvalue()
                                mime_type = "image/png"
                                logger.info(f"图片 {task.image_id} GIF 已转换为 PNG")
                            except Exception as e:
                                logger.warning(f"GIF 转换失败: {str(e)}，使用原始格式")
                                from imgtag.services.upload_service import UploadService
                                mime_type = UploadService().get_mime_type(file_path)
                        else:
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
                    embedding=embedding,
                    tag_source="ai"
                )
            
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now()
            
            # 更新数据库状态
            try:
                db.update_task_status(
                    task.id, 
                    "completed", 
                    result={
                        "image_id": task.image_id,
                        "tags": analysis.tags if 'analysis' in locals() else image.get("tags"),
                        "description": analysis.description if 'analysis' in locals() else image.get("description")
                    }
                )
            except Exception as e:
                logger.error(f"更新任务 {task.id} 状态失败: {str(e)}")
            
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
            
            # 更新数据库状态
            try:
                db.update_task_status(task.id, "failed", error=str(e))
            except Exception as db_e:
                logger.error(f"更新任务 {task.id} 状态失败: {str(db_e)}")
            
            with self._lock:
                if task.image_id in self._processing:
                    del self._processing[task.image_id]
                self._completed.append(task)


# 全局实例
task_queue = TaskQueueService()
