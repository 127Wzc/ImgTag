import json
import threading

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from imgtag.api.endpoints.auth import require_admin
from imgtag.api.endpoints.config import router
from imgtag.core.config_cache import config_cache
from imgtag.schemas.model_test import ModelTestRequest
from imgtag.services import model_test_service


@pytest.fixture
def model_api(monkeypatch):
    reads = []

    async def get_config(key, default=None):
        reads.append(key)
        return "saved-secret" if key.endswith("_api_key") else default

    monkeypatch.setattr(config_cache, "get", get_config)

    def install_handler(handler):
        monkeypatch.setattr(
            httpx, "AsyncClient",
            lambda **kwargs: AsyncClient(transport=httpx.MockTransport(handler), **kwargs),
        )

    return reads, install_handler


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "******"])
async def test_vision_uses_text_and_saved_masked_key(model_api, key):
    reads, install_handler = model_api

    def handler(request):
        assert str(request.url) == "https://example.com/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer saved-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "unsaved-vision-model"
        assert isinstance(payload["messages"][0]["content"], str)
        assert "image" not in request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    install_handler(handler)
    result = await model_test_service.test_model_config(ModelTestRequest(
        kind="vision", api_base_url="https://example.com/v1/",
        api_key=key, model="unsaved-vision-model",
    ))

    assert "测试成功" in result.message
    assert result.dimensions is None
    assert reads == ["vision_api_key"]


@pytest.mark.asyncio
async def test_embedding_uses_unsaved_config_without_reading_saved_settings(model_api):
    reads, install_handler = model_api

    def handler(request):
        assert request.headers["Authorization"] == "Bearer new-secret"
        payload = json.loads(request.content)
        assert payload["model"] == "BAAI/bge-m3"
        assert "dimensions" not in payload
        return httpx.Response(200, json={"data": [{"embedding": [0.1] * 1024}]})

    install_handler(handler)
    result = await model_test_service.test_model_config(ModelTestRequest(
        kind="embedding", api_base_url="https://example.com/v1",
        api_key="new-secret", model="BAAI/bge-m3", dimensions=1024,
    ))

    assert result.dimensions == 1024
    assert reads == []


@pytest.mark.asyncio
async def test_explicitly_empty_key_does_not_use_saved_key(model_api):
    reads, _ = model_api
    with pytest.raises(ValueError, match="密钥未配置"):
        await model_test_service.test_model_config(ModelTestRequest(
            kind="vision", api_base_url="https://example.com/v1", api_key="", model="model",
        ))
    assert reads == []


@pytest.mark.asyncio
async def test_embedding_dimension_mismatch_is_a_test_failure(model_api):
    _, install_handler = model_api
    install_handler(lambda request: httpx.Response(200, json={"data": [{"embedding": [0.1] * 768}]}))

    with pytest.raises(ValueError, match="实际输出维度为 768.*配置维度 1024"):
        await model_test_service.test_model_config(ModelTestRequest(
            kind="embedding", api_base_url="https://example.com/v1",
            api_key="key", model="BAAI/bge-m3", dimensions=1024,
        ))


@pytest.mark.asyncio
async def test_local_model_load_and_encode_do_not_block_event_loop(monkeypatch):
    event_loop_thread = threading.get_ident()

    class LocalModel:
        def __init__(self, model, endpoint):
            assert threading.get_ident() != event_loop_thread
            assert model == "local-model"
            assert endpoint == "https://hf-mirror.com"

        def encode(self, text):
            assert threading.get_ident() != event_loop_thread
            return [0.1] * 512

    monkeypatch.setattr(model_test_service, "ONNXEmbeddingModel", LocalModel)
    result = await model_test_service.test_model_config(ModelTestRequest(
        kind="embedding", mode="local", model="local-model",
    ))
    assert result.dimensions == 512


@pytest.mark.asyncio
async def test_upstream_auth_failure_does_not_log_out_frontend(model_api):
    _, install_handler = model_api
    install_handler(lambda request: httpx.Response(401, text="Invalid token"))
    app = FastAPI()
    app.include_router(router, prefix="/config")
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/config/test-model", json={
            "kind": "vision", "model": "model", "api_base_url": "https://example.com/v1",
            "api_key": "wrong-key",
        })
    assert response.status_code == 400
    assert "HTTP 401" in response.json()["detail"]
    assert "wrong-key" not in response.text


@pytest.mark.asyncio
async def test_model_endpoint_requires_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/config")
    async with AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/config/test-model", json={"kind": "vision", "model": "model"})
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("key, expected", [(None, "saved-secret"), ("******", "saved-secret"), ("new-secret", "new-secret")])
async def test_model_dropdown_resolves_saved_or_new_key(model_api, key, expected):
    reads, install_handler = model_api

    def handler(request):
        assert str(request.url) == "https://example.com/v1/models"
        assert request.headers["Authorization"] == f"Bearer {expected}"
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}]})

    install_handler(handler)
    result = await model_test_service.fetch_vision_models("https://example.com/v1", key)
    assert result.models == ["a-model", "b-model"]
    assert result.error is None
    assert reads == (["vision_api_key"] if key != "new-secret" else [])


@pytest.mark.asyncio
async def test_model_dropdown_does_not_fall_back_after_key_is_cleared(model_api):
    reads, _ = model_api
    result = await model_test_service.fetch_vision_models("https://example.com/v1", "")
    assert result.models == []
    assert "密钥未配置" in result.error
    assert reads == []


@pytest.mark.asyncio
async def test_vision_testing_uses_newly_entered_key(model_api):
    reads, install_handler = model_api

    def handler(request):
        assert request.headers["Authorization"] == "Bearer new-secret"
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    install_handler(handler)
    await model_test_service.test_model_config(ModelTestRequest(
        kind="vision", model="model", api_base_url="https://example.com/v1", api_key="new-secret",
    ))
    assert reads == []
