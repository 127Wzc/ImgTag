"""主体提炼图片数量策略；默认少量参考图，管理员可调整。"""

SUBJECT_EXTRACTION_LIMIT_KEY = "subject_extraction_max_images"
DEFAULT_SUBJECT_EXTRACTION_MAX_IMAGES = 3
HARD_SUBJECT_EXTRACTION_MAX_IMAGES = 3


def parse_subject_extraction_limit(value: str | None) -> int:
    if value is None:
        return DEFAULT_SUBJECT_EXTRACTION_MAX_IMAGES
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("主体提炼图片上限必须是1至3之间的整数") from exc
    if not 1 <= limit <= HARD_SUBJECT_EXTRACTION_MAX_IMAGES:
        raise ValueError("主体提炼图片上限必须是1至3之间的整数")
    return limit


def validate_subject_extraction_config(configs: dict[str, str]) -> None:
    if SUBJECT_EXTRACTION_LIMIT_KEY in configs:
        parse_subject_extraction_limit(configs[SUBJECT_EXTRACTION_LIMIT_KEY])
