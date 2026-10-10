"""模型配置测试的输入与输出。"""

from typing import Literal

from pydantic import BaseModel, Field


class ModelTestRequest(BaseModel):
    kind: Literal["vision", "embedding"]
    mode: Literal["api", "local"] = "api"
    model: str = Field(min_length=1)
    api_base_url: str = ""
    api_key: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    hf_endpoint: str = "https://hf-mirror.com"


class ModelTestResponse(BaseModel):
    message: str
    elapsed_ms: int
    dimensions: int | None = None


class ModelListRequest(BaseModel):
    api_base_url: str | None = None
    api_key: str | None = None


class ModelListResponse(BaseModel):
    models: list[str] = Field(default_factory=list)
    error: str | None = None
