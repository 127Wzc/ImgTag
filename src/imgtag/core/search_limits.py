"""搜索保护配置及参数边界。"""

from dataclasses import dataclass


SMART_SEARCH_LIMIT = 50

SEARCH_DEFAULTS = {
    "search_hnsw_enabled": "false",
    "search_hnsw_ef_search": "40",
    "search_max_text_length": "200",
    "search_rate_limit": "20",
    "search_rate_interval": "1",
    "search_rate_unit": "minute",
}
SEARCH_CONFIG_BOUNDS = {
    "search_hnsw_ef_search": (40, 1000),
    "search_max_text_length": (1, 10000),
    "search_rate_limit": (1, 1000),
    "search_rate_interval": (1, 60),
}
SEARCH_TIME_UNITS = {"second": 1, "minute": 60, "hour": 3600}


def validate_search_config(configs: dict[str, str]) -> None:
    if "search_hnsw_enabled" in configs and configs["search_hnsw_enabled"] not in {"true", "false"}:
        raise ValueError("HNSW 开关必须是 true 或 false")
    for key, (minimum, maximum) in SEARCH_CONFIG_BOUNDS.items():
        if key not in configs:
            continue
        try:
            value = int(configs[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} 必须是 {minimum} 至 {maximum} 的整数") from None
        if not minimum <= value <= maximum:
            raise ValueError(f"{key} 必须是 {minimum} 至 {maximum} 的整数")
    if "search_rate_unit" in configs and configs["search_rate_unit"] not in SEARCH_TIME_UNITS:
        raise ValueError("搜索限流时间单位必须是 second、minute 或 hour")


@dataclass(frozen=True)
class SearchPolicy:
    max_text_length: int = 200
    rate_limit: int = 20
    window_seconds: int = 60

    @classmethod
    def from_config(cls, values: dict[str, str]) -> "SearchPolicy":
        config = SEARCH_DEFAULTS | values
        validate_search_config(config)
        return cls(
            max_text_length=int(config["search_max_text_length"]),
            rate_limit=int(config["search_rate_limit"]),
            window_seconds=int(config["search_rate_interval"]) * SEARCH_TIME_UNITS[config["search_rate_unit"]],
        )
