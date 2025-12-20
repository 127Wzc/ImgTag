#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
配置 API 端点
管理系统配置的读取和更新
"""

from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from imgtag.db import config_db
from imgtag.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


class ConfigUpdate(BaseModel):
    """配置更新请求"""
    configs: Dict[str, str]


@router.get("/", response_model=Dict[str, Any])
async def get_all_config():
    """获取所有配置（密钥会被遮挡）"""
    logger.info("获取所有配置")
    try:
        return config_db.get_all(include_secrets=False)
    except Exception as e:
        logger.error(f"获取配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.get("/{key}")
async def get_config(key: str):
    """获取单个配置项"""
    logger.info(f"获取配置: {key}")
    value = config_db.get(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"配置项 {key} 不存在")
    
    # 如果是密钥类型，遮挡显示
    if "key" in key.lower() and value:
        return {"key": key, "value": "******", "has_value": True}
    
    return {"key": key, "value": value}


@router.put("/", response_model=Dict[str, str])
async def update_configs(request: ConfigUpdate):
    """批量更新配置"""
    logger.info(f"更新配置: {list(request.configs.keys())}")
    
    try:
        # 过滤掉值为 "******" 的项（表示未修改的密钥）
        filtered_configs = {
            k: v for k, v in request.configs.items() 
            if v != "******"
        }
        
        if not filtered_configs:
            return {"message": "没有需要更新的配置"}
        
        success = config_db.update_multiple(filtered_configs)
        
        if not success:
            raise HTTPException(status_code=500, detail="更新配置失败")
        
        return {"message": f"成功更新 {len(filtered_configs)} 个配置项"}
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")


@router.put("/{key}")
async def update_single_config(key: str, value: str):
    """更新单个配置项"""
    logger.info(f"更新单个配置: {key}")
    
    try:
        is_secret = "key" in key.lower()
        success = config_db.set(key, value, is_secret=is_secret)
        
        if not success:
            raise HTTPException(status_code=500, detail="更新配置失败")
        
        return {"message": f"配置项 {key} 更新成功"}
    except Exception as e:
        logger.error(f"更新配置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")
