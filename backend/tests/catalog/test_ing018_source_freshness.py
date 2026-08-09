from __future__ import annotations

import hashlib

import httpx
import pytest


def _source_payload(url: str = "https://docs.example/refresh/manual") -> dict:
    return {
        "source_type": "internal",
        "source_kind": "internal",
        "canonical_url": url,
        "name": "ING-018 freshness fixture",
        "trust_level": "reviewed",
        "metadata": {"owner": "network-team"},
    }


def _public(*_args):
    return ["93.184.216.34"]


def _transport(handler):
    return httpx.MockTransport(handler)


def test_ing018_safe_fetch_sends_only_server_owned_conditional_validators():
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update({key.lower(): value for key, value in request.headers.items()})
        return httpx.Response(304, headers={"etag": '"v2"', "last-modified": "Tue, 11 Aug 2026 06:00:00 GMT"}, request=request)

    result = safe_fetch(
        {
            "id": "source-ing018",
            "tenant_id": "tenant-default",
            "status": "active",
            "validation_status": "valid",
            "fetch_enabled": True,
            "canonical_url": "https://docs.example/refresh/manual",
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
                "retry_policy": {"max_attempts": 1, "retry_5xx": True},
            },
        },
        transport=_transport(handler),
        resolver=_public,
        conditional_headers={"if-none-match": '"v1"', "if-modified-since": "Mon, 10 Aug 2026 06:00:00 GMT"},
    )
    assert result.not_modified is True
    assert result.status_code == 304
    assert result.content == b""
    assert seen["if-none-match"] == '"v1"'
    assert seen["if-modified-since"] == "Mon, 10 Aug 2026 06:00:00 GMT"

    with pytest.raises(OutboundCollectionError) as forbidden:
        safe_fetch(
            {
                "id": "source-ing018",
                "tenant_id": "tenant-default",
                "status": "active",
                "validation_status": "valid",
                "fetch_enabled": True,
                "canonical_url": "https://docs.example/refresh/manual",
                "allowed_host": "docs.example",
                "host_match_mode": "exact",
                "collection_policy": {"http_methods": ["GET"], "timeout_seconds": 5, "max_bytes": 1024, "redirect_limit": 2, "rate_limit_per_minute": 30, "content_types": ["text/plain"], "retry_policy": {"max_attempts": 1}},
            },
            transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x", request=request)),
            resolver=_public,
            conditional_headers={"authorization": "Bearer forbidden"},
        )
    assert forbidden.value.code == "OUTBOUND_CONDITIONAL_HEADER_FORBIDDEN"


def test_ing018_collects_304_without_creating_duplicate_version(isolated_db, make_user):
    from services.source_registry_service import (
        collect_source,
        create_source,
        enable_source,
        list_source_refresh_observations,
        list_source_versions,
    )

    operator = make_user("ing018-304", role="Operator")
    source = create_source(_source_payload(), operator)
    enable_source(source["id"], operator)
    body = b"stable source body"
    first = collect_source(
        source["id"],
        {"method": "GET"},
        operator,
        transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain", "etag": '"v1"', "last-modified": "Mon, 10 Aug 2026 06:00:00 GMT"}, content=body, request=request)),
        resolver=_public,
    )
    assert first["version"]["content_hash"] == hashlib.sha256(body).hexdigest()
    seen = {}

    def not_modified(request: httpx.Request) -> httpx.Response:
        seen.update({key.lower(): value for key, value in request.headers.items()})
        return httpx.Response(304, headers={"etag": '"v1"', "last-modified": "Mon, 10 Aug 2026 06:00:00 GMT"}, request=request)

    second = collect_source(source["id"], {"method": "GET"}, operator, transport=_transport(not_modified), resolver=_public)
    assert second["version"] is None
    assert second["refresh"]["outcome"] == "not_modified"
    assert seen["if-none-match"] == '"v1"'
    assert seen["if-modified-since"] == "Mon, 10 Aug 2026 06:00:00 GMT"
    assert len(list_source_versions(source["id"], operator)) == 1
    observations = list_source_refresh_observations(source["id"], operator)
    assert observations[0]["outcome"] == "not_modified"
    assert observations[0]["content_hash"] == hashlib.sha256(body).hexdigest()
    assert "content" not in observations[0]


def test_ing018_same_hash_refreshes_validators_and_changed_hash_appends_version(isolated_db, make_user):
    from services.source_registry_service import collect_source, create_source, enable_source, list_source_refresh_observations, list_source_versions

    operator = make_user("ing018-hash", role="Operator")
    source = create_source(_source_payload("https://docs.example/refresh/hash"), operator)
    enable_source(source["id"], operator)
    body = b"same content"
    collect_source(source["id"], {"method": "GET"}, operator, transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain", "etag": '"v1"'}, content=body, request=request)), resolver=_public)
    same = collect_source(source["id"], {"method": "GET"}, operator, transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain", "etag": '"v2"', "last-modified": "Tue, 11 Aug 2026 06:00:00 GMT"}, content=body, request=request)), resolver=_public)
    assert same["version"]["deduplicated"] is True
    assert len(list_source_versions(source["id"], operator)) == 1
    changed_body = b"changed content"
    changed = collect_source(source["id"], {"method": "GET"}, operator, transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain", "etag": '"v3"'}, content=changed_body, request=request)), resolver=_public)
    assert changed["version"]["content_hash"] == hashlib.sha256(changed_body).hexdigest()
    assert len(list_source_versions(source["id"], operator)) == 2
    assert [row["outcome"] for row in list_source_refresh_observations(source["id"], operator)][:3] == ["changed", "unchanged", "changed"]


def test_ing018_refresh_batch_is_bounded_tenant_scoped_and_redacts_failure(isolated_db, make_user):
    from services.source_freshness_service import refresh_sources
    from services.source_registry_service import create_source, enable_source, list_source_refresh_observations

    operator = make_user("ing018-batch", role="Operator")
    source = create_source(_source_payload("https://docs.example/refresh/fail"), operator)
    enable_source(source["id"], operator)
    other = make_user("ing018-other", role="Operator")
    other["tenant_id"] = "tenant-other"
    other_source = create_source(_source_payload("https://docs.example/refresh/other"), other)
    enable_source(other_source["id"], other)
    result = refresh_sources(
        tenant_id="tenant-default",
        limit=1,
        user=operator,
        transport=_transport(lambda request: httpx.Response(503, headers={"content-type": "text/plain"}, content=b"provider secret should not escape", request=request)),
        resolver=_public,
    )
    assert result["selected"] == 1
    assert result["checked"] == 1
    assert result["failed"] == 1
    assert result["results"][0]["source_id"] == source["id"]
    assert "provider secret" not in str(result)
    observation = list_source_refresh_observations(source["id"], operator)[0]
    assert observation["outcome"] == "failed"
    assert observation["error"] == {"code": "OUTBOUND_HTTP_5XX"}


def test_ing018_api_and_scheduler_contracts(monkeypatch):
    from api.knowledge_sources import router
    from services import source_freshness_service

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/{source_id}/refresh-observations") and "GET" in methods for path, methods in paths)
    assert source_freshness_service.REFRESH_INTERVAL_MINUTES == 30
    monkeypatch.setattr(source_freshness_service, "_freshness_schema_ready", lambda: False)
    blocked = source_freshness_service.run_scheduled_source_freshness_refresh()
    assert blocked["status"] == "blocked_schema"
    assert blocked["error_code"] == "SOURCE_FRESHNESS_SCHEMA_UNAVAILABLE"
