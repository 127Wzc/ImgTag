import json

import httpx
import pytest

from imgtag.core.exception_translate import translate_exception
from imgtag.core.exceptions import EmbeddingAPIError
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


@pytest.mark.asyncio
async def test_structured_description_and_subject_tags_are_both_embedded(embedding_api):
    _, install_handler = embedding_api
    description = '主体：菲比，金发紫眼。\n动作：举起双臂。\n文字：拉电线哈哈。'
    def handler(request):
        payload = json.loads(request.content)
        assert payload['input'] == description + ' | 标签: 菲比, 举手, 表情包'
        assert 'subject_checks' not in payload['input']
        return httpx.Response(200, json={'data': [{'embedding': [0.1] * 1024}]})
    install_handler(handler)
    assert len(await EmbeddingService().get_embedding_combined(description, ['菲比', '举手', '表情包'])) == 1024


@pytest.mark.asyncio
@pytest.mark.parametrize('status, message', [
    (400, '模型和参数配置'), (401, '网页登录仍有效'), (403, '权限'),
    (404, 'API 地址和模型名称'), (429, '账户额度'), (503, '暂时不可用'),
])
async def test_upstream_errors_identify_vector_service_without_exposing_body(embedding_api, caplog, status, message):
    _, install_handler = embedding_api
    install_handler(lambda request: httpx.Response(status, json={'message': 'test-key provider-secret'}))
    with pytest.raises(EmbeddingAPIError) as raised:
        await EmbeddingService().get_embedding('图片描述')
    assert message in str(raised.value) and f'HTTP {status}' in str(raised.value)
    translated = translate_exception(raised.value).api_error
    assert translated.status_code == 502
    assert translated.to_dict()['error']['upstream_status'] == status
    assert translated.to_dict()['error']['service'] == 'embedding'
    assert 'test-key' not in str(raised.value) + caplog.text
    assert 'provider-secret' not in str(raised.value) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize('failure, expected_status, message', [
    (httpx.ReadTimeout('secret-request-info'), 504, '请求超时'),
    (httpx.ConnectError('secret-request-info'), 502, 'API 地址和网络'),
])
async def test_embedding_network_errors_are_actionable(embedding_api, caplog, failure, expected_status, message):
    _, install_handler = embedding_api
    def handler(request):
        raise failure
    install_handler(handler)
    with pytest.raises(EmbeddingAPIError, match=message) as raised:
        await EmbeddingService().get_embedding('图片描述')
    assert translate_exception(raised.value).api_error.status_code == expected_status
    assert 'secret-request-info' not in str(raised.value) + caplog.text


@pytest.mark.asyncio
async def test_embedding_missing_key_does_not_send_request(embedding_api):
    config, install_handler = embedding_api
    config['embedding_api_key'] = ''
    def handler(request):
        pytest.fail('未配置密钥时不应发出请求')
    install_handler(handler)
    with pytest.raises(EmbeddingAPIError, match='系统设置 → 向量嵌入') as raised:
        await EmbeddingService().get_embedding('图片描述')
    assert translate_exception(raised.value).api_error.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [b'not-json', b'{"data":[]}', b'{"data":[{}]}'])
async def test_embedding_malformed_response_has_clear_message(embedding_api, body):
    _, install_handler = embedding_api
    install_handler(lambda request: httpx.Response(200, content=body))
    with pytest.raises(EmbeddingAPIError, match='返回的数据格式不正确'):
        await EmbeddingService().get_embedding('图片描述')
