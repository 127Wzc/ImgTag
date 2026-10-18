"""GIF 分析取帧数量约束。"""

GIF_FRAME_COUNT_KEY = "vision_gif_frame_count"
DEFAULT_GIF_FRAME_COUNT = 3


def parse_gif_frame_count(value: str | None) -> int:
    if value is None:
        return DEFAULT_GIF_FRAME_COUNT
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("GIF 取帧数量必须是1至3之间的整数") from exc
    if not 1 <= count <= 3:
        raise ValueError("GIF 取帧数量必须是1至3之间的整数")
    return count


def validate_gif_analysis_config(configs: dict[str, str]) -> None:
    if GIF_FRAME_COUNT_KEY in configs:
        parse_gif_frame_count(configs[GIF_FRAME_COUNT_KEY])
