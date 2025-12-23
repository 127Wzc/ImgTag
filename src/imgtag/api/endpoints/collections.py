#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
收藏夹 API 端点
处理与收藏夹相关的请求
"""

import time
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends

from imgtag.api.endpoints.auth import get_current_user

from imgtag.db import db
from imgtag.services import embedding_service
from imgtag.schemas import (
    Collection,
    CollectionCreate,
    CollectionUpdate,
    CollectionList,
    CollectionImageAdd,
    ImageResponse,
)
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/", response_model=Dict[str, Any], status_code=201)
async def create_collection(collection: CollectionCreate, user: Dict = Depends(get_current_user)):
    """创建收藏夹（需登录）"""
    logger.info(f"创建收藏夹: {collection.name}")
    
    new_id = db.create_collection(
        name=collection.name,
        description=collection.description,
        parent_id=collection.parent_id
    )
    
    if not new_id:
        raise HTTPException(status_code=500, detail="创建收藏夹失败")
    
    return {
        "id": new_id,
        "message": "收藏夹创建成功"
    }


@router.get("/", response_model=List[Collection])
async def get_collections():
    """获取所有收藏夹"""
    return db.get_collections()


@router.get("/{collection_id}", response_model=Collection)
async def get_collection(collection_id: int):
    """获取单个收藏夹详情"""
    collection = db.get_collection(collection_id)
    if not collection:
        raise HTTPException(status_code=404, detail="收藏夹不存在")
    
    # 获取图片数量（如果 get_collection 没有返回，需要额外查询，但 db.get_collections 已经返回了）
    # 这里 db.get_collection 只返回基本信息，我们需要补充 image_count 等字段
    # 为了简单，我们复用 get_collections 的逻辑或者在 db 中增强 get_collection
    # 暂时先返回基本信息，前端列表页已经有数量了
    
    # 补全字段以匹配 Schema
    if "image_count" not in collection:
        collection["image_count"] = 0  # 详情页可能需要单独查询数量，这里简化
    if "sort_order" not in collection:
        collection["sort_order"] = 0
    if "is_public" not in collection:
        collection["is_public"] = True
    if "created_at" not in collection:
        from datetime import datetime
        collection["created_at"] = datetime.now()
    if "updated_at" not in collection:
        from datetime import datetime
        collection["updated_at"] = datetime.now()
        
    return collection


@router.put("/{collection_id}", response_model=Dict[str, Any])
async def update_collection(collection_id: int, collection: CollectionUpdate, user: Dict = Depends(get_current_user)):
    """更新收藏夹（需登录）"""
    success = db.update_collection(
        collection_id=collection_id,
        name=collection.name,
        description=collection.description,
        cover_image_id=collection.cover_image_id
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="更新收藏夹失败")
    
    return {"message": "收藏夹更新成功"}


@router.delete("/{collection_id}", response_model=Dict[str, Any])
async def delete_collection(collection_id: int, user: Dict = Depends(get_current_user)):
    """删除收藏夹（需登录）"""
    success = db.delete_collection(collection_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除收藏夹失败")
    
    return {"message": "收藏夹删除成功"}


@router.post("/{collection_id}/images", response_model=Dict[str, Any])
async def add_image_to_collection(collection_id: int, image_data: CollectionImageAdd, user: Dict = Depends(get_current_user)):
    """添加图片到收藏夹（需登录）"""
    image_id = image_data.image_id
    
    # 1. 添加到收藏夹
    success = db.add_image_to_collection(collection_id, image_id)
    if not success:
        raise HTTPException(status_code=500, detail="添加图片到收藏夹失败")
    
    # 2. 创建异步任务处理标签和向量更新
    from imgtag.services.task_service import task_service
    
    task_id = task_service.create_task(
        "add_to_collection",
        {"collection_id": collection_id, "image_id": image_id}
    )
    
    return {
        "message": "已添加到收藏夹，正在后台更新标签和向量",
        "task_id": task_id
    }


@router.delete("/{collection_id}/images/{image_id}", response_model=Dict[str, Any])
async def remove_image_from_collection(collection_id: int, image_id: int, user: Dict = Depends(get_current_user)):
    """从收藏夹移除图片（需登录）"""
    success = db.remove_image_from_collection(collection_id, image_id)
    if not success:
        raise HTTPException(status_code=500, detail="移除图片失败")
    
    return {"message": "已从收藏夹移除"}


@router.get("/{collection_id}/images", response_model=Dict[str, Any])
async def get_collection_images(
    collection_id: int, 
    limit: int = 20, 
    offset: int = 0
):
    """获取收藏夹内的图片"""
    return db.get_collection_images(collection_id, limit, offset)


@router.get("/{collection_id}/random", response_model=Dict[str, Any])
async def get_random_image(
    collection_id: int,
    tags: List[str] = None,
    include_children: bool = False
):
    """
    获取收藏夹中的随机图片
    
    - **collection_id**: 收藏夹 ID
    - **tags**: 可选，标签过滤
    - **include_children**: 是否包含子收藏夹中的图片
    """
    from fastapi import Query
    
    image = db.get_random_image_from_collection(
        collection_id=collection_id,
        tags=tags,
        include_children=include_children
    )
    
    if not image:
        raise HTTPException(status_code=404, detail="未找到符合条件的图片")
    
    return image
