"""当前分析编辑与只读历史响应。"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalysisContent(BaseModel):
    description: str = Field(max_length=12000)
    tags: list[str] = Field(max_length=200)


class CurrentAnalysisSave(AnalysisContent):
    expected_snapshot: dict


class RestoreAnalysisRequest(BaseModel):
    expected_snapshot: dict


class AnalysisVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    image_id: int
    state: str
    pending: bool
    revision: int
    description: str
    tags: list[str]
    subject_analysis: dict | None
    base_snapshot: dict
    created_at: datetime
