from __future__ import annotations

import hashlib

import httpx
import pytest


def _source(url: str = "https://docs.example/vendor/manual") -> dict:
    return {
        "id": "source-cat004",
        "tenant_id": "tenant-default",
        "status": "active",
        "validation_status": "valid",
        "fetch_enabled": True,
        "canonical_url": url,
        "allowed_host": "docs.example",
        "host_match_mode": "exact",
        "policy_version": 1,
        "collection_policy": {
            "http_methods": ["GET", "HEAD"],
            "user_agent": "NexoraKnowledgeEngine/2.0",
            "timeout_seconds": 5,
            "max_bytes": 1024,
            "redirect_limit": 2,
            "rate_limit_per_minute": 30,
            "content_types": ["text/plain", "text/html"],
            "parser_name": "plain-text",
            "parser_version": "1.0.0",
            "retry_policy": {"max_attempts": 2, "retry_4xx": False, "retry_5xx": True},
        },
    }


def _public(*_args):
    return ["93.184.216.34"]


def _transport(handler):
    return httpx.MockTransport(handler)


def test_cat004_fetches_allowlisted_content_without_proxy_environment():
    from services.safe_outbound_http import safe_fetch

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain; charset=utf-8", "etag": '"v1"'}, content=b"hello", request=request)

    def client_factory(**kwargs):
        captured.update(kwargs)
        return httpx.Client(**kwargs)

    result = safe_fetch(_source(), transport=_transport(handler), resolver=_public, client_factory=client_factory)
    assert result.content == b"hello"
    assert result.final_url == "https://docs.example/vendor/manual"
    assert result.content_type == "text/plain"
    assert result.source_etag == '"v1"'
    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False


@pytest.mark.parametrize(
    ("location", "code"),
    [
        ("https://evil.example/vendor/manual", "OUTBOUND_REDIRECT_HOST_FORBIDDEN"),
        ("http://docs.example/vendor/manual", "OUTBOUND_REDIRECT_TARGET_FORBIDDEN"),
        ("https://docs.example/vendor/other?token=1", "OUTBOUND_REDIRECT_TARGET_FORBIDDEN"),
        ("https://docs.example/vendor/manual/%2e%2e/secret", "OUTBOUND_REDIRECT_TARGET_FORBIDDEN"),
        ("https://docs.example/vendorsibling/manual", "OUTBOUND_REDIRECT_PATH_FORBIDDEN"),
    ],
)
def test_cat004_revalidates_every_redirect_target(location, code):
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location}, request=request)

    with pytest.raises(OutboundCollectionError) as exc:
        safe_fetch(_source(), transport=_transport(handler), resolver=_public)
    assert exc.value.code == code


