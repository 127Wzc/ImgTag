#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置 API 端点
管理系统配置的读取和更新
"""

from typing import Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.endpoints.auth import require_admin
from imgtag.core.config_cache import config_cache
from imgtag.core.config_defaults import DEFAULT_CONFIG, DEFAULT_CATEGORY_PROMPTS
from imgtag.core.logging_config import get_logger
from imgtag.core.subject_extraction_limits import validate_subject_extraction_config
from imgtag.db.database import get_async_session
from imgtag.db.repositories import config_repository
from imgtag.schemas.model_test import ModelTestRequest, ModelTestResponse
from imgtag.services.model_test_service import test_model_config

logger = get_logger(__name__)

router = APIRouter()


class ConfigUpdate(BaseModel):
    """配置更新请求"""
    configs: Dict[str, str]


@router.post("/test-model", response_model=ModelTestResponse)
async def test_model(
    request: ModelTestRequest,
    admin: Dict = Depends(require_admin),
):
    """使用当前表单测试模型，需管理员权限。"""
    try:
        return await test_model_config(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/", response_model=Dict[str, Any])
async def get_all_config(
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """获取所有配置（密钥会被遮挡，需管理员权限）"""
    logger.info("获取所有配置")
    try:
        return await config_repository.get_all_configs(session, include_secrets=False)
    except Exception as e:
        logger.error(f"获取配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.get("/prompt-defaults")
async def get_prompt_defaults(admin: Dict = Depends(require_admin)):
    """只读返回可重置的提示词，用户保存的配置不受影响。"""
    return {"vision_prompt": DEFAULT_CONFIG["vision_prompt"],
            "category_prompts": DEFAULT_CATEGORY_PROMPTS}


@router.get("/{key}")
async def get_config(
    key: str,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """获取单个配置项（需管理员权限）"""
    logger.info(f"获取配置: {key}")
    value = await config_repository.get_value(session, key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"配置项 {key} 不存在")
    
    # 如果是密钥类型，遮挡显示
    if "key" in key.lower() and value:
        return {"key": key, "value": "******", "has_value": True}
    
    return {"key": key, "value": value}


@router.put("/", response_model=Dict[str, str])
async def update_configs(
    request: ConfigUpdate,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """批量更新配置（需管理员权限）"""
    logger.info(f"更新配置: {list(request.configs.keys())}")
    try:
        validate_subject_extraction_config(request.configs)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    
    try:
        # 过滤掉值为 "******" 的项（表示未修改的密钥）
        filtered_configs = {
            k: v for k, v in request.configs.items() 
            if v != "******"
        }
        
        if not filtered_configs:
            return {"message": "没有需要更新的配置"}
        
        success = await config_repository.update_multiple(session, filtered_configs)
        
        if not success:
            raise HTTPException(status_code=500, detail="更新配置失败")
        
        # 必须先 commit，确保数据真正写入数据库后再刷新缓存
        await session.commit()
        
        # 清除配置缓存并重新加载，确保新配置立即生效
        config_cache.clear()
        await config_cache.preload()
        logger.info("配置缓存已重新加载")
        
        # 如果更新了嵌入模型相关配置，重载模型以应用新设置
        embedding_related_keys = ["embedding_mode", "embedding_local_model", "hf_endpoint"]
        if any(key in filtered_configs for key in embedding_related_keys):
            from imgtag.services.embedding_service import EmbeddingService
            EmbeddingService.reload_model()
            logger.info("嵌入模型配置已更新，已重载模型")
        
        return {"message": f"成功更新 {len(filtered_configs)} 个配置项"}
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.put("/{key}")
async def update_single_config(
    key: str,
    value: str,
    admin: Dict = Depends(require_admin),
    session: AsyncSession = Depends(get_async_session),
):
    """更新单个配置项（需管理员权限）"""
    logger.info(f"更新单个配置: {key}")
    try:
        validate_subject_extraction_config({key: value})
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    
    try:
        is_secret = "key" in key.lower() or "secret" in key.lower()
        success = await config_repository.set_value(session, key, value, is_secret=is_secret)
        
        if not success:
            raise HTTPException(status_code=500, detail="更新配置失败")
            
        await session.commit()
        config_cache.clear()
        await config_cache.preload()
        
        # Check if model reload needed
        if key in ["embedding_mode", "embedding_local_model", "hf_endpoint"]:
            from imgtag.services.embedding_service import EmbeddingService
            EmbeddingService.reload_model()
        
        return {"message": f"配置项 {key} 更新成功"}
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")
