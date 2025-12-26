#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
存储管理 API 端点
管理员备份文件到 S3 兼容存储
"""

from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from imgtag.db import db
from imgtag.services.s3_service import s3_service
from imgtag.api.endpoints.auth import require_admin
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


class SyncRequest(BaseModel):
    """同步请求"""
    image_ids: Optional[List[int]] = None  # 为空则同步全部


class SyncResult(BaseModel):
    """同步结果"""
    success: int
    failed: int
    errors: List[str]


@router.get("/status")
async def get_storage_status(_=require_admin):
    """获取存储状态统计"""
    try:
        stats = db.get_storage_status()
        s3_enabled = s3_service.is_enabled()
        return {
            **stats,
            "s3_enabled": s3_enabled
        }
    except Exception as e:
        logger.error(f"获取存储状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files")
async def get_storage_files(
    filter: str = "all",
    page: int = 1,
    page_size: int = 20,
    _=require_admin
):
    """
    获取文件存储状态列表
    
    Args:
        filter: all/local_only/s3_only/both
        page: 页码
        page_size: 每页数量
    """
    try:
        offset = (page - 1) * page_size
        result = db.get_storage_files(
            filter_type=filter,
            limit=page_size,
            offset=offset
        )
        return result
    except Exception as e:
        logger.error(f"获取文件列表失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-connection")
async def test_s3_connection(_=require_admin):
    """测试 S3 连接"""
    try:
        result = s3_service.test_connection()
        return result
    except Exception as e:
        logger.error(f"测试 S3 连接失败: {str(e)}")
        return {
            "success": False,
            "message": str(e)
        }


@router.post("/sync-to-s3", response_model=SyncResult)
async def sync_to_s3(request: SyncRequest, _=require_admin):
    """
    同步本地文件到 S3
    
    Args:
        image_ids: 指定图片 ID 列表，为空则同步所有仅本地文件
    """
    if not s3_service.is_enabled():
        raise HTTPException(status_code=400, detail="S3 未启用")
    
    try:
        success_count = 0
        failed_count = 0
        errors = []
        
        # 获取要同步的文件
        if request.image_ids:
            # 指定 ID
            for image_id in request.image_ids:
                result = await _sync_single_to_s3(image_id)
                if result["success"]:
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append(f"ID {image_id}: {result['error']}")
        else:
            # 同步所有仅本地文件
            files = db.get_storage_files(filter_type="local_only", limit=1000, offset=0)
            for file in files["files"]:
                result = await _sync_single_to_s3(file["id"])
                if result["success"]:
                    success_count += 1
                else:
                    failed_count += 1
                    if len(errors) < 10:  # 限制错误数量
                        errors.append(f"ID {file['id']}: {result['error']}")
        
        return SyncResult(success=success_count, failed=failed_count, errors=errors)
    except Exception as e:
        logger.error(f"批量同步到 S3 失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-to-local", response_model=SyncResult)
async def sync_to_local(request: SyncRequest, _=require_admin):
    """
    从 S3 同步文件到本地
    
    Args:
        image_ids: 指定图片 ID 列表，为空则同步所有仅 S3 文件
    """
    if not s3_service.is_enabled():
        raise HTTPException(status_code=400, detail="S3 未启用")
    
    try:
        success_count = 0
        failed_count = 0
        errors = []
        
        # 获取要同步的文件
        if request.image_ids:
            for image_id in request.image_ids:
                result = await _sync_single_to_local(image_id)
                if result["success"]:
                    success_count += 1
                else:
                    failed_count += 1
                    errors.append(f"ID {image_id}: {result['error']}")
        else:
            # 同步所有仅 S3 文件
            files = db.get_storage_files(filter_type="s3_only", limit=1000, offset=0)
            for file in files["files"]:
                result = await _sync_single_to_local(file["id"])
                if result["success"]:
                    success_count += 1
                else:
                    failed_count += 1
                    if len(errors) < 10:
                        errors.append(f"ID {file['id']}: {result['error']}")
        
        return SyncResult(success=success_count, failed=failed_count, errors=errors)
    except Exception as e:
        logger.error(f"批量同步到本地失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def _sync_single_to_s3(image_id: int) -> dict:
    """同步单个文件到 S3"""
    try:
        local_path = db.get_local_file_path(image_id)
        if not local_path:
            return {"success": False, "error": "本地文件不存在"}
        
        # 生成 S3 key
        import os
        filename = os.path.basename(local_path)
        s3_key = s3_service.generate_s3_key(filename)
        
        # 上传
        s3_service.upload_file(local_path, s3_key)
        
        # 更新数据库
        db.update_storage_info(
            image_id=image_id,
            s3_path=s3_key,
            storage_type="both"
        )
        
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def _sync_single_to_local(image_id: int) -> dict:
    """从 S3 同步单个文件到本地"""
    try:
        # 获取图片信息
        image = db.get_image(image_id)
        if not image:
            return {"success": False, "error": "图片不存在"}
        
        s3_path = image.get("s3_path")
        if not s3_path:
            return {"success": False, "error": "S3 路径为空"}
        
        # 构建本地路径
        from imgtag.core.config import settings
        import os
        filename = os.path.basename(s3_path)
        local_path = str(settings.UPLOADS_DIR / filename)
        
        # 下载
        s3_service.download_file(s3_path, local_path)
        
        # 更新数据库
        db.update_storage_info(
            image_id=image_id,
            local_exists=True,
            storage_type="both"
        )
        
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
