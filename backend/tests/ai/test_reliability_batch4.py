"""Regression tests for the reliability batch (review items M3, M4, M6).

M3  Circuit breaker: one failed request counts once, half-open allows a
    single probe, Retry-After and jittered backoff.
M4  Provider HTTP clients are reused; streamed answers have a total deadline.
M6  Streams record prompt id/version, and client disconnects are accounted
    for without marking the provider unhealthy.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from ai.gateway import limits as limits_module
from ai.gateway import llm_gateway as gateway_module
from ai.gateway.exceptions import AICircuitOpenException, AINetworkException, AIProviderTimeoutException, AIRateLimitException
from ai.gateway.limits import AILimitManager
from ai.gateway.llm_gateway import LLMGateway, _estimate_tokens
from ai.providers import openai_compatible as provider_module
from ai.providers.openai_compatible import OpenAICompatibleProvider, _rate_limited, aclose_shared_clients
from ai.security.gateway import AISecurityGateway, SecurityPolicy
from core.config import settings


MSG = [{"role": "user", "content": "ok?"}]


def _model() -> dict:
    return {
        "id": "m", "model_code": "m", "provider_id": "p", "provider_type": "openai",
        "allowed_data_classification": "INTERNAL", "data_region": "unknown", "model_type": "chat",
        "enabled": True, "tool_call_supported": False, "json_supported": True, "thinking_supported": False,
        "stream_supported": True, "default_temperature": 0.0, "default_max_tokens": 128,
    }


def _gateway(monkeypatch, provider, *, limits: AILimitManager | None = None, log=None, patch_sleep: bool = True):
    limits = limits or AILimitManager()
    monkeypatch.setattr(gateway_module, "ai_limits", limits)
    gateway = LLMGateway(security_gateway=AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True)))
    monkeypatch.setattr(gateway, "_get_model_details", lambda *_a, **_k: _model())
    monkeypatch.setattr(gateway, "_authorize_model", lambda *_a, **_k: None)
    monkeypatch.setattr(gateway, "_get_provider_instance", lambda *_a, **_k: provider)
    monkeypatch.setattr(gateway, "_budget_exceeded", lambda **_k: False)
    monkeypatch.setattr(gateway, "_log_request", log or (lambda **_k: None))
    monkeypatch.setattr(gateway, "_log_security_audit", lambda **_k: None)
    if patch_sleep:
        monkeypatch.setattr(gateway_module.asyncio, "sleep", AsyncMock())
    return gateway, limits


def _chat(gateway: LLMGateway):
    return gateway.chat(scene="provider_test", model_id="m", messages=MSG, data_classification="PUBLIC")


async def _collect(agen) -> list[str]:
    return [chunk async for chunk in agen]


# ── M3: circuit breaker ───────────────────────────────────────────────────


def test_m3_one_failed_request_counts_one_failure(monkeypatch):
    limits = AILimitManager()
    limits.failure_threshold = 2
    provider = SimpleNamespace(max_retries=3, chat=AsyncMock(side_effect=AINetworkException()))
    gateway, _ = _gateway(monkeypatch, provider, limits=limits)

    with pytest.raises(AINetworkException):
        asyncio.run(_chat(gateway))

    assert provider.chat.await_count == 4  # 1 + 3 retries
    assert limits._circuits["p"].failures == 1
    assert limits._circuits["p"].opened_until == 0.0


def test_m3_circuit_opens_after_threshold_failed_requests(monkeypatch):
    limits = AILimitManager()
    limits.failure_threshold = 2
    provider = SimpleNamespace(max_retries=1, chat=AsyncMock(side_effect=AINetworkException()))
    gateway, _ = _gateway(monkeypatch, provider, limits=limits)

    for _ in range(2):
        with pytest.raises(AINetworkException):
            asyncio.run(_chat(gateway))
    calls = provider.chat.await_count

    with pytest.raises(AICircuitOpenException):
        asyncio.run(_chat(gateway))
    assert provider.chat.await_count == calls


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(limits_module, "time", SimpleNamespace(monotonic=lambda: now["t"]))
    return now


def _opened(threshold: int = 1, cooldown: float = 30.0) -> AILimitManager:
    limits = AILimitManager()
    limits.failure_threshold = threshold
    limits.cooldown_seconds = cooldown
    limits.probe_timeout_seconds = 120.0
    limits.record_failure("p")
    return limits


def test_m3_half_open_lets_exactly_one_probe_through(clock):
    limits = _opened()
    with pytest.raises(AICircuitOpenException):
        limits.acquire_circuit("p")
    clock["t"] += 31
    assert limits.acquire_circuit("p") is True
    with pytest.raises(AICircuitOpenException):
        limits.acquire_circuit("p")  # a second request while the probe is out
    limits.record_success("p")
    assert limits.acquire_circuit("p") is False


def test_m3_failed_probe_reopens_for_a_full_cooldown(clock):
    limits = _opened()
    clock["t"] += 31
    assert limits.acquire_circuit("p") is True
    limits.record_failure("p")
    clock["t"] += 29
    with pytest.raises(AICircuitOpenException):
        limits.acquire_circuit("p")
    clock["t"] += 2
    assert limits.acquire_circuit("p") is True


def test_m3_released_or_stale_probe_frees_the_half_open_slot(clock):
    limits = _opened()
    clock["t"] += 31
    assert limits.acquire_circuit("p") is True
    limits.release_probe("p")
    assert limits.acquire_circuit("p") is True  # next request may probe
    clock["t"] += 121
    assert limits.acquire_circuit("p") is True  # stale probe is abandoned


def test_m3_probe_request_can_use_its_own_retries(monkeypatch):
    limits = AILimitManager()
    limits._circuits["p"] = limits_module._Circuit(failures=3, opened_until=time.monotonic() - 1)
    provider = SimpleNamespace(
        max_retries=1,
        chat=AsyncMock(side_effect=[AINetworkException(), {"content": "ok", "input_tokens": 1, "output_tokens": 1}]),
    )
    gateway, _ = _gateway(monkeypatch, provider, limits=limits)

    result = asyncio.run(_chat(gateway))

    assert result["content"] == "ok"
    assert limits._circuits["p"].failures == 0
    assert limits._circuits["p"].opened_until == 0.0
    assert limits._circuits["p"].probe_in_flight is False


def test_m3_retry_delay_has_jitter_and_honours_retry_after(monkeypatch):
    monkeypatch.setattr(settings, "AI_RETRY_AFTER_MAX_SECONDS", 10.0)
    delays = {LLMGateway._retry_delay(0, 3, None) for _ in range(50)}
    assert all(0.25 <= value <= 0.75 for value in delays)
    assert len(delays) > 1
    assert LLMGateway._retry_delay(3, 3, None) is None

    short = AIRateLimitException()
    short.retry_after = 4.0
    assert LLMGateway._retry_delay(0, 3, short) >= 4.0

    long_wait = AIRateLimitException()
    long_wait.retry_after = 60.0
    assert LLMGateway._retry_delay(0, 3, long_wait) is None


def test_m3_retry_after_header_is_parsed():
    assert _rate_limited(SimpleNamespace(headers=httpx.Headers({"Retry-After": "5"}))).retry_after == 5.0
    assert _rate_limited(SimpleNamespace(headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})).retry_after is None
    assert _rate_limited(SimpleNamespace(headers={})).retry_after is None


# ── M4: shared clients and stream deadline ───────────────────────────────


def _provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        {"id": "p1", "name": "Example", "provider_type": "openai", "base_url": "https://api.example.com/v1", "timeout": 30},
        api_key="test-key",
    )


def _fake_client_class(created: list):
    class FakeResponse:
        status_code = 200
        headers: dict = {}

        def json(self):
            return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}}

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            created.append(self)

        async def post(self, url, *, headers, json):
            return FakeResponse()

        async def aclose(self):
            self.closed = True

    return FakeClient


def test_m4_client_is_reused_within_a_loop_and_closed_on_shutdown(monkeypatch):
    created: list = []
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", _fake_client_class(created))
    provider = _provider()

    async def run():
        await provider.chat(MSG, model="m")
        await provider.chat(MSG, model="m")
        await aclose_shared_clients()

    asyncio.run(run())

    assert len(created) == 1
    client = created[0]
    assert client.closed is True
    assert client.kwargs["follow_redirects"] is False
    timeout = client.kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 10.0 and timeout.read == 30.0


def test_m4_each_event_loop_gets_its_own_client(monkeypatch):
    created: list = []
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", _fake_client_class(created))
    provider = _provider()
    asyncio.run(provider.chat(MSG, model="m"))
    asyncio.run(provider.chat(MSG, model="m"))
    assert len(created) == 2


def test_m4_stream_stops_at_the_total_deadline(monkeypatch):
    class FakeResponse:
        status_code = 200

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"a"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"b"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"c"}}]}'

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            return False

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def stream(self, method, url, *, headers, json):
            return FakeStream()

    ticks = iter([0.0, 0.5, 5.0])
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(provider_module, "time", SimpleNamespace(monotonic=lambda: next(ticks, 99.0), perf_counter=time.perf_counter))
    monkeypatch.setattr(settings, "AI_STREAM_MAX_SECONDS", 1.0)
    chunks: list[str] = []

    async def run():
        async for chunk in _provider().chat_stream(MSG, model="m"):
            chunks.append(chunk)

    with pytest.raises(AIProviderTimeoutException):
        asyncio.run(run())
    assert chunks == ["a"]


# ── M6: prompt version and client aborts ──────────────────────────────────


def test_m6_stream_records_prompt_id_and_version(monkeypatch):
    logs: list[dict] = []

    async def stream(*_a, **_k):
        yield "o"
        yield "k"

    provider = SimpleNamespace(max_retries=0, chat_stream=stream)
    gateway, _ = _gateway(monkeypatch, provider, log=lambda **kwargs: logs.append(kwargs))

    asyncio.run(_collect(gateway.chat_stream(
        scene="chat", model_id="m", messages=MSG, data_classification="PUBLIC", prompt_id="prm_1", prompt_version=3,
    )))

    success = [item for item in logs if item["status"] == "success"]
    assert success and success[0]["prompt_id"] == "prm_1" and success[0]["prompt_version"] == 3


def _abort_logger():
    logs: list[dict] = []
    done = threading.Event()

    def log(**kwargs):
        logs.append(kwargs)
        if kwargs.get("status") == "client_aborted":
            done.set()

    return logs, done, log


def test_m6_closing_the_stream_records_a_client_abort(monkeypatch):
    logs, done, log = _abort_logger()

    async def stream(*_a, **_k):
        for _ in range(200):
            yield "接口状态正常。"

    provider = SimpleNamespace(max_retries=0, chat_stream=stream)
    gateway, _ = _gateway(monkeypatch, provider, log=log)

    async def run():
        agen = gateway.chat_stream(scene="chat", model_id="m", messages=MSG, data_classification="PUBLIC")
        await agen.__anext__()
        await agen.aclose()

    asyncio.run(run())

    assert done.wait(5)
    aborted = [item for item in logs if item["status"] == "client_aborted"][0]
    assert aborted["provider_id"] == "p"
    assert aborted["error_code"] == "AI_CLIENT_ABORTED"
    assert aborted["output_tokens"] >= 1
    assert not [item for item in logs if item["status"] == "success"]


def test_m6_cancelling_the_request_records_a_client_abort(monkeypatch):
    logs, done, log = _abort_logger()

    async def stream(*_a, **_k):
        yield "partial answer"
        await asyncio.Event().wait()  # provider stalls mid-answer

    provider = SimpleNamespace(max_retries=0, chat_stream=stream)
    gateway, limits = _gateway(monkeypatch, provider, log=log, patch_sleep=False)

    async def run():
        received: list[str] = []

        async def consume():
            async for chunk in gateway.chat_stream(scene="chat", model_id="m", messages=MSG, data_classification="PUBLIC"):
                received.append(chunk)

        task = asyncio.create_task(consume())
        for _ in range(100):
            if received:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert done.wait(5)
    aborted = [item for item in logs if item["status"] == "client_aborted"][0]
    assert aborted["provider_id"] == "p"
    assert aborted["input_tokens"] >= 1
    # A client disconnect is not a provider failure.
    assert limits._circuits.get("p") is None or limits._circuits["p"].failures == 0


def test_m6_client_abort_does_not_mark_the_provider_unhealthy(isolated_db):
    from database.core import get_db_connection

    provider_id = f"prov_{uuid.uuid4().hex[:10]}"
    model_id = f"model_{uuid.uuid4().hex[:10]}"
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO ai_provider (id, name, provider_type, base_url, enabled, health_status, created_at, updated_at) VALUES (?, ?, 'openai_compatible', 'https://example.invalid/v1', 1, 'healthy', ?, ?)",
            (provider_id, f"P-{provider_id}", now, now),
        )
        conn.execute(
            "INSERT INTO ai_model (id, provider_id, name, model_code, model_type, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, 'chat', 1, ?, ?)",
            (model_id, provider_id, f"M-{model_id}", f"code-{model_id}", now, now),
        )
        conn.commit()

    LLMGateway()._log_request(
        request_id="r1", user_id="u", scene="chat", provider_id=provider_id, model_id=model_id,
        prompt_id=None, prompt_version=None, input_tokens=10, output_tokens=5, latency_ms=100,
        status="client_aborted", error_code="AI_CLIENT_ABORTED", error_message="client_disconnected",
    )

    with get_db_connection() as conn:
        health = conn.execute("SELECT health_status FROM ai_provider WHERE id = ?", (provider_id,)).fetchone()
        usage = conn.execute(
            "SELECT requests, input_tokens, output_tokens, error_count FROM ai_usage_daily WHERE provider_id = ? AND model_id = ?",
            (provider_id, model_id),
        ).fetchone()
        logged = conn.execute("SELECT status FROM ai_request_log WHERE request_id = 'r1'").fetchone()
    assert health[0] == "healthy"
    assert tuple(usage) == (1, 10, 5, 0)
    assert logged[0] == "client_aborted"


def test_m6_token_estimate_weights_cjk_text():
    assert _estimate_tokens("") == 0
    assert _estimate_tokens("hello world") == 3
    assert _estimate_tokens("接口状态正常") == 4
