"""chat() and chat_stream() share one preparation stage (review item L4).

For the same input both entry points must pick the same model, reject with
the same error code and write the same audit fields.  The stream path must
also record the prompt version (M6) and re-check a fallback against the
effective data classification.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ai.gateway import llm_gateway as gateway_module
from ai.gateway.exceptions import AIModelNotFoundException, AINetworkException, AISecurityBlockedException
from ai.gateway.limits import AILimitManager
from ai.gateway.llm_gateway import LLMGateway
from ai.security.gateway import AISecurityGateway, SecurityPolicy


MSG = [{"role": "user", "content": "Reply with ok"}]
ROUTE_KEYS = ("requested_model_id", "model_id", "provider_id", "route_reason", "fallback_used", "status")


def _model(model_id: str, provider_id: str, classification: str = "INTERNAL") -> dict:
    return {
        "id": model_id,
        "model_code": model_id,
        "provider_id": provider_id,
        "provider_type": "openai",
        "allowed_data_classification": classification,
        "data_region": "unknown",
        "model_type": "chat",
        "enabled": True,
        "tool_call_supported": False,
        "json_supported": True,
        "thinking_supported": False,
        "stream_supported": True,
        "default_temperature": 0.0,
        "default_max_tokens": 128,
    }


def _provider(*, fail: bool = False, text: str = "ok") -> SimpleNamespace:
    async def chat_stream(*_args, **_kwargs):
        provider.stream_calls += 1
        if fail:
            raise AINetworkException()
        yield text

    provider = SimpleNamespace(
        max_retries=0,
        stream_calls=0,
        chat=AsyncMock(side_effect=AINetworkException()) if fail else AsyncMock(return_value={"content": text, "input_tokens": 3, "output_tokens": 1}),
        chat_stream=chat_stream,
    )
    return provider


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []


def _gateway(monkeypatch: pytest.MonkeyPatch, models: dict[str, dict], providers: dict[str, Any], *, denied: set[str] | None = None) -> tuple[LLMGateway, _Recorder]:
    limits = AILimitManager()
    limits.failure_threshold = 10
    monkeypatch.setattr(gateway_module, "ai_limits", limits)
    gateway = LLMGateway(security_gateway=AISecurityGateway(policy=SecurityPolicy(external_ai_enabled=True)))
    rec = _Recorder()

    def details(model_id):
        if str(model_id) not in models:
            raise AIModelNotFoundException("Requested AI model is not available")
        return models[str(model_id)]

    def authorize(model_info, **_kwargs):
        if model_info["id"] in (denied or set()):
            raise AIModelNotFoundException("Requested AI model is not available for this user")

    monkeypatch.setattr(gateway, "_get_model_details", details)
    monkeypatch.setattr(gateway, "_authorize_model", authorize)
    monkeypatch.setattr(gateway, "_get_provider_instance", lambda provider_id: providers[str(provider_id)])
    monkeypatch.setattr(gateway, "_budget_exceeded", lambda **_kwargs: False)
    monkeypatch.setattr(gateway, "_log_request", lambda **kwargs: rec.requests.append(kwargs))
    monkeypatch.setattr(gateway, "_log_security_audit", lambda **kwargs: rec.audits.append(kwargs))
    return gateway, rec


async def _run_chat(gateway: LLMGateway, **kwargs) -> tuple[Any, dict]:
    meta: dict = {}
    try:
        result = await gateway.chat(scene="t6", messages=list(MSG), route_meta=meta, user_id="alice", tenant_id="tenant-default", **kwargs)
    except Exception as exc:  # the exception is the outcome under test
        return exc, meta
    return result, meta


async def _run_stream(gateway: LLMGateway, **kwargs) -> tuple[Any, dict]:
    meta: dict = {}
    chunks: list[str] = []
    try:
        async for chunk in gateway.chat_stream(scene="t6", messages=list(MSG), route_meta=meta, user_id="alice", tenant_id="tenant-default", **kwargs):
            chunks.append(chunk)
    except Exception as exc:
        return exc, meta
    return "".join(chunks), meta


def _route(meta: dict) -> dict:
    return {key: meta.get(key) for key in ROUTE_KEYS}


def _audit_shape(audits: list[dict]) -> list[tuple]:
    return [(a.get("decision"), a.get("status"), a.get("error_code"), a.get("model_code"), a.get("provider_type"), a.get("max_data_level")) for a in audits]


def _request_shape(requests: list[dict]) -> list[tuple]:
    return [(r.get("status"), r.get("provider_id"), r.get("model_id"), r.get("prompt_id"), r.get("prompt_version"), r.get("error_message")) for r in requests]


def _scene_route(monkeypatch, primary: str, fallback: str | None) -> None:
    monkeypatch.setattr(gateway_module.model_router, "resolve_route_policy", lambda _scene: (primary, fallback, "scene_route", None))


@pytest.mark.anyio
async def test_both_entry_points_use_the_shared_preparation(monkeypatch):
    gateway, _rec = _gateway(monkeypatch, {"m": _model("m", "p")}, {"p": _provider()})
    calls: list[str] = []
    original = gateway._prepare_request

    async def spy(**kwargs):
        calls.append(kwargs["scene"])
        return await original(**kwargs)

    monkeypatch.setattr(gateway, "_prepare_request", spy)
    await _run_chat(gateway, model_id="m", data_classification="PUBLIC")
    await _run_stream(gateway, model_id="m", data_classification="PUBLIC")
    assert calls == ["t6", "t6"]


@pytest.mark.anyio
async def test_normal_request_same_route_and_audit_and_stream_keeps_prompt_version(monkeypatch):
    models = {"m": _model("m", "p")}
    chat_gw, chat_rec = _gateway(monkeypatch, models, {"p": _provider()})
    chat_result, chat_meta = await _run_chat(chat_gw, model_id="m", data_classification="PUBLIC", prompt_id="prompt-1", prompt_version=3)
    stream_gw, stream_rec = _gateway(monkeypatch, models, {"p": _provider()})
    stream_text, stream_meta = await _run_stream(stream_gw, model_id="m", data_classification="PUBLIC", prompt_id="prompt-1", prompt_version=3)

    assert chat_result["content"] == "ok" and stream_text == "ok"
    assert _route(chat_meta) == _route(stream_meta)
    assert chat_meta["model_id"] == "m" and chat_meta["route_reason"] == "message_explicit_model"
    assert _audit_shape(chat_rec.audits) == _audit_shape(stream_rec.audits)
    assert [a["status"] for a in stream_rec.audits] == ["prepared"]
    assert _request_shape(chat_rec.requests) == _request_shape(stream_rec.requests)
    # M6: the stream request log carries the prompt id and version.
    assert stream_rec.requests[-1]["prompt_id"] == "prompt-1"
    assert stream_rec.requests[-1]["prompt_version"] == 3


@pytest.mark.anyio
async def test_missing_model_is_rejected_identically(monkeypatch):
    provider = _provider()
    gateway, rec = _gateway(monkeypatch, {"m": _model("m", "p")}, {"p": provider})
    chat_exc, _ = await _run_chat(gateway, model_id="missing", data_classification="PUBLIC")
    stream_exc, _ = await _run_stream(gateway, model_id="missing", data_classification="PUBLIC")

    assert isinstance(chat_exc, AIModelNotFoundException) and isinstance(stream_exc, AIModelNotFoundException)
    assert chat_exc.code == stream_exc.code
    assert provider.chat.await_count == 0 and provider.stream_calls == 0
    assert rec.audits == []  # nothing was prepared for egress


@pytest.mark.anyio
async def test_acl_denial_is_rejected_identically(monkeypatch):
    provider = _provider()
    gateway, rec = _gateway(monkeypatch, {"m": _model("m", "p")}, {"p": provider}, denied={"m"})
    chat_exc, _ = await _run_chat(gateway, model_id="m", data_classification="PUBLIC")
    stream_exc, _ = await _run_stream(gateway, model_id="m", data_classification="PUBLIC")

    assert type(chat_exc) is type(stream_exc) is AIModelNotFoundException
    assert chat_exc.code == stream_exc.code
    assert provider.chat.await_count == 0 and provider.stream_calls == 0
    assert rec.audits == [] and rec.requests == []


@pytest.mark.anyio
async def test_fallback_after_primary_failure_matches(monkeypatch):
    models = {"primary": _model("primary", "p1"), "fallback": _model("fallback", "p2")}
    _scene_route(monkeypatch, "primary", "fallback")

    chat_gw, chat_rec = _gateway(monkeypatch, models, {"p1": _provider(fail=True), "p2": _provider(text="fb")})
    chat_result, chat_meta = await _run_chat(chat_gw, data_classification="PUBLIC")
    stream_gw, stream_rec = _gateway(monkeypatch, models, {"p1": _provider(fail=True), "p2": _provider(text="fb")})
    stream_text, stream_meta = await _run_stream(stream_gw, data_classification="PUBLIC")

    assert chat_result["content"] == "fb" and stream_text == "fb"
    assert chat_result["fallback_used"] is True
    assert _route(chat_meta) == _route(stream_meta)
    assert stream_meta["model_id"] == "fallback" and stream_meta["route_reason"] == "scene_route_fallback"
    assert _audit_shape(chat_rec.audits) == _audit_shape(stream_rec.audits)
    assert chat_rec.requests[-1]["model_id"] == stream_rec.requests[-1]["model_id"] == "fallback"


@pytest.mark.anyio
async def test_fallback_that_would_downgrade_classification_is_dropped_in_both(monkeypatch):
    # Primary may carry INTERNAL data, the fallback only PUBLIC: the fallback
    # would lower the boundary, so neither path may use it.
    models = {"primary": _model("primary", "p1", "INTERNAL"), "fallback": _model("fallback", "p2", "PUBLIC")}
    _scene_route(monkeypatch, "primary", "fallback")

    chat_fallback = _provider(text="fb")
    chat_gw, chat_rec = _gateway(monkeypatch, models, {"p1": _provider(fail=True), "p2": chat_fallback})
    chat_exc, chat_meta = await _run_chat(chat_gw, data_classification="PUBLIC")
    stream_fallback = _provider(text="fb")
    stream_gw, stream_rec = _gateway(monkeypatch, models, {"p1": _provider(fail=True), "p2": stream_fallback})
    stream_exc, stream_meta = await _run_stream(stream_gw, data_classification="PUBLIC")

    assert type(chat_exc) is type(stream_exc) is AINetworkException
    assert chat_exc.code == stream_exc.code
    assert chat_fallback.chat.await_count == 0 and stream_fallback.stream_calls == 0
    assert chat_meta["fallback_used"] is False and stream_meta["fallback_used"] is False
    assert chat_meta["status"] == stream_meta["status"] == "error"
    assert [r["status"] for r in chat_rec.requests] == [r["status"] for r in stream_rec.requests] == ["error"]


@pytest.mark.anyio
async def test_kill_switch_block_is_audited_identically(monkeypatch):
    provider = _provider()
    gateway, rec = _gateway(monkeypatch, {"m": _model("m", "p")}, {"p": provider})
    monkeypatch.setattr(gateway, "_current_policy", lambda: SimpleNamespace(kill_switch=True, external_ai_enabled=True))

    chat_exc, chat_meta = await _run_chat(gateway, model_id="m", data_classification="PUBLIC", prompt_version=2)
    chat_audits, chat_requests = list(rec.audits), list(rec.requests)
    rec.audits.clear(); rec.requests.clear()
    stream_exc, stream_meta = await _run_stream(gateway, model_id="m", data_classification="PUBLIC", prompt_version=2)

    assert isinstance(chat_exc, AISecurityBlockedException) and isinstance(stream_exc, AISecurityBlockedException)
    assert chat_exc.code == stream_exc.code == "AI_SECURITY_BLOCKED"
    # The stream path used to skip the security audit and route_meta here.
    assert _audit_shape(chat_audits) == _audit_shape(rec.audits) == [("BLOCK", "blocked", "AI_SECURITY_BLOCKED", "m", None, None)]
    assert _request_shape(chat_requests) == _request_shape(rec.requests)
    assert rec.requests[0]["prompt_version"] == 2
    assert chat_meta["status"] == stream_meta["status"] == "blocked"
    assert provider.chat.await_count == 0 and provider.stream_calls == 0
