#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""任务队列服务 - PostgreSQL 队列实现

基于 PostgreSQL 的任务队列，使用 FOR UPDATE SKIP LOCKED 实现原子抢占。
支持持久化、服务重启恢复、多实例部署。
"""

import asyncio
import io
import uuid
from typing import Any

import httpx
from sqlalchemy import select

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import StorageTaskStatus, get_mime_type
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    config_repository,
    image_repository,
    image_tag_repository,
    task_repository,
)
from imgtag.models.task import Task

logger = get_logger(__name__)

# 队列处理的任务类型
QUEUE_TASK_TYPES = ["analyze_image", "rebuild_vector"]


class TaskQueueService:
    """基于 PostgreSQL 的任务队列服务
    
    特点：
    - 无内存状态，所有状态存储在数据库
    - 使用 FOR UPDATE SKIP LOCKED 实现原子抢占
    - 服务重启后自动恢复 stuck 任务
    - 支持多实例部署（共享同一数据库）
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        
        self._running = False
        self._workers: list[asyncio.Task] = []
        self._initialized = True
        
        logger.info("任务队列服务初始化完成 (PostgreSQL 模式)")
    
    # ==================== 配置管理 ====================
    
    async def _get_max_workers(self) -> int:
        """获取最大并发 Worker 数"""
        async with async_session_maker() as session:
            value = await config_repository.get_value(session, "queue_max_workers", "2")
            try:
                return max(1, min(10, int(value or 2)))
            except (ValueError, TypeError):
                return 2
    
    async def _get_batch_interval(self) -> float:
        """获取任务间隔时间（秒）"""
        async with async_session_maker() as session:
            value = await config_repository.get_value(session, "queue_batch_interval", "1")
            try:
                return max(0, float(value or 1.0))
            except (ValueError, TypeError):
                return 1.0
    
    async def _get_pending_image_ids(
        self, 
        session, 
        image_ids: list[int],
    ) -> set[int]:
        """批量获取已有 pending/processing 任务的 image_ids
        
        Args:
            session: 数据库 session
            image_ids: 待检查的图片 ID 列表
            
        Returns:
            已有任务的 image_id 集合
        """
        
        if not image_ids:
            return set()
        
        stmt = (
            select(Task.payload["image_id"].as_integer())
            .where(Task.status.in_(["pending", "processing"]))
            .where(Task.type.in_(QUEUE_TASK_TYPES))
            .where(Task.payload["image_id"].as_integer().in_(image_ids))
        )
        result = await session.execute(stmt)
        return set(row[0] for row in result.fetchall())
    
    # ==================== 任务添加 ====================
    
    async def add_tasks(
        self, 
        image_ids: list[int], 
        task_type: str = "analyze_image",
        callback_url: str | None = None,
    ) -> int:
        """添加任务到队列
        
        Args:
            image_ids: 图片 ID 列表
            task_type: 任务类型 (analyze_image / rebuild_vector)
            callback_url: 分析完成后的回调 URL
            
        Returns:
            实际添加的任务数量
        """
        if not image_ids:
            return 0
        
        added = 0
        async with async_session_maker() as session:
            # 批量获取已有 pending/processing 任务的 image_ids
            existing_ids = await self._get_pending_image_ids(session, image_ids)
            
            for image_id in image_ids:
                if image_id in existing_ids:
                    continue
                
                # 创建任务
                task_id = str(uuid.uuid4())
                await task_repository.create_task(
                    session,
                    task_id=task_id,
                    task_type=task_type,
                    payload={
                        "image_id": image_id,
                        "callback_url": callback_url,
                    },
                )
                added += 1
            
            await session.commit()
        
        if added > 0:
            logger.info(f"添加了 {added} 个任务到队列 (类型: {task_type})")
            # 确保处理正在运行
            if not self._running:
                asyncio.create_task(self.start_processing())
        
        return added
    
    # ==================== 状态查询 ====================
    
    async def get_status(self) -> dict[str, Any]:
        """获取队列状态"""
        max_workers = await self._get_max_workers()
        batch_interval = await self._get_batch_interval()
        
        async with async_session_maker() as session:
            # 获取统计
            stats = await task_repository.get_stats_by_type(session, QUEUE_TASK_TYPES)
            
            # 获取最近完成的任务
            recent = await task_repository.get_recent_completed(
                session, QUEUE_TASK_TYPES, limit=10
            )
            recent_list = [
                {
                    "task_id": t.id,
                    "image_id": t.payload.get("image_id") if t.payload else None,
                    "status": t.status,
                    "error": t.error,
                }
                for t in recent
            ]
        
        return {
            "running": self._running,
            "max_workers": max_workers,
            "batch_interval": batch_interval,
            "pending_count": stats["pending"],
            "processing_count": stats["processing"],
            "completed_count": stats["completed"],
            "failed_count": stats["failed"],
            "recent_completed": recent_list,
        }
    
    # ==================== 队列控制 ====================
    
    async def start_processing(self):
        """启动队列处理"""
        if self._running:
            logger.info("队列已在运行中")
            return
        
        self._running = True
        max_workers = await self._get_max_workers()
        
        logger.info(f"启动队列处理 (workers={max_workers})")
        
        # 恢复 stuck 任务
        await self._recover_stuck_tasks()
        
        # 启动 Worker
        for i in range(max_workers):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)
    
    def stop_processing(self):
        """停止队列处理"""
        self._running = False
        logger.info("停止队列处理")
    
    async def clear_queue(self):
        """清空待处理队列"""
        async with async_session_maker() as session:
            count = await task_repository.delete_by_status(
                session, StorageTaskStatus.PENDING.value, QUEUE_TASK_TYPES
            )
            await session.commit()
        logger.info(f"清空了 {count} 个待处理任务")
    
    async def clear_completed(self):
        """清空已完成/失败任务"""
        async with async_session_maker() as session:
            c1 = await task_repository.delete_by_status(
                session, StorageTaskStatus.COMPLETED.value, QUEUE_TASK_TYPES
            )
            c2 = await task_repository.delete_by_status(
                session, StorageTaskStatus.FAILED.value, QUEUE_TASK_TYPES
            )
            await session.commit()
        logger.info(f"清空了 {c1 + c2} 个已完成/失败任务")
    
    async def retry_task(self, task_id: str) -> bool:
        """重试失败的任务
        
        将失败的任务状态重置为 pending，让 Worker 重新处理。
        
        Args:
            task_id: 任务 ID
            
        Returns:
            True 如果重试成功，False 如果任务不存在或不是失败状态
        """
        async with async_session_maker() as session:
            task = await task_repository.get_by_id(session, task_id)
            if not task:
                logger.warning(f"任务 {task_id} 不存在")
                return False
            
            if task.status != StorageTaskStatus.FAILED.value:
                logger.warning(f"任务 {task_id} 状态为 {task.status}，无法重试")
                return False
            
            # 重置为 pending 状态
            await task_repository.update_status(
                session, task_id, StorageTaskStatus.PENDING.value, error=None
            )
            await session.commit()
        
        logger.info(f"任务 {task_id} 已重置为待处理状态")
        
        # 确保处理正在运行
        if not self._running:
            asyncio.create_task(self.start_processing())
        
        return True
    
    async def _recover_stuck_tasks(self):
        """恢复 stuck 的 processing 任务"""
        async with async_session_maker() as session:
            count = await task_repository.reset_stuck_tasks(
                session, QUEUE_TASK_TYPES, stuck_minutes=10
            )
            await session.commit()
        if count > 0:
            logger.info(f"恢复了 {count} 个 stuck 任务")
    
    # ==================== Worker 实现 ====================
    
    async def _worker(self, worker_id: int):
        """Worker 协程"""
        logger.info(f"Worker {worker_id} 启动")
        
        while self._running:
            # 尝试抢占任务
            task = await self._claim_next_task()
            
            if task is None:
                await asyncio.sleep(0.5)
                continue
            
            try:
                await self._process_task(task, worker_id)
            except Exception as e:
                # _process_task 内部已处理异常并标记失败，此处仅记录日志
                logger.error(f"Worker {worker_id} 处理任务失败: {e}")
            
            # 任务间隔
            interval = await self._get_batch_interval()
            if interval > 0:
                await asyncio.sleep(interval)
        
        logger.info(f"Worker {worker_id} 停止")
    
    async def _claim_next_task(self) -> Task | None:
        """原子抢占下一个任务"""
        async with async_session_maker() as session:
            task = await task_repository.claim_next_task(session, QUEUE_TASK_TYPES)
            await session.commit()
            return task
    
    async def _mark_task_failed(self, task_id: str, error: str):
        """标记任务失败"""
        async with async_session_maker() as session:
            await task_repository.update_status(
                session, task_id, StorageTaskStatus.FAILED.value, error=error
            )
            await session.commit()
    
    async def _mark_task_completed(self, task_id: str, result: dict):
        """标记任务完成"""
        async with async_session_maker() as session:
            await task_repository.update_status(
                session, task_id, StorageTaskStatus.COMPLETED.value, result=result
            )
            await session.commit()
    
    # ==================== 任务处理 ====================
    
    async def _process_task(self, task: Task, worker_id: int):
        """处理单个任务"""
        from imgtag.services import vision_service, embedding_service
        from imgtag.services.storage_service import storage_service
        
        payload = task.payload or {}
        image_id = payload.get("image_id")
        callback_url = payload.get("callback_url")
        
        logger.info(f"Worker {worker_id} 处理图片 ID: {image_id}")
        
        try:
            async with async_session_maker() as session:
                # 获取图片信息
                image_model = await image_repository.get_with_tags(session, image_id)
                if not image_model:
                    raise ValueError(f"图片 {image_id} 不存在")
                
                # 获取分类 ID（level=0 的 Tag）用于分类专用提示词
                category_id = None
                if image_model.tags:
                    for tag in image_model.tags:
                        if tag.level == 0:
                            category_id = tag.id
                            logger.debug(f"图片 {image_id} 分类: {tag.name} (ID={tag.id})")
                            break
                
                image = {
                    "id": image_model.id,
                    "file_type": image_model.file_type,
                    "description": image_model.description,
                    "tags": [t.name for t in image_model.tags] if image_model.tags else [],
                    "embedding": image_model.embedding,
                    "original_url": image_model.original_url,
                    "category_id": category_id,  # 保存分类 ID
                }
                
                # 获取配置
                allowed_extensions = await config_repository.get_value(
                    session, "vision_allowed_extensions", "jpg,jpeg,png,webp,bmp"
                )
                convert_gif = (await config_repository.get_value(
                    session, "vision_convert_gif", "true"
                ) or "true").lower() == "true"
            
            file_ext = image.get("file_type", "") or ""
            
            # 如果已有描述和标签，直接生成向量
            if image.get("description") and image.get("tags"):
                logger.info(f"图片 {image_id} 已有标签，只生成向量")
                await embedding_service.save_embedding_for_image(
                    image_id, image["description"], image["tags"]
                )
                
                await self._mark_task_completed(task.id, {
                    "image_id": image_id,
                    "tags": image["tags"],
                    "description": image["description"],
                })
                logger.info(f"图片 {image_id} 处理完成")
                return
            
            # 检查格式
            allowed_list = [ext.strip().lower() for ext in (allowed_extensions or "").split(",")]
            
            if file_ext == "gif" and not convert_gif:
                await self._skip_task(task.id, image_id, "GIF not converted")
                return
            
            if file_ext and file_ext not in allowed_list and file_ext != "gif":
                await self._skip_task(task.id, image_id, f"Extension {file_ext} not allowed")
                return
            
            # 获取文件内容
            file_content = await storage_service.get_file_content(image_id)
            
            # 如果本地和远程都没有，尝试 original_url
            if file_content is None and image.get("original_url"):
                try:
                    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                        resp = await client.get(image["original_url"])
                        if resp.status_code == 200:
                            file_content = resp.content
                            logger.info(f"从 original_url 下载成功")
                except Exception as e:
                    logger.warning(f"从 original_url 下载失败: {e}")
            
            if file_content is None:
                raise ValueError(f"无法获取图片内容: image_id={image_id}")
            
            # 确定 MIME 类型
            mime_type = get_mime_type(file_ext)
            
            # GIF 转 PNG
            if file_ext == "gif" and convert_gif:
                file_content, mime_type = await self._convert_gif_to_png(file_content)
            
            # 分析图片（传递分类 ID 以使用分类专用提示词）
            analysis = await vision_service.analyze_image_base64(
                file_content, mime_type, category_id=image.get("category_id")
            )
            
            # 更新数据库 - 保存分析结果
            async with async_session_maker() as session:
                image_model = await image_repository.get_with_tags(session, image_id)
                if image_model:
                    await image_repository.update_image(
                        session, image_model,
                        description=analysis.description,
                    )
                    await image_tag_repository.set_image_tags(
                        session, image_id, analysis.tags, source="ai"
                    )
                    
                await session.commit()
            
            # 生成并保存向量（失败时优雅降级，独立事务）
            await embedding_service.save_embedding_for_image(
                image_id, analysis.description, analysis.tags
            )
            
            # 获取合并后的完整标签列表（用户标签 + AI 标签），按 source 排序：用户标签优先
            async with async_session_maker() as session:
                tags_with_source = await image_repository.get_image_tags_with_source(session, image_id)
                # 排序：user/system 标签优先，ai 标签其次，同级别按 sort_order 排序
                sorted_tags = sorted(
                    tags_with_source,
                    key=lambda t: (0 if t["source"] in ("user", "system") else 1, t["sort_order"])
                )
                final_tags = [t["name"] for t in sorted_tags]
            
            # 完成
            await self._mark_task_completed(task.id, {
                "image_id": image_id,
                "tags": final_tags,
                "description": analysis.description,
            })
            logger.info(f"图片 {image_id} 处理完成")
            
            # 回调 - 使用合并后的完整标签
            if callback_url:
                asyncio.create_task(self._send_callback(
                    callback_url, image_id, task.id, True, 
                    final_tags, analysis.description
                ))
            
        except Exception as e:
            logger.error(f"处理图片 {image_id} 失败: {e}")
            await self._mark_task_failed(task.id, str(e))
            
            if callback_url:
                asyncio.create_task(self._send_callback(
                    callback_url, image_id, task.id, False, 
                    error=str(e)
                ))
            raise
    
    async def _skip_task(self, task_id: str, image_id: int, reason: str):
        """跳过任务（格式不支持等）"""
        logger.info(f"图片 {image_id} 跳过: {reason}")
        
        # 生成空向量
        embedding = await embedding_service.get_embedding("")
        async with async_session_maker() as session:
            image_model = await image_repository.get_by_id(session, image_id)
            if image_model:
                await image_repository.update_image(session, image_model, embedding=embedding)
            await session.commit()
        
        await self._mark_task_completed(task_id, {
            "image_id": image_id,
            "skipped": True,
            "reason": reason,
        })
    
    async def _convert_gif_to_png(self, content: bytes) -> tuple[bytes, str]:
        """将 GIF 转换为 PNG"""
        def _convert(data: bytes) -> bytes:
            from PIL import Image as PILImage
            img = PILImage.open(io.BytesIO(data))
            if hasattr(img, 'n_frames') and img.n_frames > 1:
                img.seek(0)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            output = io.BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()
        
        try:
            converted = await asyncio.to_thread(_convert, content)
            logger.info("GIF 已转换为 PNG")
            return converted, "image/png"
        except Exception as e:
            logger.warning(f"GIF 转换失败: {e}，使用原始格式")
            return content, "image/gif"
    
    async def _send_callback(
        self,
        url: str,
        image_id: int,
        task_id: str,
        success: bool,
        tags: list[str] | None = None,
        description: str | None = None,
        error: str | None = None,
    ):
        """发送回调"""
        from imgtag.services.storage_service import storage_service
        
        try:
            async with async_session_maker() as session:
                image = await image_repository.get_with_tags(session, image_id)
                if not image:
                    return
                image_url = await storage_service.get_read_url(image) or ""
            
            callback_data = {
                "image_id": image_id,
                "task_id": task_id,
                "success": success,
                "image_url": image_url,
                "tags": tags or [],
                "description": description or "",
                "width": image.width if image else None,
                "height": image.height if image else None,
                "error": error,
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=callback_data)
                logger.info(f"回调 {url} 完成: {resp.status_code}")
        except Exception as e:
            logger.warning(f"回调 {url} 失败: {e}")


# 全局实例
task_queue = TaskQueueService()
