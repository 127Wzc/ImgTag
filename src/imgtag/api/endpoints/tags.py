#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
标签 API 端点
处理与标签相关的请求
"""

from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, Query

from imgtag.db import db
from imgtag.schemas import (
    Tag,
    TagUpdate,
    TagList
)
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/", response_model=List[Tag])
async def get_tags(
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str = Query("usage_count", regex="^(usage_count|name)$")
):
    """获取标签列表（用于自动补全）"""
    return db.get_tags(limit=limit, sort_by=sort_by)


@router.post("/sync", response_model=Dict[str, Any])
async def sync_tags():
    """同步标签（从图片数据重建标签表）"""
    count = db.sync_tags()
    return {
        "message": f"标签同步完成，更新了 {count} 个标签",
        "count": count
    }


@router.put("/{tag_name}", response_model=Dict[str, Any])
async def rename_tag(tag_name: str, tag_update: TagUpdate):
    """重命名标签（会更新所有包含该标签的图片）"""
    if not tag_update.name:
        raise HTTPException(status_code=400, detail="新标签名不能为空")
        
    success = db.rename_tag(tag_name, tag_update.name)
    if not success:
        raise HTTPException(status_code=500, detail="重命名标签失败")
    
    return {
        "message": f"标签 '{tag_name}' 已重命名为 '{tag_update.name}'",
        "old_name": tag_name,
        "new_name": tag_update.name
    }


@router.delete("/{tag_name}", response_model=Dict[str, Any])
async def delete_tag(tag_name: str):
    """删除标签（从所有图片中移除该标签）"""
    success = db.delete_tag(tag_name)
    if not success:
        raise HTTPException(status_code=500, detail="删除标签失败")
    
    return {
        "message": f"标签 '{tag_name}' 已删除",
        "deleted_name": tag_name
    }
