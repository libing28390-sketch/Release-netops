from __future__ import annotations

import threading
import time

import httpx

from services.official_seed_batch_service import collect_official_seed_batch, rate_limiter
from services.safe_outbound_http import check_robots_policy, safe_fetch


USER = {"id": "ing023", "username": "ing023", "tenant_id": "tenant-ing023", "role": "Administrator"}
URL_A = "https://www.cisco.com/c/en/us/products/switches/catalyst-9300-series-switches/index.html"
URL_B = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/system_management_commands.html"


def _item(url: str) -> dict:
    return {
        "url": url,
        "source_kind": "product_page" if "/products/switches/" in url else "command_reference",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "reviewer",
    }


def _source() -> dict:
    return {
        "id": "source-1",
        "status": "active",
        "fetch_enabled": True,
        "validation_status": "valid",
        "canonical_url": URL_A,
        "allowed_host": "www.cisco.com",
        "host_match_mode": "exact",
        "collection_policy": {
            "http_methods": ["GET", "HEAD"],
            "timeout_seconds": 10,
            "max_bytes": 20_000_000,
            "redirect_limit": 3,
            "rate_limit_per_minute": 30,
            "robots_policy": "respect",
            "user_agent": "NexoraKnowledgeEngine/2.0",
            "content_types": ["text/plain", "text/html"],
            "retry_policy": {"max_attempts": 3, "retry_5xx": True, "retry_4xx": False},
        },
    }


def _public(*_args):
    return ["72.163.4.161"]


def test_ing023_robots_respect_denies_disallowed_path_without_body_leak():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/robots.txt"
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"User-agent: *\nDisallow: /c/en/us/\n", request=request)

    decision = check_robots_policy(_source(), transport=httpx.MockTransport(handler), resolver=_public)
    assert decision["outcome"] == "disallowed"
    assert decision["allowed"] is False
    assert decision["error_code"] == "ROBOTS_DISALLOWED"
    assert "Disallow" not in str(decision)


def test_ing023_robots_404_is_bounded_allow_and_5xx_backoff_is_exponential():
    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, request=request)

    decision = check_robots_policy(_source(), transport=httpx.MockTransport(missing), resolver=_public)
    assert decision["outcome"] == "not_found_allow"
    assert decision["allowed"] is True

    attempts = 0
    delays: list[float] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok", request=request)

    result = safe_fetch(
        _source(),
        transport=httpx.MockTransport(flaky),
        resolver=_public,
        backoff_base_seconds=0.25,
        sleeper=delays.append,
    )
    assert result.status_code == 200
    assert attempts == 3
    assert delays == [0.25, 0.5]


def test_ing023_batch_bounds_concurrency_and_returns_site_alert_summary(monkeypatch):
    rate_limiter.reset_for_tests()
    lock = threading.Lock()
    active = 0
    max_active = 0

    def importer(_user, _payload, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"success": False, "error": {"code": "OUTBOUND_HTTP_5XX", "retryable": True}}

    recorded: list[dict] = []
    monkeypatch.setattr(
        "services.official_seed_batch_service._record_site_alerts",
        lambda _user, *, batch_id, alerts: recorded.extend(alerts),
    )
    result = collect_official_seed_batch(
        USER,
        [_item(URL_A), _item(URL_B)],
        rate_limit_per_minute=30,
        concurrency=2,
        backoff_base_seconds=0,
        importer=importer,
        sleeper=lambda _seconds: None,
    )
    assert result["failed_count"] == 2
    assert result["concurrency"] == 2
    assert max_active == 2
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["host"] == "www.cisco.com"
    assert result["alerts"][0]["alert_code"] == "OUTBOUND_HTTP_5XX"

    assert recorded == result["alerts"]


def test_ing023_site_alert_read_route_is_tenant_bounded(monkeypatch):
    from api.knowledge_ingestion import api_list_official_site_alerts, router

    paths = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert ("/knowledge/ingestion/official-site-alerts", ("GET",)) in paths
    monkeypatch.setattr(
        "api.knowledge_ingestion.list_site_anomaly_alerts",
        lambda user, **kwargs: [{"tenant_id": user["tenant_id"], "host": "www.cisco.com", "status": "open"}],
    )
    result = api_list_official_site_alerts(host="www.cisco.com", status="open", limit=10, user=USER)
    assert result["count"] == 1
    assert result["data"][0]["tenant_id"] == USER["tenant_id"]
