#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Search API endpoints.

Handles similarity and hybrid search requests.
"""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.core.logging_config import get_logger, get_perf_logger
from imgtag.db import get_async_session
from imgtag.db.repositories import image_repository
from imgtag.schemas import (
    ImageWithSimilarity,
    SimilarSearchRequest,
    SimilarSearchResponse,
)
from imgtag.services import embedding_service

logger = get_logger(__name__)
perf_logger = get_perf_logger()

router = APIRouter()


@router.post("/similar", response_model=SimilarSearchResponse)
async def search_similar(
    request: SimilarSearchRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Vector similarity search with optional tag weighting.

    Args:
        request: Search parameters.
        session: Database session.

    Returns:
        Search results with similarity scores.
    """
    start_time = time.time()
    logger.info(f"相似度搜索: '{request.text[:50]}...'")

    try:
        # Generate query vector
        if request.tags:
            query_vector = await embedding_service.get_embedding_combined(
                request.text,
                request.tags,
            )
        else:
            query_vector = await embedding_service.get_embedding(request.text)

        # Execute hybrid search
        results = await image_repository.hybrid_search(
            session,
            query_vector=query_vector,
            query_text=request.text,
            limit=request.limit,
            threshold=request.threshold,
            vector_weight=request.vector_weight,
            tag_weight=request.tag_weight,
            category_id=request.category_id,
            resolution_id=request.resolution_id,
        )

        # Convert to response model
        images = [ImageWithSimilarity(**img) for img in results]

        response = SimilarSearchResponse(
            images=images,
            total=len(images),
        )

        process_time = time.time() - start_time
        perf_logger.info(f"相似度搜索总耗时: {process_time:.4f}秒")

        return response
    except Exception as e:
        logger.error(f"相似度搜索失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {e}")
