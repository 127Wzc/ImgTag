#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
搜索 API 端点
处理相似度搜索请求
"""

import time
from fastapi import APIRouter, HTTPException

from imgtag.db import db
from imgtag.services import embedding_service
from imgtag.schemas import (
    SimilarSearchRequest,
    SimilarSearchResponse,
    ImageWithSimilarity,
)
from imgtag.core.logging_config import get_logger, get_perf_logger

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()


@router.post("/similar", response_model=SimilarSearchResponse)
async def search_similar(request: SimilarSearchRequest):
    """向量相似度搜索"""
    start_time = time.time()
    logger.info(f"相似度搜索: '{request.text[:50]}...'")
    
    try:
        # 生成查询向量
        if request.tags:
            query_vector = await embedding_service.get_embedding_combined(
                request.text, 
                request.tags
            )
        else:
            query_vector = await embedding_service.get_embedding(request.text)
        
        # 执行混合搜索 (向量 + 标签权重)
        results = db.hybrid_search(
            query_vector=query_vector,
            query_text=request.text,
            limit=request.limit,
            threshold=request.threshold,
            vector_weight=request.vector_weight,
            tag_weight=request.tag_weight,
            category_id=request.category_id,
            resolution_id=request.resolution_id
        )
        
        # 转换为响应模型
        images = [ImageWithSimilarity(**img) for img in results]
        
        response = SimilarSearchResponse(
            images=images,
            total=len(images)
        )
        
        process_time = time.time() - start_time
        perf_logger.info(f"相似度搜索总耗时: {process_time:.4f}秒")
        
        return response
    except Exception as e:
        logger.error(f"相似度搜索失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")
