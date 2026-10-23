"""内部状态使用 config 存储，但不通过普通配置读写链路暴露。"""

from collections.abc import Iterable


ENCRYPTION_STATE_KEY = "__encryption_state"
HNSW_STATE_KEY = "__hnsw_index_state"
INTERNAL_CONFIG_KEYS = frozenset({ENCRYPTION_STATE_KEY, HNSW_STATE_KEY})


def validate_public_config_keys(keys: Iterable[str]) -> None:
    if INTERNAL_CONFIG_KEYS.intersection(keys):
        raise ValueError("内部配置不允许通过系统设置修改")
