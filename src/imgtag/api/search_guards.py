"""匿名智能搜索入口的共享保护依赖，在查询或嵌入调用前执行。"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from imgtag.api.dependencies import get_user_by_api_key
from imgtag.api.endpoints.auth import get_current_user_optional
from imgtag.db import get_async_session
from imgtag.schemas.image import SimilarSearchRequest
from imgtag.services.search_guard_service import SearchRejected, search_guard


async def get_search_user(
    http_request: Request,
    user: dict | None = Depends(get_current_user_optional),
    session: AsyncSession = Depends(get_async_session),
) -> dict | None:
    """登录会话或有效 API Key 均视为已认证，不能仅凭请求头存在就豁免。"""
    if user is not None:
        return user
    key = (
        http_request.headers.get("x-api-key")
        or http_request.headers.get("api_key")
        or http_request.query_params.get("api_key")
    )
    if not key:
        scheme, _, token = http_request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer":
            key = token.strip()
    return await get_user_by_api_key(session, key) if key else None


async def guard_smart_search(
    request: SimilarSearchRequest, http_request: Request,
    user: dict | None = Depends(get_search_user),
) -> None:
    if user is not None:
        return
    host = http_request.client.host if http_request.client else "unknown"
    try:
        await search_guard.check(f"ip:{host}", texts=(request.text,), tags=request.tags)
    except SearchRejected as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.status_code == 429 else None
        raise HTTPException(exc.status_code, detail=str(exc), headers=headers) from exc

