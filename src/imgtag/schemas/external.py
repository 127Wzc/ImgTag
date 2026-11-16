"""外部图片添加的公共选项与 URL 请求。"""

from pydantic import BaseModel, Field, Json

from imgtag.core.analysis_instructions import AnalysisInstructions
from imgtag.schemas.task import CallbackHeaders


class ExternalImageOptions(BaseModel):
    tags: list[str] = Field(default_factory=list, description="用户自定义标签列表")
    description: str = Field(default="", description="用户提供的描述")
    category_id: int | None = Field(default=None, description="主分类ID")
    endpoint_id: int | None = Field(default=None, description="目标存储端点ID")
    auto_analyze: bool = Field(default=True, description="是否启用 AI 分析")
    analysis_instructions: AnalysisInstructions = Field(default="", max_length=6000, description="仅本次分析的补充要求")
    callback_url: str | None = Field(default=None, description="分析完成后的回调URL")
    callback_headers: CallbackHeaders = Field(default_factory=dict, repr=False, description="自定义回调请求头")
    is_public: bool = Field(default=True, description="是否公开可见")


class ExternalImageCreate(ExternalImageOptions):
    image_url: str = Field(..., description="图片URL")


class ExternalImageForm(ExternalImageOptions):
    callback_headers: Json[CallbackHeaders] = Field(default_factory=dict, repr=False,
        description="自定义回调请求头，JSON 对象字符串")
