"""回归测试隔离搜索配置、限流状态和加密密钥，不使用真实凭据。"""

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from imgtag.core import crypto
from imgtag.core.search_limits import SearchPolicy
from imgtag.services.search_guard_service import search_guard
from imgtag.services.search_service import SearchOptions, search_service


@pytest.fixture(autouse=True)
def isolated_search_guard(monkeypatch):
    monkeypatch.setattr(search_guard, "load_policy", AsyncMock(return_value=SearchPolicy()))
    monkeypatch.setattr(search_guard, "_callers", {})


@pytest.fixture(autouse=True)
def isolated_search_options(monkeypatch):
    # 接口用例默认不读取真实库配置；词典匹配与 ANN 分支在专门的行为用例中验证。
    monkeypatch.setattr(search_service, "load_options", AsyncMock(return_value=SearchOptions()))

    async def query_terms(session, text):
        return {text: 1.0}

    monkeypatch.setattr(search_service, "query_terms", query_terms)


@pytest.fixture(autouse=True)
def isolated_encryption_key(monkeypatch):
    # 自动测试不用生产环境变量或真实数据库中的加密密钥。
    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
