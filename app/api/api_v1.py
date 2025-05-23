#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API路由主文件
集中注册所有API路由
"""

from fastapi import APIRouter

from app.api.endpoints import images, search, system

# 创建API路由
api_router = APIRouter()

# 注册路由
api_router.include_router(images.router, prefix="/images", tags=["images"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(system.router, prefix="/system", tags=["system"]) 