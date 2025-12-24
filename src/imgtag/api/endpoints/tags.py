#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
标签 API 端点
处理与标签相关的请求
"""

from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends

from imgtag.api.endpoints.auth import require_admin

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
    sort_by: str = Query("usage_count", pattern="^(usage_count|name)$")
):
    """获取标签列表（用于自动补全）"""
    return db.get_tags(limit=limit, sort_by=sort_by)


@router.post("/sync", response_model=Dict[str, Any])
async def sync_tags(admin: Dict = Depends(require_admin)):
    """同步标签（需管理员权限）"""
    count = db.sync_tags()
    return {
        "message": f"标签同步完成，更新了 {count} 个标签",
        "count": count
    }


@router.put("/{tag_name}", response_model=Dict[str, Any])
async def rename_tag(tag_name: str, tag_update: TagUpdate, admin: Dict = Depends(require_admin)):
    """重命名标签（需管理员权限）"""
    if not tag_update.name:
        raise HTTPException(status_code=400, detail="新标签名不能为空")
    
    if tag_name == tag_update.name:
        raise HTTPException(status_code=400, detail="新标签名与原标签名相同")
    
    # 检查新标签名是否已存在（高效索引查询）
    if db.tag_exists(tag_update.name):
        raise HTTPException(status_code=409, detail=f"标签 '{tag_update.name}' 已存在，无法重命名")
    
    success = db.rename_tag(tag_name, tag_update.name)
    if not success:
        raise HTTPException(status_code=404, detail=f"标签 '{tag_name}' 不存在")
    
    return {
        "message": f"标签 '{tag_name}' 已重命名为 '{tag_update.name}'",
        "old_name": tag_name,
        "new_name": tag_update.name
    }


@router.delete("/{tag_name}", response_model=Dict[str, Any])
async def delete_tag(tag_name: str, admin: Dict = Depends(require_admin)):
    """删除标签（需管理员权限）"""
    success = db.delete_tag(tag_name)
    if not success:
        raise HTTPException(status_code=500, detail="删除标签失败")
    
    return {
        "message": f"标签 '{tag_name}' 已删除",
        "deleted_name": tag_name
    }
