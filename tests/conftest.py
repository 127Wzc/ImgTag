"""回归测试不读取真实搜索配置，不在用例之间共享限流状态。"""

from unittest.mock import AsyncMock

import pytest

from imgtag.core.search_limits import SearchPolicy
from imgtag.services.search_guard_service import search_guard


@pytest.fixture(autouse=True)
def isolated_search_guard(monkeypatch):
    monkeypatch.setattr(search_guard, "load_policy", AsyncMock(return_value=SearchPolicy()))
    monkeypatch.setattr(search_guard, "_callers", {})
