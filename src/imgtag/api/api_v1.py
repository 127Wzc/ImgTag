#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
API 路由注册
"""

from fastapi import APIRouter

from imgtag.api.endpoints import (
    images, search, system, config, vectors, queue, collections, tags,
    tasks, auth, approvals, storage_endpoints,
)

api_router = APIRouter()

# 注册认证相关路由
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["认证"]
)

# 注册审批管理路由
api_router.include_router(
    approvals.router,
    prefix="/approvals",
    tags=["审批管理"]
)

# 注册图像相关路由
api_router.include_router(
    images.router,
    prefix="/images",
    tags=["图像管理"]
)

# 注册搜索相关路由
api_router.include_router(
    search.router,
    prefix="/search",
    tags=["搜索"]
)

# 注册系统相关路由
api_router.include_router(
    system.router,
    prefix="/system",
    tags=["系统"]
)

# 注册配置相关路由
api_router.include_router(
    config.router,
    prefix="/config",
    tags=["配置管理"]
)

# 注册向量管理路由
api_router.include_router(
    vectors.router,
    prefix="/vectors",
    tags=["向量管理"]
)

# 注册队列管理路由
api_router.include_router(
    queue.router,
    prefix="/queue",
    tags=["队列管理"]
)

# 注册收藏夹管理路由
api_router.include_router(
    collections.router, 
    prefix="/collections", 
    tags=["收藏夹管理"]
)

# 注册标签管理路由
api_router.include_router(
    tags.router, 
    prefix="/tags", 
    tags=["标签管理"]
)

# 注册任务管理路由
api_router.include_router(
    tasks.router, 
    prefix="/tasks", 
    tags=["任务管理"]
)

# 注册存储管理路由 (多端点存储)
api_router.include_router(
    storage_endpoints.router, 
    prefix="/storage", 
    tags=["存储管理"]
)

# 注册外部 API 路由（第三方接入，使用 API 密钥认证）
from imgtag.api.endpoints import external
api_router.include_router(
    external.router, 
    prefix="/external", 
    tags=["外部API"]
)

