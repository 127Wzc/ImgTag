"""匿名智能搜索入口共用输入上限和滑动窗口频率保护（单进程）。"""

from collections import deque
from collections.abc import Sequence
from contextvars import ContextVar
from itertools import chain
from math import ceil
from time import monotonic

from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger
from imgtag.core.search_limits import SEARCH_DEFAULTS, SearchPolicy

logger = get_logger(__name__)
search_client_host: ContextVar[str] = ContextVar("search_client_host", default="unknown")


class SearchRejected(ValueError):
    def __init__(self, detail: str, status_code: int = 429, retry_after: int = 1):
        super().__init__(detail)
        self.status_code = status_code
        self.retry_after = retry_after


class SearchGuardService:
    MAX_CALLERS = 4096

    def __init__(self):
        self._callers: dict[str, deque[float]] = {}

    async def load_policy(self) -> SearchPolicy:
        values = {key: await config_cache.get(key, default) for key, default in SEARCH_DEFAULTS.items()}
        try:
            return SearchPolicy.from_config(values)
        except ValueError:
            logger.warning("搜索保护配置无效，使用默认限制")
            return SearchPolicy()

    @staticmethod
    def validate_inputs(policy: SearchPolicy, texts: Sequence[str | None], tags: list[str] | None) -> None:
        if tags is not None:
            if not isinstance(tags, list):
                raise SearchRejected("搜索标签必须是字符串数组", 422)
            if any(not isinstance(tag, str) for tag in tags):
                raise SearchRejected("搜索标签必须是字符串数组", 422)
        for text in chain(texts, tags or ()):
            if text is not None and (not isinstance(text, str) or len(text) > policy.max_text_length):
                raise SearchRejected(f"搜索文本或单个标签不能超过 {policy.max_text_length} 个字符", 422)

    async def check(
        self, caller: str, *, texts: Sequence[str | None] = (), tags: list[str] | None = None,
    ) -> None:
        policy = await self.load_policy()
        self.validate_inputs(policy, texts, tags)
        now = monotonic()
        cutoff = now - policy.window_seconds
        if caller not in self._callers:
            if len(self._callers) >= self.MAX_CALLERS:
                self._callers = {
                    key: window for key, window in self._callers.items()
                    if window and window[-1] > cutoff
                }
            if len(self._callers) >= self.MAX_CALLERS:
                raise SearchRejected("搜索服务繁忙，请稍后重试")
            self._callers[caller] = deque()
        window = self._callers[caller]
        while window and window[0] <= cutoff:
            window.popleft()
        if len(window) >= policy.rate_limit:
            retry_after = max(1, ceil(window[0] + policy.window_seconds - now))
            raise SearchRejected("搜索过于频繁，请稍后重试", retry_after=retry_after)
        # 检查与计数之间无 await；同时到达的请求也各计一次，不超额放行。
        window.append(now)


search_guard = SearchGuardService()
