"""单次图片分析的补充要求，不写入全局或主体定义。"""

MAX_ANALYSIS_INSTRUCTIONS_LENGTH = 6000


def normalize_analysis_instructions(value: str | None) -> str:
    value = (value or "").strip()
    if len(value) > MAX_ANALYSIS_INSTRUCTIONS_LENGTH:
        raise ValueError("分析补充要求不能超过6000字")
    return value
