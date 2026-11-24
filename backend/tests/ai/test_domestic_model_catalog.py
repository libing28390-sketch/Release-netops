import pytest

from ai.services.domestic_model_catalog import get_domestic_catalog, parse_domestic_catalog_page


@pytest.mark.parametrize(
    ("base_url", "kind", "path"),
    [
        ("https://api.deepseek.com", "deepseek", "/models"),
        ("https://ark.cn-beijing.volces.com/api/v3", "ark", "/api/v3/models"),
        ("https://qianfan.baidubce.com/v2/chat/completions", "qianfan", "/v2/models"),
        ("https://api.moonshot.cn/v1", "kimi", "/v1/models"),
        ("https://api.siliconflow.cn/v1", "siliconflow", "/v1/models"),
        ("https://tokenhub.tencentcloudmaas.com/v1", "tokenhub", "/v1/models"),
        ("https://llm-workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1", "dashscope", "/api/v1/models"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", "dashscope", None),
        ("https://api.hunyuan.cloud.tencent.com/v1", "hunyuan", None),
        ("https://open.bigmodel.cn/api/paas/v4", "zhipu", None),
        ("https://api.minimax.cn/v1", "minimax", None),
    ],
)
def test_domestic_presets_route_to_documented_directory(base_url, kind, path):
    result = get_domestic_catalog(base_url)
    assert result is not None
    assert (result.kind, result.path) == (kind, path)
    assert bool(result.items) == (path is None)


def test_domestic_special_cases_require_the_expected_origin():
    assert get_domestic_catalog("https://api.deepseek.com.example.com/v1") is None
    assert get_domestic_catalog("https://api.deepseek.com@other.example/v1") is None
    assert get_domestic_catalog("https://api.deepseek.com:8443/v1") is None


def test_dashscope_uses_official_capability_codes():
    payload = {"success": True, "output": {"models": [
        {"model": "qwen-plus", "capabilities": ["TG"]},
        {"model": "text-embedding-v4", "capabilities": ["TR"]},
        {"model": "wan", "capabilities": ["VG"]},
    ]}}
    assert [(item["model_code"], item["model_type"]) for item in parse_domestic_catalog_page("dashscope", payload)] == [
        ("qwen-plus", "chat"), ("text-embedding-v4", "embedding"),
    ]


def test_tokenhub_excludes_offline_models_and_siliconflow_accepts_retrieval_subtypes():
    candidates = parse_domestic_catalog_page("tokenhub", {"data": [
        {"id": "online-text", "status": "online"},
        {"id": "offline-text", "status": "offline"},
    ]})
    assert [item["model_code"] for item in candidates] == ["online-text"]
    candidates = parse_domestic_catalog_page("siliconflow", {"data": [
        {"id": "BAAI/bge-m3", "type": "text", "sub_type": "embedding"},
        {"id": "BAAI/bge-reranker-v2-m3", "sub_type": "reranker"},
    ]})
    assert [item["model_type"] for item in candidates] == ["embedding", "rerank"]
