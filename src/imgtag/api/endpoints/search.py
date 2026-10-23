#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Search API endpoints.

Handles similarity and hybrid search requests.
"""


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.search_guards import get_search_user, guard_smart_search
from imgtag.core.logging_config import get_logger
from imgtag.core.search_logging import traced_search
from imgtag.core.exceptions import EmbeddingAPIError
from imgtag.db import get_async_session
from imgtag.schemas import (
    SimilarSearchRequest,
    SimilarSearchResponse,
)
from imgtag.services.search_service import search_service

logger = get_logger(__name__)

router = APIRouter()


@router.post("/similar", response_model=SimilarSearchResponse, dependencies=[Depends(guard_smart_search)])
@traced_search("smart.legacy")
async def search_similar(
    request: SimilarSearchRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: dict | None = Depends(get_search_user),
):
    """Vector similarity search with optional tag weighting.

    Args:
        request: Search parameters.
        session: Database session.

    Returns:
        Search results with similarity scores.
    """
    logger.debug("相似度搜索: text_chars=%s filter_tags=%s size=%s", len(request.text), len(request.tags or []), request.size)

    try:
        return await search_service.search_request(session, request, current_user)
    except HTTPException:
        raise
    except EmbeddingAPIError:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