def test_cat004_accepts_same_host_descendant_redirect_and_enforces_hop_limit():
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/vendor/manual":
            return httpx.Response(302, headers={"location": "manual/v2"}, request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"v2", request=request)

    result = safe_fetch(_source(), transport=_transport(handler), resolver=_public)
    assert result.final_url == "https://docs.example/vendor/manual/v2"
    assert result.redirect_chain == ("https://docs.example/vendor/manual", "https://docs.example/vendor/manual/v2")
    assert calls == ["https://docs.example/vendor/manual", "https://docs.example/vendor/manual/v2"]

    def infinite(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://docs.example/vendor/manual/again"}, request=request)

    with pytest.raises(OutboundCollectionError) as exc:
        safe_fetch(_source(), transport=_transport(infinite), resolver=_public)
    assert exc.value.code == "OUTBOUND_REDIRECT_LIMIT"


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "10.0.0.8"])
def test_cat004_rejects_ip_literal_and_private_dns_answers(host):
    from services.safe_outbound_http import OutboundCollectionError, resolve_public_addresses, safe_fetch

    with pytest.raises(OutboundCollectionError) as exc:
        resolve_public_addresses(host, 443, resolver=lambda *_: [host])
    assert exc.value.code == "OUTBOUND_IP_LITERAL_FORBIDDEN" if host in {"127.0.0.1", "169.254.169.254", "10.0.0.8"} else exc.value.code == "OUTBOUND_DNS_BLOCKED"

    source = _source()
    with pytest.raises(OutboundCollectionError) as dns_exc:
        safe_fetch(source, transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x", request=request)), resolver=lambda *_: ["10.0.0.8"])
    assert dns_exc.value.code == "OUTBOUND_DNS_BLOCKED"


def test_cat004_rejects_content_type_and_declared_or_streamed_size():
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    def bad_type(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"x", request=request)

    with pytest.raises(OutboundCollectionError) as type_exc:
        safe_fetch(_source(), transport=_transport(bad_type), resolver=_public)
    assert type_exc.value.code == "OUTBOUND_CONTENT_TYPE_FORBIDDEN"

    def declared_large(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain", "content-length": "2048"}, content=b"x", request=request)

    with pytest.raises(OutboundCollectionError) as declared_exc:
        safe_fetch(_source(), transport=_transport(declared_large), resolver=_public)
    assert declared_exc.value.code == "OUTBOUND_RESPONSE_TOO_LARGE"

    def streamed_large(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 2048, request=request)

    with pytest.raises(OutboundCollectionError) as streamed_exc:
        safe_fetch(_source(), transport=_transport(streamed_large), resolver=_public)
    assert streamed_exc.value.code == "OUTBOUND_RESPONSE_TOO_LARGE"


def test_cat004_does_not_retry_4xx_and_bounds_5xx_retries():
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    calls = {"four": 0, "five": 0}

    def four(request: httpx.Request) -> httpx.Response:
        calls["four"] += 1
        return httpx.Response(404, headers={"content-type": "text/plain"}, content=b"not found", request=request)

    with pytest.raises(OutboundCollectionError) as four_exc:
        safe_fetch(_source(), transport=_transport(four), resolver=_public)
    # ING-019 refines only 404/410 into a safe source-absence signal.  It is
    # still a single non-retried 4xx request and contains no provider payload.
    assert four_exc.value.code == "OUTBOUND_HTTP_SOURCE_NOT_FOUND"
    assert four_exc.value.details == {"http_status": 404}
    assert calls["four"] == 1

    def five(request: httpx.Request) -> httpx.Response:
        calls["five"] += 1
        return httpx.Response(503, headers={"content-type": "text/plain"}, content=b"retry", request=request)

    with pytest.raises(OutboundCollectionError) as five_exc:
        safe_fetch(_source(), transport=_transport(five), resolver=_public)
    assert five_exc.value.code == "OUTBOUND_HTTP_5XX"
    assert calls["five"] == 2


def test_cat004_gates_inactive_and_unvalidated_sources():
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    for changes, code in (({"status": "disabled"}, "OUTBOUND_SOURCE_NOT_ACTIVE"), ({"validation_status": "unvalidated"}, "OUTBOUND_SOURCE_NOT_VALIDATED")):
        source = _source()
        source.update(changes)
        with pytest.raises(OutboundCollectionError) as exc:
            safe_fetch(source, transport=_transport(lambda request: httpx.Response(200, request=request)), resolver=_public)
        assert exc.value.code == code


def test_cat004_collects_hash_only_version_and_redacted_audit(isolated_db, make_user):
    from database import get_db_connection
    from services.source_registry_service import collect_source, create_source, enable_source

    operator = make_user("cat004-collector", role="Administrator", tenant_id="tenant-default")
    source = create_source(
        {
            "source_type": "internal",
            "source_kind": "internal",
            "canonical_url": "https://docs.example/vendor/integration",
            "name": "CAT-004 fixture",
            "metadata": {"owner": "network-team"},
        },
        operator,
    )
    enable_source(source["id"], operator)
    body = b"collected document"

    result = collect_source(
        source["id"],
        {"method": "GET"},
        operator,
        transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain", "etag": "fixture"}, content=body, request=request)),
        resolver=_public,
    )
    assert result["fetch"]["bytes_read"] == len(body)
    assert "content" not in result["fetch"]
    assert result["version"]["content_hash"] == hashlib.sha256(body).hexdigest()
    assert result["version"]["raw_content_storage"] == "hash_only_memory_boundary"
    assert result["version"]["metadata"]["redirect_chain"] == ["https://docs.example/vendor/integration"]

    conn = get_db_connection()
    try:
        events = conn.execute("SELECT event_type, details_json FROM audit_events WHERE target_id = ? ORDER BY created_at", (source["id"],)).fetchall()
        event_types = [row["event_type"] for row in events]
    finally:
        conn.close()
    assert "fetch_started" in event_types
    assert "fetch_completed" in event_types


def test_cat004_api_contract_exposes_fetch_route():
    from api.knowledge_sources import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/{source_id}/fetch") and "POST" in methods for path, methods in paths)
