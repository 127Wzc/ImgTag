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
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger
from imgtag.core.storage_constants import StorageTaskStatus, get_mime_type
from imgtag.db.database import async_session_maker
from imgtag.db.repositories import (
    config_repository,
    image_repository,
    image_tag_repository,
    subject_repository,
    task_repository,
)
from imgtag.models.task import Task
from imgtag.services.embedding_service import embedding_service
from imgtag.services.storage_service import storage_service
from imgtag.services.subject_assignment_service import subject_assignment_service
from imgtag.services.subject_context_service import subject_context, subject_context_service
from imgtag.services.subject_memory_service import subject_memory_service
from imgtag.services.subject_analysis_service import review_subject_analysis
from imgtag.core.analysis_instructions import normalize_analysis_instructions
from imgtag.services.analysis_review_service import analysis_review_service
from imgtag.services.subject_extraction_service import subject_extraction_service
from imgtag.services.vision_service import vision_service

logger = get_logger(__name__)

# 队列处理的任务类型
QUEUE_TASK_TYPES = ["analyze_image", "rebuild_vector", "extract_subject"]


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
    
    async def enqueue_tasks(
        self,
        image_ids: list[int],
        task_type: str = "analyze_image",
        callback_url: str | None = None,
        force_analyze: bool = False,
        session: AsyncSession | None = None,
        analysis_instructions: str = "",
    ) -> dict[str, Any]:
        """串行化同图入队，返回新建、升级、等待和复用情况。"""
        analysis_instructions = normalize_analysis_instructions(analysis_instructions)
        force_analyze = force_analyze or bool(analysis_instructions)
        report: dict[str, Any] = {
            "added": 0, "upgraded": 0, "waiting": 0, "existing": 0,
            "missing": 0, "task_ids": [],
        }

        async def add_in_session(db_session: AsyncSession) -> None:
            # 后续锁读取会刷新实体，先保存本事务中已修改的字段。
            await db_session.flush()
            for image_id in sorted(set(image_ids)):
                image = await image_repository.get_by_id_for_update(db_session, image_id)
                if image is None:
                    report["missing"] += 1
                    continue
                active = await task_repository.list_active_for_image(db_session, image_id, task_type)
                matching = [t for t in active if normalize_analysis_instructions((t.payload or {}).get("analysis_instructions")) == analysis_instructions]
                pending = next((t for t in matching if t.status == "pending"), None)
                if pending is not None:
                    if force_analyze and not (pending.payload or {}).get("force_analyze"):
                        pending.payload = {**(pending.payload or {}), "force_analyze": True}
                        report["upgraded"] += 1
                    else:
                        report["existing"] += 1
                    report["task_ids"].append(pending.id)
                    continue
                if matching and not force_analyze:
                    report["existing"] += 1
                    report["task_ids"].append(matching[0].id)
                    continue
                payload: dict[str, Any] = {"image_id": image_id, "callback_url": callback_url}
                if analysis_instructions:
                    payload["analysis_instructions"] = analysis_instructions
                if force_analyze:
                    payload["force_analyze"] = True
                task_id = str(uuid.uuid4())
                await task_repository.create_task(
                    db_session, task_id=task_id, task_type=task_type, payload=payload,
                )
                report["added"] += 1
                report["waiting"] += int(bool(active))
                report["task_ids"].append(task_id)

        if session is not None:
            await add_in_session(session)
        else:
            async with async_session_maker() as db_session:
                await add_in_session(db_session)
                await db_session.commit()
        if report["task_ids"] and not self._running:
            asyncio.create_task(self.start_processing())
        logger.info(f"队列入队: type={task_type}, force={force_analyze}, result={report}")
        return report

    async def add_tasks(
        self,
        image_ids: list[int],
        task_type: str = "analyze_image",
        callback_url: str | None = None,
        force_analyze: bool = False,
        session: AsyncSession | None = None,
        analysis_instructions: str = "",
    ) -> int:
        """兼容内部调用；强制分析返回已接受数量（包括复用的强制任务）。"""
        report = await self.enqueue_tasks(image_ids, task_type, callback_url, force_analyze, session, analysis_instructions)
        return report["added"] + report["upgraded"] + (report["existing"] if force_analyze or analysis_instructions.strip() else 0)

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

    async def _resolve_subject_memory(
        self, *, image_id: int, file_content: bytes, mime_type: str,
    ) -> list[dict[str, Any]]:
        """明确关联优先；唯一人工标签可关联，其余标签只作为候选。"""
        async with async_session_maker() as session:
            # 与人工纠正共用图片锁，防止标签解析覆盖刚确认的主体。
            await image_repository.get_by_id_for_update(session, image_id)
            contexts = await subject_context_service.resolve(session, image_id, assign_from_tags=True)
            await session.commit()
        if contexts:
            return contexts
        match = await subject_memory_service.match_primary_subject(
            image_id=image_id, image_data=file_content, mime_type=mime_type,
        )
        subject_id = match.get("subject_id")
        if not subject_id:
            return []
        async with async_session_maker() as session:
            if match["status"] == "high_conf":
                await subject_assignment_service.assign_primary_subject(
                    session, image_id=image_id, subject_id=int(subject_id), actor_id=None,
                    confidence=match.get("confidence"), source="auto", state="confirmed", add_sample=False,
                )
                contexts = await subject_context_service.resolve(session, image_id)
                await session.commit()
                return contexts
            if match["status"] == "low_conf":
                if not await subject_assignment_service.has_pending_subject_suggestion(session, image_id):
                    await subject_assignment_service.create_subject_suggestion(
                        session, image_id=image_id, requester_id=None, subject_id=int(subject_id),
                        confidence=match.get("confidence"), comment="系统候选，等待管理员确认", add_sample=False,
                    )
                    await session.commit()
            subject = await subject_repository.get_by_id(session, int(subject_id))
            if subject and subject.is_active:
                return [subject_context(subject, source="matcher_candidate", confirmed=False)]
        return []

    # ==================== 任务处理 ====================
    
    async def _process_task(self, task: Task, worker_id: int):
        """处理单个任务"""
        payload = task.payload or {}
        image_id = payload.get("image_id")
        callback_url = payload.get("callback_url")
        analysis_instructions = normalize_analysis_instructions(payload.get("analysis_instructions"))
        force_analyze = bool(payload.get("force_analyze")) or bool(analysis_instructions)
        
        logger.info(f"任务 {task.id}, Worker {worker_id} 处理图片 ID: {image_id}, force={force_analyze}")
        
        try:
            if task.type == "extract_subject":
                result = await subject_extraction_service.process(task.id, payload)
                await self._mark_task_completed(task.id, result)
                return
            # ==================== 向量重建任务（不触发视觉分析） ====================
            if task.type == "rebuild_vector":
                async with async_session_maker() as session:
                    image_model = await image_repository.get_with_tags(session, image_id)
                    if not image_model:
                        raise ValueError(f"图片 {image_id} 不存在")

                    description = image_model.description or ""
                    # 仅使用主分类(level=0) + 普通标签(level=2)，排除分辨率(level=1)
                    tags = [
                        t.name for t in (image_model.tags or [])
                        if t.level in (0, 2)
                    ]

                saved = await embedding_service.save_embedding_for_image(
                    image_id, description, tags
                )

                await self._mark_task_completed(task.id, {
                    "image_id": image_id,
                    "saved": saved,
                    "used_description": description,
                    "used_tags": tags,
                })
                logger.info(f"图片 {image_id} 向量重建完成")
                return

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
                    "embedding_tags": [t.name for t in image_model.tags or [] if t.level in (0, 2)],
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
            
            # 如果已有描述和标签，直接生成向量（force_analyze 时跳过短路，重新走视觉分析）
            if not force_analyze and image.get("description") and image.get("tags"):
                logger.info(f"任务 {task.id}, 图片 {image_id} 未调用视觉模型：普通补全任务复用已有描述与标签，只重建向量")
                await embedding_service.save_embedding_for_image(
                    image_id, image["description"], image["embedding_tags"]
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

            # 主体记忆判定层（人工确认优先，其次自动匹配；stub 后端恒无命中）
            subject_contexts = await self._resolve_subject_memory(
                image_id=image_id,
                file_content=file_content,
                mime_type=mime_type,
            )
            
            # 保存主体快照用于写回前校验（候选资料也需要校验）。
            async with async_session_maker() as session:
                subject_snapshot = (
                    [] if any(c["source"] == "matcher_candidate" for c in subject_contexts)
                    else subject_contexts
                )
                attempt = await task_repository.begin_attempt(session, task.id)
                await session.commit()

            async def record_input(metadata: dict[str, Any]) -> None:
                # 调用前持久化，失败任务同样可在详情中查看当次输入。
                async with async_session_maker() as input_session:
                    task_row = await task_repository.get_by_id(input_session, task.id)
                    if task_row is not None:
                        task_row.result = {"analysis_input": metadata}
                    await input_session.commit()

            # 分类与主体资料分别传递，由视觉服务组装请求。
            analysis = await vision_service.analyze_image_base64(
                file_content,
                mime_type,
                category_id=image.get("category_id"),
                subject_contexts=subject_contexts,
                analysis_instructions=analysis_instructions,
                input_observer=record_input,
                request_context={"task_id": task.id, "image_id": image_id,
                                 "attempt": attempt, "force_analyze": force_analyze},
            )
            subject_analysis = review_subject_analysis(analysis, subject_contexts) if subject_contexts else None
            
            # 图片锁与人工纠正共用；主体或定义发生变化时丢弃旧结果，安排后续分析。
            async with async_session_maker() as session:
                image_model = await image_repository.get_by_id_for_update(session, image_id)
                if image_model is None:
                    raise ValueError(f"图片 {image_id} 已删除")
                await subject_repository.lock_by_ids(session, [c["subject_id"] for c in subject_snapshot])
                latest = await subject_context_service.resolve(session, image_id)
                if latest != subject_snapshot:
                    await self.add_tasks([image_id], force_analyze=True, session=session, analysis_instructions=analysis_instructions)
                    await session.commit()
                    await self._mark_task_completed(task.id, {
                        "image_id": image_id, "superseded": True,
                        "reason": "主体或定义已变化，旧结果未写入，已安排重新分析",
                        "analysis_input": analysis.request_metadata,
                    })
                    return
                # 以写回时的当前内容为备份，成功结果立即生效。
                current = await analysis_review_service.current(session, image_id)
                await analysis_review_service.history(session, image_model, current)
                image_model.embedding = None
                await image_repository.update_image(session, image_model, description=analysis.description)
                image_model.subject_analysis = subject_analysis
                await image_tag_repository.set_image_tags(session, image_id, analysis.tags, source="ai")
                await session.commit()

            # 获取合并后的完整标签列表（用户标签 + AI 标签），按 source 排序：用户标签优先
            async with async_session_maker() as session:
                tags_with_source = await image_repository.get_image_tags_with_source(session, image_id)
                # 排序：user/system 标签优先，ai 标签其次，同级别按 sort_order 排序
                sorted_tags = sorted(
                    tags_with_source,
                    key=lambda t: (0 if t["source"] in ("user", "system") else 1, t["sort_order"])
                )
                final_tags = [t["name"] for t in sorted_tags]
            
            # 使用最终完整标签生成向量，包含保留的人工标签和主体标签。
            saved = await embedding_service.save_embedding_for_image(
                image_id, analysis.description,
                [t["name"] for t in sorted_tags if t.get("level", 2) in (0, 2)],
            )
            # 完成
            await self._mark_task_completed(task.id, {
                "image_id": image_id,
                "tags": final_tags,
                "description": analysis.description,
                "vector_saved": saved,
                "analysis_input": analysis.request_metadata,
                "subject_analysis": subject_analysis,
                "analysis_raw_response": analysis.raw_response,
            })
            logger.info(f"图片 {image_id} 处理完成")
            
            # 回调 - 使用合并后的完整标签
            if callback_url:
                asyncio.create_task(self._send_callback(
                    callback_url, image_id, task.id, True, 
                    final_tags, analysis.description
                ))
            
        except Exception as e:
            logger.error(f"任务 {task.id}, 图片 {image_id} 处理失败: {e}", exc_info=True)
            await self._mark_task_failed(task.id, str(e))
            
            if callback_url:
                asyncio.create_task(self._send_callback(
                    callback_url, image_id, task.id, False, 
                    error=str(e)
                ))
            raise
    
    async def _skip_task(self, task_id: str, image_id: int, reason: str):
        """跳过任务（格式不支持等）"""
        logger.warning(f"任务 {task_id}, 图片 {image_id} 未调用视觉模型: {reason}")
        await self._mark_task_failed(task_id, f"未调用视觉模型: {reason}")

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
