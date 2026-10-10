"""使用临时表单配置测试模型，不修改已保存配置。"""

import asyncio
import time

import httpx

from imgtag.core.config_cache import config_cache
from imgtag.core.logging_config import get_logger
from imgtag.schemas.model_test import ModelListResponse, ModelTestRequest, ModelTestResponse
from imgtag.services.embedding_service import EmbeddingService, ONNXEmbeddingModel
from imgtag.services.vision_service import VisionService

logger = get_logger(__name__)


async def _resolve_api_key(kind: str, api_key: str | None) -> str:
    """省略或遮挡的密钥使用服务器原值，显式空字符串不回退。"""
    if api_key is None or api_key == "******":
        api_key = await config_cache.get(f"{kind}_api_key", "") or ""
    return api_key.strip()


def _validate_api_base(api_base: str) -> str:
    api_base = api_base.strip().rstrip("/")
    url = httpx.URL(api_base)
    if url.scheme not in ("http", "https") or not url.host:
        raise ValueError("请填写有效的 API 地址")
    return api_base


async def fetch_vision_models(
    api_base_url: str | None = None,
    api_key: str | None = None,
) -> ModelListResponse:
    """获取视觉模型列表，与模型测试使用相同的密钥回退规则。"""
    try:
        if api_base_url is None:
            api_base_url = await config_cache.get("vision_api_base_url", "https://api.openai.com/v1") or ""
        api_base = _validate_api_base(api_base_url)
        api_key = await _resolve_api_key("vision", api_key)
        if not api_key:
            raise ValueError("API 密钥未配置")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{api_base}/models", headers={"Authorization": f"Bearer {api_key}"}
            )
        if response.status_code != 200:
            raise ValueError(f"API 返回 {response.status_code}")
        data = response.json()
        items = data if isinstance(data, list) else data["data"]
        models = sorted({item["id"] for item in items if isinstance(item.get("id"), str) and item["id"]})
        return ModelListResponse(models=models)
    except httpx.TimeoutException:
        logger.warning("获取视觉模型列表超时")
        return ModelListResponse(error="请求超时")
    except (httpx.RequestError, httpx.InvalidURL):
        logger.warning("获取视觉模型列表连接失败")
        return ModelListResponse(error="无法连接到 API，请检查地址和网络")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "模型列表返回的数据格式无效"
        if api_key:
            message = message.replace(api_key, "******")
        logger.warning("获取视觉模型列表失败: %s", message)
        return ModelListResponse(error=message)


async def test_model_config(request: ModelTestRequest) -> ModelTestResponse:
    """执行一次最小请求；脱敏密钥从服务器配置中读取。"""
    started = time.perf_counter()
    api_key = request.api_key
    try:
        model_name = request.model.strip()
        if not model_name:
            raise ValueError("模型名称不能为空")
        if request.kind == "embedding" and request.mode == "local":
            # 模型加载与推理都可能耗时，避免阻塞状态轮询等其他请求。
            model = await asyncio.to_thread(
                ONNXEmbeddingModel, model_name, request.hf_endpoint.strip()
            )
            embedding = await asyncio.to_thread(model.encode, "向量模型连接测试")
            dimensions = len(embedding)
            message = f"测试成功，本地模型输出 {dimensions} 维向量"
        else:
            api_base = _validate_api_base(request.api_base_url)
            api_key = await _resolve_api_key(request.kind, api_key)
            if not api_key:
                raise ValueError("API 密钥未配置")

            dimensions = None
            if request.kind == "embedding":
                if request.dimensions is None:
                    raise ValueError("请填写向量维度")
                embedding = await EmbeddingService()._get_embedding_api(
                    "向量模型连接测试",
                    api_base=api_base,
                    api_key=api_key,
                    model=model_name,
                    dimensions=request.dimensions,
                )
                dimensions = len(embedding)
                message = f"测试成功，模型输出 {dimensions} 维向量"
            else:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        f"{api_base}/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": model_name,
                            "messages": [{"role": "user", "content": "连接测试，请只回复：OK"}],
                            "stream": False,
                        },
                    )
                if response.status_code != 200:
                    raise ValueError(f"API 请求失败: HTTP {response.status_code}")
                content = VisionService()._extract_content_from_response(response.json())
                if not content.strip():
                    raise ValueError("模型未返回有效文本")
                message = "测试成功，模型已正常返回文本"

        return ModelTestResponse(
            message=message,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            dimensions=dimensions,
        )
    except httpx.TimeoutException as exc:
        logger.warning("模型配置测试超时: kind=%s", request.kind)
        raise ValueError("模型测试超时，请稍后重试") from exc
    except (httpx.RequestError, httpx.InvalidURL) as exc:
        logger.warning("模型配置测试连接失败: kind=%s, type=%s", request.kind, type(exc).__name__)
        raise ValueError("无法连接到 API，请检查地址和网络") from exc
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, ImportError, RuntimeError) as exc:
        # 上游异常可能带有请求信息，避免向界面或日志回传真实密钥。
        message = str(exc).replace(api_key, "******") if api_key else str(exc)
        if not isinstance(exc, (ValueError, ImportError, RuntimeError)):
            message = "模型返回的数据格式无效"
        logger.warning("模型配置测试失败: kind=%s, error=%s", request.kind, message)
        raise ValueError(message) from exc
