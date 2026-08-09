from __future__ import annotations

import socket

import httpx
import pytest


def _source(**overrides):
    source = {
        "id": "source-ing003",
        "tenant_id": "tenant-default",
        "status": "active",
        "validation_status": "valid",
        "fetch_enabled": True,
        "canonical_url": "https://docs.example/vendor/manual",
        "allowed_host": "docs.example",
        "host_match_mode": "exact",
        "collection_policy": {
            "http_methods": ["GET", "HEAD"],
            "user_agent": "NexoraKnowledgeEngine/2.0",
            "timeout_seconds": 5,
            "max_bytes": 1024,
            "redirect_limit": 2,
            "rate_limit_per_minute": 30,
            "content_types": ["text/plain"],
            "retry_policy": {"max_attempts": 2, "retry_4xx": False, "retry_5xx": True},
        },
    }
    source.update(overrides)
    return source


def _public(*_args):
    return ["93.184.216.34"]


def test_ing003_returns_redacted_canonical_security_decision():
    from services.safe_outbound_http import validate_url_security

    decision = validate_url_security(
        "https://docs.example/vendor/manual",
        source=_source(),
        resolver=_public,
        resolve_dns=True,
    )
    assert decision.canonical_url == "https://docs.example/vendor/manual"
    assert decision.host == "docs.example"
    assert decision.port == 443
    assert decision.path == "/vendor/manual"
    assert decision.resolved_addresses == ("93.184.216.34",)
    assert set(decision.as_dict()) == {"canonical_url", "host", "port", "path", "resolved_addresses"}


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example/vendor/manual",
        "https://docs.example:8443/vendor/manual",
        "https://docs.example/vendor/manual?download=1",
        "https://docs.example/vendor/manual#section",
        "https://user:password@docs.example/vendor/manual",
        "https://docs.example/vendor/manual/%2fsecret",
        "https://docs.example/vendor/manual\\secret",
    ],
)
def test_ing003_rejects_unsafe_url_syntax_before_dns(url):
    from services.safe_outbound_http import OutboundCollectionError, validate_url_security

    with pytest.raises(OutboundCollectionError) as exc:
        validate_url_security(url, resolver=lambda *_: pytest.fail("DNS must not run for invalid URL"), resolve_dns=True)
    assert exc.value.code == "OUTBOUND_URL_FORBIDDEN"
    assert "password" not in str(exc.value).lower()
    assert "download=1" not in str(exc.value)


def test_ing003_rejects_ip_literals_and_non_public_dns_answers():
    from services.safe_outbound_http import OutboundCollectionError, validate_url_security

    with pytest.raises(OutboundCollectionError) as literal:
        validate_url_security("https://10.0.0.8/vendor/manual", resolve_dns=True)
    assert literal.value.code == "OUTBOUND_IP_LITERAL_FORBIDDEN"

    for answer in ("127.0.0.1", "169.254.169.254", "10.0.0.8", "::1"):
        with pytest.raises(OutboundCollectionError) as blocked:
            validate_url_security("https://docs.example/vendor/manual", resolver=lambda *_: [answer], resolve_dns=True)
        assert blocked.value.code == "OUTBOUND_DNS_BLOCKED"


def test_ing003_dns_empty_and_resolution_errors_fail_closed():
    from services.safe_outbound_http import OutboundCollectionError, validate_url_security

    with pytest.raises(OutboundCollectionError) as empty:
        validate_url_security("https://docs.example/vendor/manual", resolver=lambda *_: [], resolve_dns=True)
    assert empty.value.code == "OUTBOUND_DNS_EMPTY"

    def broken(*_args):
        raise socket.gaierror("secret resolver detail")

    with pytest.raises(OutboundCollectionError) as failed:
        validate_url_security("https://docs.example/vendor/manual", resolver=broken, resolve_dns=True)
    assert failed.value.code == "OUTBOUND_DNS_RESOLUTION_FAILED"
    assert "secret resolver detail" not in str(failed.value)


@pytest.mark.parametrize(
    ("target", "code"),
    [
        ("https://evil.example/vendor/manual", "OUTBOUND_REDIRECT_HOST_FORBIDDEN"),
        ("http://docs.example/vendor/manual", "OUTBOUND_REDIRECT_TARGET_FORBIDDEN"),
        ("https://docs.example/other", "OUTBOUND_REDIRECT_PATH_FORBIDDEN"),
    ],
)
def test_ing003_redirect_target_is_revalidated_against_registered_source(target, code):
    from services.safe_outbound_http import OutboundCollectionError, validate_url_security

    with pytest.raises(OutboundCollectionError) as exc:
        validate_url_security(target, source=_source(), current_url=_source()["canonical_url"])
    assert exc.value.code == code


def test_ing003_resolves_before_each_retry_and_redirect(monkeypatch):
    from services.safe_outbound_http import safe_fetch

    resolver_calls = []

    def resolver(host, port):
        resolver_calls.append((host, port))
        return _public()

    attempts = {"count": 0}

    def retry_handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(503, headers={"content-type": "text/plain"}, content=b"retry", request=request)

    with pytest.raises(Exception) as retry_error:
        safe_fetch(_source(), transport=httpx.MockTransport(retry_handler), resolver=resolver)
    assert retry_error.value.code == "OUTBOUND_HTTP_5XX"
    assert attempts["count"] == 2
    assert len(resolver_calls) == 2

    resolver_calls.clear()
    hops = {"count": 0}

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        hops["count"] += 1
        if hops["count"] == 1:
            return httpx.Response(302, headers={"location": "/vendor/manual/v2"}, request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok", request=request)

    result = safe_fetch(_source(), transport=httpx.MockTransport(redirect_handler), resolver=resolver)
    assert result.final_url.endswith("/vendor/manual/v2")
    assert len(resolver_calls) == 2


def test_ing003_enforces_stream_size_and_negative_content_length():
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    def too_large(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 1025, request=request)

    with pytest.raises(OutboundCollectionError) as large:
        safe_fetch(_source(), transport=httpx.MockTransport(too_large), resolver=_public)
    assert large.value.code == "OUTBOUND_RESPONSE_TOO_LARGE"

    def invalid_length(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain", "content-length": "-1"}, content=b"x", request=request)

    with pytest.raises(OutboundCollectionError) as invalid:
        safe_fetch(_source(), transport=httpx.MockTransport(invalid_length), resolver=_public)
    assert invalid.value.code == "OUTBOUND_CONTENT_LENGTH_INVALID"


def test_ing003_enforces_wall_clock_deadline_during_stream(monkeypatch):
    import services.safe_outbound_http as outbound

    ticks = iter((0.0, 0.0, 6.0))
    monkeypatch.setattr(outbound.time, "monotonic", lambda: next(ticks))

    def body(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok", request=request)

    with pytest.raises(outbound.OutboundCollectionError) as exc:
        outbound.safe_fetch(_source(), transport=httpx.MockTransport(body), resolver=_public)
    assert exc.value.code == "OUTBOUND_TIMEOUT"

