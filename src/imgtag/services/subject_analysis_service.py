"""核实主体输出，保持用户关联与AI视觉判断独立。"""

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


class SubjectCheck(BaseModel):
    subject_id: int | str
    status: Literal["supported", "uncertain", "conflict"]
    evidence: str = Field(default="", max_length=2000)


class SubjectObservation(BaseModel):
    subject_id: int | str | None = None
    position: str = Field(default="", max_length=300)
    appearance: str = Field(min_length=1, max_length=2000)
    multiple: bool = False


def review_subject_analysis(analysis: Any, contexts: list[dict]) -> dict:
    """校验输出ID、缺失核实保守降级；身份标签由程序归一。"""
    by_id = {str(c["subject_id"]): c for c in contexts}
    checks = {}
    for raw in analysis.subject_checks:
        check = SubjectCheck.model_validate(raw)
        key = str(check.subject_id)
        if key not in by_id or key in checks:
            raise ValueError("模型返回未知或重复的主体核实ID")
        if check.status == "supported" and not check.evidence.strip():
            check.status = "uncertain"
            check.evidence = "模型没有提供身份核实依据"
        checks[key] = check.model_dump()
    for key, context in by_id.items():
        if key not in checks:
            checks[key] = {"subject_id": context["subject_id"], "status": "uncertain", "evidence": "模型未返回该主体的核实结果"}
    observations = [SubjectObservation.model_validate(row).model_dump() for row in analysis.subject_observations]
    for row in observations:
        if row["subject_id"] is not None and str(row["subject_id"]) not in by_id:
            raise ValueError("模型观察引用了未知主体ID")
    for key, context in by_id.items():
        if context.get("status") == "confirmed" and checks[key]["status"] == "uncertain":
            checks[key] = {"subject_id": context["subject_id"], "status": "supported",
                           "evidence": "采用人工确认的主体身份；外观、动作和场景以图片为准"}
    supported = {key for key, check in checks.items() if check["status"] == "supported"}
    aliases: dict[str, set[str]] = {}
    for key, context in by_id.items():
        for name in [context["name"], *context.get("aliases", [])]:
            for variant in (name, name + "表情包"):
                aliases.setdefault(variant.strip().casefold(), set()).add(key)
    normalized = []
    for tag in analysis.tags:
        ids = aliases.get(tag.strip().casefold())
        # 歧义别名由显式ID核实结果决定，不按列表顺序猜身份。
        if ids is None:
            normalized.append(tag.strip())
    normalized.extend(by_id[key]["name"] for key in by_id if key in supported)
    analysis.tags = list(dict.fromkeys(t for t in normalized if t))
    unsafe_names = [n for key, c in by_id.items() if key not in supported
                    for n in [c["name"], *c.get("aliases", [])] if n]
    # OCR 中的姓名属于图片原文，不能据此判定模型错误断言了身份。
    identity_description = re.sub(
        r"(。\s*文字\s*[:：]).*?(?=。\s*心情/氛围\s*[:：])", "", analysis.description,
        flags=re.DOTALL,
    )
    if any(name.casefold() in identity_description.casefold() for name in unsafe_names):
        # 不用字符串替换拼接错误身份，退回可见观察；原始模型文本仍留在任务输入/响应中。
        visible = []
        for row in observations:
            appearance = row["appearance"]
            for name in unsafe_names:
                appearance = re.sub(re.escape(name), "角色", appearance, flags=re.IGNORECASE)
            visible.append(f"{row['position']}：{appearance}")
        replacement = "；".join(visible) or "画面主体身份待核实"
        # 表情包只降级主体段，保留 OCR、情绪、含义及原有标点格式。
        meme = re.fullmatch(
            r"(主体\s*[:：]\s*)(.*?)(。\s*文字\s*[:：].*?。\s*心情/氛围\s*[:：].*?。\s*表述含义\s*[:：].*)",
            analysis.description, re.DOTALL,
        )
        if meme:
            analysis.description = meme[1] + replacement.rstrip("。") + meme[3]
        else:
            analysis.description = replacement + "。关联身份存在冲突或暂无法核实。"
    return {"checks": list(checks.values()), "observations": observations,
            "subject_names": {key: c["name"] for key, c in by_id.items()},
            "definition_versions": {key: c.get("version") for key, c in by_id.items()}}
