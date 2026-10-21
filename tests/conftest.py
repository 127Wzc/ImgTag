"""回归测试隔离搜索配置、限流状态和加密密钥，不使用真实凭据。"""

from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from imgtag.core import crypto
from imgtag.core.search_limits import SearchPolicy
from imgtag.services.search_guard_service import search_guard


@pytest.fixture(autouse=True)
def isolated_search_guard(monkeypatch):
    monkeypatch.setattr(search_guard, "load_policy", AsyncMock(return_value=SearchPolicy()))
    monkeypatch.setattr(search_guard, "_callers", {})


@pytest.fixture(autouse=True)
def isolated_encryption_key(monkeypatch):
    # 自动测试不用生产环境变量或真实数据库中的加密密钥。
    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))
