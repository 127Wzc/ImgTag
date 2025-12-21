#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
任务服务
管理异步任务的创建、执行和状态更新
"""

import asyncio
import uuid
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List

from imgtag.db import db
from imgtag.core.logging_config import get_logger
from imgtag.services import embedding_service, vision_service

logger = get_logger(__name__)


class TaskService:
    """任务服务类"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TaskService, cls).__new__(cls)
        return cls._instance
    
    def create_task(self, task_type: str, payload: Dict[str, Any]) -> str:
        """创建并启动任务"""
        task_id = str(uuid.uuid4())
        
        # 1. 创建数据库记录
        db.create_task(task_id, task_type, payload)
        logger.info(f"创建任务 {task_id} (类型: {task_type})")
        
        # 2. 异步执行任务
        asyncio.create_task(self._process_task_wrapper(task_id, task_type, payload))
        
        return task_id
    
    async def _process_task_wrapper(self, task_id: str, task_type: str, payload: Dict[str, Any]):
        """任务处理包装器"""
        try:
            # 更新状态为处理中
            db.update_task_status(task_id, "processing")
            
            # 执行具体逻辑
            result = await self._dispatch_task(task_type, payload)
            
            # 更新状态为完成
            db.update_task_status(task_id, "completed", result=result)
            logger.info(f"任务 {task_id} 完成")
            
        except Exception as e:
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            logger.error(f"任务 {task_id} 失败: {str(e)}")
            db.update_task_status(task_id, "failed", error=error_msg)

    async def _dispatch_task(self, task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """分发任务到具体的处理函数"""
        if task_type == "add_to_collection":
            return await self._handle_add_to_collection(payload)
        elif task_type == "vectorize_batch":
            return await self._handle_vectorize_batch(payload)
        else:
            raise ValueError(f"未知的任务类型: {task_type}")

    async def _handle_add_to_collection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理添加到收藏夹任务
        
        注意：收藏夹仅做关联，不修改标签和向量
        标签管理由专门的标签功能处理
        """
        collection_id = payload.get("collection_id")
        image_id = payload.get("image_id")
        
        if not collection_id or not image_id:
            raise ValueError("缺少 collection_id 或 image_id")
        
        # 验证收藏夹和图片存在
        collection = db.get_collection(collection_id)
        if not collection:
            raise ValueError(f"收藏夹 {collection_id} 不存在")
        
        image = db.get_image(image_id)
        if not image:
            raise ValueError(f"图片 {image_id} 不存在")
        
        # 收藏夹仅做关联，不修改标签和向量
        # 关联已在 API 层 add_image_to_collection 完成
        logger.info(f"图片 {image_id} 已添加到收藏夹 {collection['name']}")
        
        return {
            "success": True,
            "collection_name": collection["name"],
            "message": "收藏夹关联成功（不修改标签和向量）"
        }

    async def _handle_vectorize_batch(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理批量向量化任务"""
        image_ids = payload.get("image_ids", [])
        force = payload.get("force", False)
        
        processed_count = 0
        skipped_count = 0
        
        for image_id in image_ids:
            try:
                image = db.get_image(image_id)
                if not image:
                    continue
                
                # 如果已有向量且不强制更新，则跳过
                if image.get("embedding") and not force:
                    skipped_count += 1
                    continue
                
                description = image.get("description", "")
                tags = image.get("tags", [])
                
                if not description and not tags:
                    skipped_count += 1
                    continue
                
                embedding = await embedding_service.get_embedding_combined(
                    description,
                    tags
                )
                
                db.update_image(
                    image_id=image_id,
                    embedding=embedding
                )
                processed_count += 1
                
            except Exception as e:
                logger.error(f"批量向量化图片 {image_id} 失败: {str(e)}")
                # 继续处理下一个
        
        return {
            "processed": processed_count,
            "skipped": skipped_count,
            "total": len(image_ids)
        }
    
    def get_tasks(self, limit: int = 50, offset: int = 0, status: Optional[str] = None) -> Dict[str, Any]:
        """获取任务列表"""
        return db.get_tasks(limit, offset, status)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        return db.get_task(task_id)
    
    def cleanup_old_tasks(self, days: int = 7) -> int:
        """清理旧任务"""
        return db.cleanup_old_tasks(days)


# 全局实例
task_service = TaskService()
