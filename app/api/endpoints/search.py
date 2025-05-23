#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
搜索API端点
处理与搜索相关的请求
"""

import time
from fastapi import APIRouter, HTTPException, Depends
from typing import List

from app.models.image import ImageResponse, TextSearchRequest
from app.db.pg_vector import PGVectorDB
from app.services.text_embedding import TextEmbedding
from app.core.logging_config import get_logger, get_perf_logger

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

@router.post("/similar/", response_model=List[ImageResponse])
async def search_similar(
    request: TextSearchRequest,
    db: PGVectorDB = Depends(get_db),
    embedding_tool: TextEmbedding = Depends(get_embedding)
):
    """相似度搜索
    
    使用文本和可选的标签生成查询向量，并在数据库中搜索相似图像
    """
    start_time = time.time()
    logger.info(f"相似度搜索: '{request.text}'")
    
    try:
        # 生成查询向量
        vector_gen_start = time.time()
        if request.tags:
            query_vector = embedding_tool.get_embedding_combined(
                request.text, 
                request.tags
            ).tolist()
        else:
            query_vector = embedding_tool.get_embedding(request.text).tolist()
        
        vector_gen_time = time.time() - vector_gen_start
        perf_logger.info(f"查询向量生成耗时: {vector_gen_time:.4f}秒")
        
        # 执行相似度搜索
        results = db.search_similar_vectors(
            query_vector, 
            limit=request.limit,
            threshold=request.threshold
        )
        
        # 转换为响应模型
        response = []
        for img in results:
            response.append(ImageResponse(
                id=img["id"],
                image_url=img["image_url"],
                tags=img["tags"],
                description=img["description"],
                similarity=img["similarity"]
            ))
        
        total_time = time.time() - start_time
        perf_logger.info(f"相似度搜索总耗时: {total_time:.4f}秒")
        
        return response
    except Exception as e:
        logger.error(f"相似度搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"相似度搜索失败: {str(e)}") 