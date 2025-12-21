#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
系统 API 端点
系统状态和健康检查
"""

from typing import Dict, Any
from fastapi import APIRouter

from imgtag.db import db
from imgtag.core.config import settings
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


from imgtag.services.embedding_service import embedding_service
from imgtag.db import config_db

@router.get("/status", response_model=Dict[str, Any])
async def get_system_status():
    """获取系统状态"""
    logger.info("获取系统状态")
    
    try:
        image_count = db.count_images()
        
        # 从配置数据库实时读取
        vision_model = config_db.get("vision_model", settings.VISION_MODEL)
        embedding_mode = config_db.get("embedding_mode", "local")
        
        if embedding_mode == "local":
            embedding_model = config_db.get("embedding_local_model", "BAAI/bge-small-zh-v1.5")
        else:
            embedding_model = config_db.get("embedding_model", settings.EMBEDDING_MODEL)
        
        return {
            "status": "running",
            "version": settings.PROJECT_VERSION,
            "image_count": image_count,
            "vision_model": vision_model,
            "embedding_model": embedding_model,
            "embedding_dimensions": embedding_service.get_dimensions(),
        }
    except Exception as e:
        logger.error(f"获取系统状态失败: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }


@router.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy"}


@router.get("/config", response_model=Dict[str, Any])
async def get_config():
    """获取当前配置（不含敏感信息）"""
    return {
        "project_name": settings.PROJECT_NAME,
        "project_version": settings.PROJECT_VERSION,
        "vision_api_base_url": settings.VISION_API_BASE_URL,
        "vision_model": settings.VISION_MODEL,
        "embedding_api_base_url": settings.EMBEDDING_API_BASE_URL,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
        "max_upload_size": settings.MAX_UPLOAD_SIZE,
        "allowed_extensions": list(settings.ALLOWED_EXTENSIONS),
    }


import httpx

@router.get("/models")
async def get_available_models():
    """获取可用的模型列表"""
    logger.info("获取可用模型列表")
    
    try:
        # 从配置数据库读取 API 配置
        api_base_url = config_db.get("vision_api_base_url", settings.VISION_API_BASE_URL)
        api_key = config_db.get("vision_api_key", "")
        
        if not api_base_url or not api_key:
            return {"models": [], "error": "未配置 API 地址或密钥"}
        
        # 调用 OpenAI 兼容的 /models 端点
        models_url = f"{api_base_url.rstrip('/')}/models"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                # 提取模型 ID 列表
                models = []
                if "data" in data:
                    models = [m.get("id") for m in data["data"] if m.get("id")]
                elif isinstance(data, list):
                    models = [m.get("id") for m in data if m.get("id")]
                
                return {"models": sorted(models)}
            else:
                return {"models": [], "error": f"API 返回 {response.status_code}"}
                
    except httpx.TimeoutException:
        return {"models": [], "error": "请求超时"}
    except Exception as e:
        logger.error(f"获取模型列表失败: {str(e)}")
        return {"models": [], "error": str(e)}


from fastapi import Depends, UploadFile, File
from fastapi.responses import JSONResponse
from imgtag.api.endpoints.auth import require_admin
from imgtag.db import config_db
import json
from datetime import datetime


@router.get("/export")
async def export_database(admin: Dict = Depends(require_admin)):
    """导出数据库记录（管理员）"""
    logger.info("开始导出数据库")
    
    try:
        # 导出图片数据（不含向量）
        images = db.export_all_images()
        
        # 导出标签数据
        tags = db.export_all_tags()
        
        # 导出收藏夹数据
        collections = db.export_all_collections()
        
        # 导出配置
        configs = config_db.get_all()
        
        # 导出用户（不含密码）
        users = db.export_all_users()
        
        export_data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "images": images,
            "tags": tags,
            "collections": collections,
            "configs": configs,
            "users": users,
            "stats": {
                "image_count": len(images),
                "tag_count": len(tags),
                "collection_count": len(collections),
                "user_count": len(users)
            }
        }
        
        logger.info(f"导出完成: {len(images)} 张图片, {len(tags)} 个标签, {len(collections)} 个收藏夹")
        
        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": f'attachment; filename="imgtag_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
            }
        )
    except Exception as e:
        logger.error(f"导出失败: {str(e)}")
        return {"error": str(e)}


@router.post("/import")
async def import_database(
    file: UploadFile = File(...),
    admin: Dict = Depends(require_admin)
):
    """导入数据库记录（管理员）"""
    logger.info(f"开始导入数据库: {file.filename}")
    
    try:
        content = await file.read()
        data = json.loads(content.decode('utf-8'))
        
        stats = {
            "images_imported": 0,
            "tags_imported": 0,
            "collections_imported": 0,
            "configs_imported": 0,
            "errors": []
        }
        
        # 导入配置
        if "configs" in data and data["configs"]:
            for key, value in data["configs"].items():
                try:
                    config_db.set(key, value)
                    stats["configs_imported"] += 1
                except Exception as e:
                    stats["errors"].append(f"配置 {key}: {str(e)}")
        
        # 导入标签
        if "tags" in data:
            for tag in data["tags"]:
                try:
                    db.import_tag(tag)
                    stats["tags_imported"] += 1
                except Exception as e:
                    stats["errors"].append(f"标签 {tag.get('name')}: {str(e)}")
        
        # 导入图片
        if "images" in data:
            for img in data["images"]:
                try:
                    db.import_image(img)
                    stats["images_imported"] += 1
                except Exception as e:
                    stats["errors"].append(f"图片 {img.get('id')}: {str(e)}")
        
        # 导入收藏夹
        if "collections" in data:
            for col in data["collections"]:
                try:
                    db.import_collection(col)
                    stats["collections_imported"] += 1
                except Exception as e:
                    stats["errors"].append(f"收藏夹 {col.get('name')}: {str(e)}")
        
        logger.info(f"导入完成: {stats}")
        
        return {
            "message": "导入完成",
            "stats": stats
        }
    except json.JSONDecodeError:
        return {"error": "无效的 JSON 文件"}
    except Exception as e:
        logger.error(f"导入失败: {str(e)}")
        return {"error": str(e)}
