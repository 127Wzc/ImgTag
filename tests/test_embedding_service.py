import json

import httpx
import pytest

from imgtag.services.embedding_service import EmbeddingService, config_cache


@pytest.fixture
def embedding_api(monkeypatch):
    """使用配置替身和内存 HTTP 服务，无需数据库或真实密钥。"""
    config = {
        "embedding_mode": "api",
        "embedding_api_base_url": "https://api.siliconflow.cn/v1/",
        "embedding_api_key": "test-key",
        "embedding_model": "BAAI/bge-m3",
        "embedding_dimensions": "1024",
    }

    async def get_config(key, default=None):
        return config.get(key, default)

    monkeypatch.setattr(config_cache, "get", get_config)
    client_class = httpx.AsyncClient

    def install_handler(handler):
        def create_client(**kwargs):
            return client_class(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", create_client)

    return config, install_handler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "BAAI/bge-m3",
        "Pro/BAAI/bge-m3",
        "BAAI/bge-large-zh-v1.5",
        "netease-youdao/bce-embedding-base_v1",
        "text-embedding-ada-002",
    ],
)
async def test_fixed_dimension_model_omits_dimensions(embedding_api, model):
    """固定维度模型拒绝 dimensions 时，仍应正常生成向量。"""
    config, install_handler = embedding_api
    config["embedding_model"] = model
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(request)
        if "dimensions" in payload:
            return httpx.Response(
                400, json={"code": 20015, "message": "The parameter is invalid."}
            )
        assert payload == {
            "model": model,
            "input": "图片描述 | 标签: 可爱",
            "encoding_format": "float",
        }
        assert str(request.url) == "https://api.siliconflow.cn/v1/embeddings"
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1024}]})

    install_handler(handler)

    embedding = await EmbeddingService().get_embedding_combined(" 图片描述 ", ["可爱"])

    assert embedding == [0.1] * 1024
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "text-embedding-3-small",
        "text-embedding-3-large",
        "Qwen/Qwen3-Embedding-8B",
        "Qwen/Qwen3-Embedding-4B",
        "Qwen/Qwen3-Embedding-0.6B",
        "Pro/Qwen/Qwen3-Embedding-8B",
    ],
)
async def test_resizable_model_keeps_configured_dimensions(embedding_api, model):
    """支持自定义维度的模型继续收到配置维度，避免破坏已有用法。"""
    config, install_handler = embedding_api
    config["embedding_model"] = model

    def handler(request):
        payload = json.loads(request.content)
        assert payload["dimensions"] == 1024
        assert payload["encoding_format"] == "float"
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1024}]})

    install_handler(handler)

    assert len(await EmbeddingService().get_embedding("图片描述")) == 1024


@pytest.mark.asyncio
async def test_api_dimension_mismatch_is_reported(embedding_api):
    """实际输出维度不一致时应在入库前明确报错。"""
    _, install_handler = embedding_api
    install_handler(
        lambda request: httpx.Response(200, json={"data": [{"embedding": [0.1] * 768}]})
    )

    with pytest.raises(ValueError, match="实际输出维度为 768.*配置维度 1024"):
        await EmbeddingService().get_embedding("图片描述")
