#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
图像API端点
处理与图像相关的请求
"""

import time
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional

from app.models.image import ImageCreate, ImageResponse, SearchByTags
from app.db.pg_vector import PGVectorDB
from app.services.text_embedding import TextEmbedding
from app.core.logging_config import get_logger, get_perf_logger
from app.core.config import settings

# 获取日志记录器
logger = get_logger(__name__)
perf_logger = get_perf_logger()

# 创建全局实例
db = PGVectorDB()
embedding_tool = TextEmbedding()

router = APIRouter()

# 依赖项
def get_db():
    """依赖项：获取数据库连接"""
    return db

def get_embedding():
    """依赖项：获取文本嵌入工具"""
    return embedding_tool

@router.post("/", response_model=dict)
async def create_image(
    image: ImageCreate,
    db: PGVectorDB = Depends(get_db),
    embedding_tool: TextEmbedding = Depends(get_embedding)
):
    """创建图像记录
    
    为图像生成向量嵌入并存储到数据库
    """
    start_time = time.time()
    logger.info(f"创建图像: {image.image_url}")
    
    try:
        # 生成向量嵌入
        vector_gen_start = time.time()
        if image.description:
            embedding_vector = embedding_tool.get_embedding_combined(
                image.description, 
                image.tags
            ).tolist()
        else:
            # 如果没有描述，只使用标签生成向量
            tags_text = ", ".join(image.tags)
            embedding_vector = embedding_tool.get_embedding(tags_text).tolist()
        
        vector_gen_time = time.time() - vector_gen_start
        perf_logger.info(f"向量生成耗时: {vector_gen_time:.4f}秒")
        
        # 插入数据库
        new_id = db.insert_image(
            image.image_url,
            image.tags,
            embedding_vector,
            image.description
        )
        
        if not new_id:
            raise HTTPException(status_code=500, detail="数据库插入失败")
        
        total_time = time.time() - start_time
        perf_logger.info(f"图像创建总耗时: {total_time:.4f}秒")
        
        return {
            "id": new_id,
            "message": "图像创建成功",
            "process_time": f"{total_time:.4f}秒"
        }
    except Exception as e:
        logger.error(f"创建图像失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建图像失败: {str(e)}")

@router.post("/search/tags/", response_model=List[ImageResponse])
async def search_by_tags(
    request: SearchByTags,
    db: PGVectorDB = Depends(get_db)
):
    """通过标签搜索图像"""
    start_time = time.time()
    logger.info(f"按标签搜索: {request.tags}, 限制: {request.limit}")
    
    try:
        results = db.search_by_tags(request.tags, limit=request.limit)
        
        # 转换为响应模型
        response = []
        for img in results:
            response.append(ImageResponse(
                id=img["id"],
                image_url=img["image_url"],
                tags=img["tags"],
                description=img["description"]
            ))
        
        process_time = time.time() - start_time
        perf_logger.info(f"标签搜索耗时: {process_time:.4f}秒")
        
        return response
    except Exception as e:
        logger.error(f"标签搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"标签搜索失败: {str(e)}")

@router.put("/{image_id}/tags/", response_model=dict)
async def update_image_tags(
    image_id: int,
    tags: List[str],
    db: PGVectorDB = Depends(get_db)
):
    """更新图像标签"""
    start_time = time.time()
    logger.info(f"更新图像标签: ID {image_id}, 新标签: {tags}")
    
    try:
        success = db.update_image_tags(image_id, tags)
        
        if not success:
            raise HTTPException(status_code=500, detail="更新标签失败")
        
        process_time = time.time() - start_time
        
        return {
            "message": "标签更新成功",
            "process_time": f"{process_time:.4f}秒"
        }
    except Exception as e:
        logger.error(f"更新标签失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新标签失败: {str(e)}") 