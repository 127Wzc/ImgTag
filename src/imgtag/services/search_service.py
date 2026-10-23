"""搜索编排：显式标签过滤、词典匹配、精确基线与可选 ANN 候选。"""

import math
import re
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from imgtag.core.logging_config import get_logger
from imgtag.core.search_limits import SMART_SEARCH_LIMIT
from imgtag.core.search_logging import search_stage, traced_search
from imgtag.db.repositories import image_repository
from imgtag.db.repositories.vector_index import vector_index_repository
from imgtag.schemas.image import SimilarSearchRequest, SimilarSearchResponse, ImageWithSimilarity
from imgtag.services.embedding_service import embedding_service

logger = get_logger(__name__)


@dataclass(frozen=True)
class SearchOptions:
    enabled: bool = False
    ef_search: int = 40
    index_ready: bool = False


class SearchService:
    async def search_request(self, session, request: SimilarSearchRequest, user: dict | None) -> SimilarSearchResponse:
        admin = bool(user and user.get("role") == "admin")
        results = await self.search(
            session, text=request.text, tags=request.tags, category_id=request.category_id,
            resolution_id=request.resolution_id, limit=request.size,
            threshold=request.threshold, vector_weight=request.vector_weight, tag_weight=request.tag_weight,
            visible_to_user_id=user.get("id") if user and not admin else None, skip_visibility_filter=admin,
            release_connection=True,
        )
        response = SimilarSearchResponse.create(
            [ImageWithSimilarity(**image) for image in results], len(results), 1, request.size,
        )
        response.search_mode = getattr(results, "search_mode", "exact")
        return response

    async def load_options(self, session) -> SearchOptions:
        return SearchOptions(**await vector_index_repository.search_options(session))

    async def query_terms(self, session, text: str) -> dict[str, float]:
        matches = await image_repository.match_search_tags(session, text)
        occupied: list[tuple[int, int]] = []
        terms: dict[str, float] = {}
        seen = set()
        for name, is_subject in matches:
            normalized = name.casefold()
            if normalized in seen:
                continue
            # 拉丁名称按词边界匹配；中文允许自然语句中的连续词组。
            pattern = re.escape(name)
            if name[0].isascii() and name[0].isalnum():
                pattern = r"(?<![A-Za-z0-9_])" + pattern
            if name[-1].isascii() and name[-1].isalnum():
                pattern += r"(?![A-Za-z0-9_])"
            spans = [m.span() for m in re.finditer(pattern, text, re.IGNORECASE)]
            if not any(not any(start < b and end > a for a, b in occupied) for start, end in spans):
                continue
            occupied.extend(spans)
            seen.add(normalized)
            terms[name] = 2.0 if is_subject else 1.0
        return terms

    @traced_search("smart")
    async def search(
        self, session, *, text: str, tags=None, category_id=None, resolution_id=None,
        limit=SMART_SEARCH_LIMIT, threshold=0.15, vector_weight=0.7, tag_weight=0.3,
        visible_to_user_id=None, skip_visibility_filter=False, include_uploader=True,
        release_connection=False,
    ):
        if not 1 <= limit <= SMART_SEARCH_LIMIT:
            raise ValueError("智能搜索返回数量必须在 1 至 50 之间")
        text = text.strip()
        if not text and not (tags or category_id or resolution_id):
            raise ValueError("请输入搜索文字或选择筛选条件")
        total_weight = vector_weight + tag_weight
        if total_weight <= 0:
            raise ValueError("向量权重与标签权重不能同时为 0")
        vector_weight, tag_weight = vector_weight / total_weight, tag_weight / total_weight
        # 仅 HTTP/MCP 只读入口启用；通用调用保留调用方的事务所有权。
        if text and release_connection and session is not None:
            with search_stage("connection.release"):
                await session.close()
        vector = None
        if text:
            with search_stage("embedding", text_chars=len(text)) as stats:
                vector = await embedding_service.get_embedding(text, session=None if release_connection else session)
                stats["dimensions"] = len(vector) if vector else 0
        if text and (not vector or not all(
            type(value) in (int, float) and math.isfinite(value) for value in vector
        ) or not any(vector)):
            raise ValueError("查询向量无效，请检查嵌入模型服务")
        terms = {}
        if text:
            with search_stage("dictionary") as stats:
                terms = await self.query_terms(session, text)
                stats["matched_terms"] = len(terms)
        kwargs = dict(query_vector=vector, query_text=text, tags=tags,
                      category_id=category_id, resolution_id=resolution_id,
                      limit=limit, threshold=threshold,
                      vector_weight=vector_weight, tag_weight=tag_weight,
                      visible_to_user_id=visible_to_user_id, skip_visibility_filter=skip_visibility_filter,
                      include_uploader=include_uploader,
                      query_tag_weights=terms)
        options = SearchOptions()
        if vector:
            with search_stage("options") as stats:
                options = await self.load_options(session)
                stats.update(enabled=options.enabled, index_ready=options.index_ready,
                             configured_ef_search=options.ef_search, limit=limit)
        fallback_reason = "none"
        if options.enabled and options.index_ready:
            try:
                with search_stage("retrieval", mode="hnsw", candidate_limit=limit * 2,
                                  ef_search=max(options.ef_search, limit)) as stats:
                    async with session.begin_nested():
                        await image_repository.configure_hnsw(session, max(options.ef_search, limit))
                        results = await image_repository.hybrid_search(session, **kwargs, candidate_limit=limit * 2)
                    stats["returned"] = len(results)
                    return results
            except SQLAlchemyError as exc:
                # 保存点回滚后再精确查询，不能在已失败事务中直接重试。
                logger.warning("HNSW 查询不可用，回退精确搜索: %s", type(exc).__name__)
                fallback_reason = type(exc).__name__
        with search_stage("retrieval", mode="exact" if vector else "filters", fallback_reason=fallback_reason) as stats:
            results = await image_repository.hybrid_search(session, **kwargs)
            stats["returned"] = len(results)
            return results


search_service = SearchService()
