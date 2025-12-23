#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
外部 API 端点
专用于第三方接入，使用 API 密钥认证
"""

import time
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends, Query, Header

from imgtag.db import db, config_db
from imgtag.api.dependencies import require_api_key, verify_api_key
from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.services.task_queue import task_queue
from pydantic import BaseModel

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()


class ExternalImageCreate(BaseModel):
    """外部 API 创建图片请求"""
    image_url: str
    tags: List[str] = []
    description: str = ""
    auto_analyze: bool = True


def get_full_url(url: str) -> str:
    """将相对路径转换为完整 URL"""
    if not url:
        return url
    if url.startswith("http"):
        return url
    base_url = config_db.get("base_url", "")
    if base_url and url.startswith("/"):
        return base_url.rstrip("/") + url
    return url


@router.get("/random")
async def random_images(
    tags: List[str] = Query([], description="标签列表（AND 关系）"),
    count: int = Query(1, ge=1, le=50, description="返回数量"),
    include_full_url: bool = Query(True, description="是否返回完整 URL"),
    api_user: Dict = Depends(verify_api_key)
):
    """
    根据标签获取随机图片
    
    - **tags**: 标签列表，支持多个标签（AND 关系）
    - **count**: 返回图片数量，默认 1，最大 50
    - **include_full_url**: 是否返回完整 URL（拼接 base_url）
    - **api_key**: 鉴权密钥（参数或 Header 方式）
    
    返回示例：
    ```json
    {
        "images": [
            {
                "id": 1,
                "url": "http://example.com/uploads/xxx.jpg",
                "description": "图片描述",
                "tags": ["标签1", "标签2"]
            }
        ],
        "count": 1
    }
    ```
    """
    start_time = time.time()
    username = api_user.get('username') if api_user else 'anonymous'
    logger.info(f"[外部API] 随机图片请求: tags={tags}, count={count}, user={username}")
    
    try:
        # 获取 base_url 配置
        base_url = ""
        if include_full_url:
            base_url = config_db.get("base_url", "")
        
        # 查询随机图片
        result = db.get_random_images_by_tags(tags, count)
        
        images = []
        for img in result:
            url = img.get("image_url", "")
            if include_full_url and base_url and url.startswith("/"):
                url = base_url.rstrip("/") + url
            
            images.append({
                "id": img.get("id"),
                "url": url,
                "description": img.get("description", ""),
                "tags": img.get("tags", [])
            })
        
        process_time = time.time() - start_time
        perf_logger.info(f"[外部API] 随机图片查询耗时: {process_time:.4f}秒")
        
        return {
            "images": images,
            "count": len(images)
        }
    except Exception as e:
        logger.error(f"[外部API] 随机图片查询失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.post("/add-image")
async def analyze_image_from_url(
    request: ExternalImageCreate,
    api_user: Dict = Depends(require_api_key)
):
    """
    通过 URL 添加并分析图片
    
    图片会被下载保存到本地，原始 URL 将被记录。
    
    - **image_url**: 图片 URL（必填）
    - **tags**: 初始标签列表
    - **description**: 图片描述
    - **auto_analyze**: 是否自动分析（默认 true）
    - **api_key**: 鉴权密钥（必填）
    
    返回示例：
    ```json
    {
        "id": 123,
        "image_url": "/uploads/xxx.jpg",
        "original_url": "https://example.com/image.jpg",
        "tags": [],
        "description": "",
        "process_time": "0.05秒"
    }
    ```
    """
    from imgtag.services.upload_service import upload_service
    
    start_time = time.time()
    username = api_user.get('username')
    logger.info(f"[外部API] 添加图片: {request.image_url}, user={username}")
    
    try:
        # 下载并保存图片到本地
        file_path, local_url, content = await upload_service.save_remote_image(request.image_url)
        
        # 计算文件哈希
        import hashlib
        file_hash = hashlib.md5(content).hexdigest()
        
        # 插入记录，image_url 为本地地址，original_url 为原始远程地址
        new_id = db.insert_image(
            image_url=local_url,
            tags=request.tags,
            embedding=None,
            description=request.description,
            source_type="url",
            original_url=request.image_url,
            file_path=file_path,
            file_hash=file_hash
        )
        
        if not new_id:
            raise HTTPException(status_code=500, detail="数据库插入失败")
        
        # 如果需要自动分析，添加到任务队列
        if request.auto_analyze:
            task_queue.add_tasks([new_id])
        
        process_time = time.time() - start_time
        
        return {
            "id": new_id,
            "image_url": get_full_url(local_url),
            "original_url": request.image_url,
            "tags": request.tags,
            "description": request.description,
            "process_time": f"{process_time:.4f}秒"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[外部API] 添加图片失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加失败: {str(e)}")


@router.get("/image/{image_id}")
async def get_image_info(
    image_id: int,
    api_user: Dict = Depends(verify_api_key)
):
    """
    获取图片详情
    
    - **image_id**: 图片 ID
    - **api_key**: 鉴权密钥（可选）
    """
    username = api_user.get('username') if api_user else 'anonymous'
    logger.info(f"[外部API] 获取图片: id={image_id}, user={username}")
    
    image = db.get_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")
    
    return {
        "id": image.get("id"),
        "url": get_full_url(image.get("image_url")),
        "description": image.get("description", ""),
        "tags": image.get("tags", []),
        "created_at": image.get("created_at")
    }


@router.get("/search")
async def search_images(
    keyword: str = Query(None, description="关键词搜索"),
    tags: List[str] = Query([], description="标签筛选"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    api_user: Dict = Depends(verify_api_key)
):
    """
    搜索图片
    
    - **keyword**: 关键词（搜索描述）
    - **tags**: 标签列表
    - **limit**: 返回数量，最大 100
    - **offset**: 分页偏移
    - **api_key**: 鉴权密钥（可选）
    """
    username = api_user.get('username') if api_user else 'anonymous'
    logger.info(f"[外部API] 搜索图片: keyword={keyword}, tags={tags}, user={username}")
    
    try:
        result = db.search_images(
            tags=tags if tags else None,
            keyword=keyword,
            limit=limit,
            offset=offset
        )
        
        # 处理图片 URL
        images_with_full_url = []
        for img in result.get("images", []):
            img_copy = dict(img)
            img_copy["image_url"] = get_full_url(img.get("image_url", ""))
            images_with_full_url.append(img_copy)
        
        return {
            "images": images_with_full_url,
            "total": result.get("total", 0),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"[外部API] 搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")
