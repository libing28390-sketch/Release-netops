"""Semantic embedding sidecar: backend client and service (refactor phase 2).

No model is loaded: the client is tested against ``httpx.MockTransport`` and
the service against a fake encoder, so these run in CI without the 600 MB
ONNX file.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import httpx
import pytest

from ai.providers import embedding as embedding_module
from ai.providers.embedding import EmbeddingProviderError, SidecarEmbeddingProvider

ROOT = Path(__file__).resolve().parents[3]
DIMS = 4
INFO = {"model_id": "bge-m3", "dimensions": DIMS, "version": "bge-m3-int8-v1", "max_tokens": 512, "max_batch": 64}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _vector(seed: int) -> list[float]:
    raw = [float(seed + index + 1) for index in range(DIMS)]
    norm = math.sqrt(sum(value * value for value in raw))
    return [value / norm for value in raw]


def _transport(calls: list, *, info=INFO, vectors=None, status: int = 200, raise_exc: Exception | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if raise_exc is not None:
            raise raise_exc
        if request.url.path == "/v1/info":
            return httpx.Response(200, json=info)
        if status != 200:
            return httpx.Response(status, json={"detail": "x"})
        body = json.loads(request.content)
        data = vectors(body) if callable(vectors) else [_vector(index) for index, _ in enumerate(body["input"])]
        # Encode by hand: httpx's json= refuses NaN, but a misbehaving server
        # can still send the NaN token and json.loads accepts it.
        body = json.dumps({"model": "bge-m3", "dimensions": DIMS, "data": data}, allow_nan=True)
        return httpx.Response(200, content=body.encode("utf-8"), headers={"content-type": "application/json"})

    return httpx.MockTransport(handler)


def _provider(transport, clock=None, **kwargs) -> SidecarEmbeddingProvider:
    return SidecarEmbeddingProvider(
        "http://embedding-sidecar:8005",
        model_id="bge-m3",
        dimensions=DIMS,
        version="bge-m3-int8-v1",
        transport=transport,
        clock=clock or Clock(),
        cooldown_seconds=30,
        **kwargs,
    )


# ── client: endpoint safety ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.example.com/v1",          # not local
        "http://user:pw@embedding-sidecar:8005",  # credentials
        "http://embedding-sidecar:8005/?x=1",  # query string
        "ftp://embedding-sidecar",             # scheme
        "http://embedding-sidecar:99999",      # bad port
    ],
)
def test_endpoint_must_be_a_local_plain_url(endpoint):
    with pytest.raises(EmbeddingProviderError):
        SidecarEmbeddingProvider(endpoint, model_id="bge-m3", dimensions=DIMS, version="bge-m3-int8-v1")


def test_extra_hosts_can_be_allowed_explicitly(monkeypatch):
    monkeypatch.setenv("AI_EMBEDDING_ALLOWED_HOSTS", "gpu-box.internal")
    provider = SidecarEmbeddingProvider("http://gpu-box.internal:8005", model_id="bge-m3", dimensions=DIMS, version="v")
    assert provider.endpoint == "http://gpu-box.internal:8005"


# ── client: happy path ────────────────────────────────────────────────────


def test_documents_are_batched_and_contract_checked_once():
    calls: list = []
    provider = _provider(_transport(calls), batch_size=2)
    vectors = provider.embed_documents(["a", "b", "c", "d", "e"])
    assert len(vectors) == 5 and all(len(vector) == DIMS for vector in vectors)
    paths = [request.url.path for request in calls]
    assert paths.count("/v1/info") == 1
    assert paths.count("/v1/embeddings") == 3
    kinds = {json.loads(request.content)["kind"] for request in calls if request.url.path == "/v1/embeddings"}
    assert kinds == {"document"}


def test_query_embeddings_are_cached():
    calls: list = []
    provider = _provider(_transport(calls))
    first = provider.embed_query("display ospf peer")
    second = provider.embed_query("display ospf peer")
    assert first == second
    embed_calls = [request for request in calls if request.url.path == "/v1/embeddings"]
    assert len(embed_calls) == 1
    assert json.loads(embed_calls[0].content)["kind"] == "query"


def test_token_is_sent_as_bearer_and_proxy_env_is_ignored(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    calls: list = []
    provider = _provider(_transport(calls), token="s3cret")
    provider.embed_query("x")
    assert all(request.headers.get("authorization") == "Bearer s3cret" for request in calls)


# ── client: contract and output validation ────────────────────────────────


@pytest.mark.parametrize(
    "info",
    [
        {**INFO, "model_id": "bge-small-zh"},
        {**INFO, "dimensions": 512},
        {**INFO, "version": "bge-m3-fp32-v2"},
    ],
)
def test_a_different_model_behind_the_url_is_refused(info):
    provider = _provider(_transport([], info=info))
    with pytest.raises(EmbeddingProviderError, match="MISMATCH"):
        provider.embed_query("x")


@pytest.mark.parametrize(
    "vectors, code",
    [
        (lambda body: [_vector(0)[:2] for _ in body["input"]], "DIMENSION_MISMATCH"),
        (lambda body: [[float("nan")] * DIMS for _ in body["input"]], "NON_FINITE_VECTOR"),
        (lambda body: [], "BATCH_SIZE_MISMATCH"),
    ],
)
def test_invalid_output_is_rejected(vectors, code):
    provider = _provider(_transport([], vectors=vectors))
    with pytest.raises(EmbeddingProviderError, match=code):
        provider.embed_documents(["a", "b"])


# ── client: failure handling ──────────────────────────────────────────────


def test_failure_opens_a_cooldown_without_further_calls():
    calls: list = []
    clock = Clock()
    provider = _provider(_transport(calls, raise_exc=httpx.ConnectTimeout("slow")), clock=clock)
    with pytest.raises(EmbeddingProviderError, match="TIMEOUT"):
        provider.embed_query("x")
    attempts = len(calls)
    with pytest.raises(EmbeddingProviderError, match="cooling down"):
        provider.embed_query("y")
    assert len(calls) == attempts  # no network call during the cooldown
    assert provider.status()["status"] == "unavailable"

    clock.now += 31
    with pytest.raises(EmbeddingProviderError, match="TIMEOUT"):
        provider.embed_query("z")
    assert len(calls) > attempts


@pytest.mark.parametrize("status, code", [(503, "NOT_READY"), (401, "UNAUTHORIZED"), (500, "HTTP_500")])
def test_http_errors_map_to_stable_codes(status, code):
    provider = _provider(_transport([], status=status))
    with pytest.raises(EmbeddingProviderError, match=code):
        provider.embed_documents(["a"])


def test_embed_documents_batch_retries_then_raises(monkeypatch):
    provider = _provider(_transport([], status=500), clock=Clock())
    provider._cooldown = 0.0
    with pytest.raises(EmbeddingProviderError):
        embedding_module.embed_documents_batch(["a"], provider=provider, sleep_fn=lambda _s: None, cache={})


# ── factory ───────────────────────────────────────────────────────────────


def test_semantic_provider_is_off_by_default_and_separate_from_legacy(monkeypatch):
    monkeypatch.delenv("AI_SEMANTIC_EMBEDDING_PROVIDER", raising=False)
    assert embedding_module.semantic_embedding_provider() is None
    assert embedding_module.semantic_embedding_status() == {"provider": "none", "status": "disabled"}

    for name in ("AI_SEMANTIC_EMBEDDING_DIMENSIONS", "AI_SEMANTIC_EMBEDDING_MODEL", "AI_EMBEDDING_SIDECAR_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_SEMANTIC_EMBEDDING_PROVIDER", "sidecar")
    provider = embedding_module.semantic_embedding_provider()
    assert isinstance(provider, SidecarEmbeddingProvider)
    assert (provider.model_id, provider.dimensions) == ("bge-m3", 1024)
    assert embedding_module.semantic_embedding_provider() is provider  # reused
    # The legacy provider behind the vector(1536) column is untouched.
    assert embedding_module.embedding_provider is not provider

    monkeypatch.setenv("AI_SEMANTIC_EMBEDDING_PROVIDER", "openai")
    with pytest.raises(EmbeddingProviderError):
        embedding_module.semantic_embedding_provider()
    assert embedding_module.semantic_embedding_status()["status"] == "misconfigured"


# ── sidecar service ───────────────────────────────────────────────────────


@pytest.fixture
def sidecar(monkeypatch):
    monkeypatch.setenv("EMBEDDING_SKIP_LOAD", "1")
    monkeypatch.delenv("EMBEDDING_SIDECAR_TOKEN", raising=False)
    path = ROOT / "sidecars" / "embedding" / "app.py"
    spec = importlib.util.spec_from_file_location("nexora_embedding_sidecar_app", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


class FakeEncoder:
    model_id = "bge-m3"
    dimensions = DIMS
    version = "bge-m3-int8-v1"
    max_length = 512
    manifest_sha256 = "0" * 64

    def __init__(self, _model_dir=None) -> None:
        self.seen: list[list[str]] = []

    def encode(self, texts):
        self.seen.append(list(texts))
        return [_vector(index) for index, _ in enumerate(texts)]


def _client(module):
    from fastapi.testclient import TestClient

    return TestClient(module.app)


def test_sidecar_is_not_ready_until_the_model_loads(sidecar):
    client = _client(sidecar)
    assert client.get("/healthz").status_code == 503

    def broken(_dir):
        raise FileNotFoundError("model.onnx")

    sidecar.load_encoder(broken)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "FileNotFoundError"

    sidecar.load_encoder(FakeEncoder)
    assert client.get("/healthz").json() == {"status": "ok", "model": "bge-m3", "dimensions": DIMS}
    assert client.get("/v1/info").json()["version"] == "bge-m3-int8-v1"


def test_sidecar_embeds_and_validates_input(sidecar):
    sidecar.load_encoder(FakeEncoder)
    client = _client(sidecar)
    response = client.post("/v1/embeddings", json={"input": ["display ospf peer", "端口一直闪但不通"], "kind": "query"})
    assert response.status_code == 200
    body = response.json()
    assert body["dimensions"] == DIMS and len(body["data"]) == 2

    assert client.post("/v1/embeddings", json={"input": []}).status_code == 422
    assert client.post("/v1/embeddings", json={"input": ["  "]}).status_code == 422
    assert client.post("/v1/embeddings", json={"input": ["x"] * (sidecar.MAX_BATCH + 1)}).status_code == 422
    assert client.post("/v1/embeddings", json={"input": ["x"], "kind": "other"}).status_code == 422

    long_text = "a" * (sidecar.MAX_TEXT_CHARS + 100)
    client.post("/v1/embeddings", json={"input": [long_text]})
    assert len(sidecar.state.encoder.seen[-1][0]) == sidecar.MAX_TEXT_CHARS


def test_sidecar_token(sidecar, monkeypatch):
    sidecar.load_encoder(FakeEncoder)
    monkeypatch.setenv("EMBEDDING_SIDECAR_TOKEN", "s3cret")
    client = _client(sidecar)
    assert client.post("/v1/embeddings", json={"input": ["x"]}).status_code == 401
    assert client.post("/v1/embeddings", json={"input": ["x"]}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/v1/embeddings", json={"input": ["x"]}, headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/healthz").status_code == 200  # health stays open for the container probe


def test_sidecar_rejects_invalid_encoder_output(sidecar):
    class BadEncoder(FakeEncoder):
        def encode(self, texts):
            return [[float("inf")] * DIMS for _ in texts]

    sidecar.load_encoder(BadEncoder)
    assert _client(sidecar).post("/v1/embeddings", json={"input": ["x"]}).status_code == 500


def test_client_and_sidecar_agree_end_to_end(sidecar):
    """The real client against the real service app (fake model)."""
    from fastapi.testclient import TestClient

    sidecar.load_encoder(FakeEncoder)
    test_client = TestClient(sidecar.app)

    def handler(request: httpx.Request) -> httpx.Response:
        response = test_client.request(request.method, request.url.path, content=request.content, headers=dict(request.headers))
        return httpx.Response(response.status_code, content=response.content, headers={"content-type": "application/json"})

    provider = _provider(httpx.MockTransport(handler))
    vectors = provider.embed_documents(["vlan batch 10 20", "port link-type trunk", "OSPF 邻居 ExStart"])
    assert len(vectors) == 3 and all(len(vector) == DIMS for vector in vectors)
    assert provider.status()["status"] == "ready"
