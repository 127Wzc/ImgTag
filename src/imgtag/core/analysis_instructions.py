"""单次图片分析的补充要求，不写入全局或主体定义。"""

from typing import Annotated, Any

from pydantic import BeforeValidator

MAX_ANALYSIS_INSTRUCTIONS_LENGTH = 6000


def _empty_if_none(value: Any) -> Any:
    return "" if value is None else value


AnalysisInstructions = Annotated[str, BeforeValidator(_empty_if_none, json_schema_input_type=str | None)]


def normalize_analysis_instructions(value: str | None) -> str:
    value = (value or "").strip()
    if len(value) > MAX_ANALYSIS_INSTRUCTIONS_LENGTH:
        raise ValueError("分析补充要求不能超过6000字")
    return value
