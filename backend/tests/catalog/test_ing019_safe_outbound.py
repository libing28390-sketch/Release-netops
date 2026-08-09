from __future__ import annotations

import httpx
import pytest


def _source() -> dict:
    return {
        "id": "source-ing019",
        "tenant_id": "tenant-default",
        "status": "active",
        "validation_status": "valid",
        "fetch_enabled": True,
        "canonical_url": "https://docs.example/vendor/manual",
        "allowed_host": "docs.example",
        "host_match_mode": "exact",
        "collection_policy": {
            "http_methods": ["GET", "HEAD"],
            "timeout_seconds": 5,
            "max_bytes": 1024,
            "redirect_limit": 2,
            "rate_limit_per_minute": 30,
            "content_types": ["text/plain"],
            "retry_policy": {"max_attempts": 2, "retry_5xx": True},
        },
    }


def _public(*_args):
    return ["93.184.216.34"]


@pytest.mark.parametrize("status", [404, 410])
def test_ing019_source_not_found_statuses_are_distinguishable_and_redacted(status: int):
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    secret = "Bearer provider-secret-should-not-escape"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"content-type": "text/plain", "x-provider-credential": secret},
            content=f"provider body {secret}".encode(),
            request=request,
        )

    with pytest.raises(OutboundCollectionError) as exc:
        safe_fetch(_source(), transport=httpx.MockTransport(handler), resolver=_public)

    assert exc.value.code == "OUTBOUND_HTTP_SOURCE_NOT_FOUND"
    assert exc.value.details == {"http_status": status}
    assert exc.value.status_code == 502
    assert secret not in str(exc.value)
    assert secret not in repr(exc.value)
    assert secret not in repr(exc.value.details)


@pytest.mark.parametrize("status", [401, 403, 418, 429])
def test_ing019_non_not_found_4xx_remain_general_and_do_not_signal_removal(status: int):
    from services.safe_outbound_http import OutboundCollectionError, safe_fetch

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"content-type": "text/plain"}, content=b"no classification leak", request=request)

    with pytest.raises(OutboundCollectionError) as exc:
        safe_fetch(_source(), transport=httpx.MockTransport(handler), resolver=_public)

    assert exc.value.code == "OUTBOUND_HTTP_4XX"
    assert exc.value.details == {"http_status": status}
    assert exc.value.code != "OUTBOUND_HTTP_SOURCE_NOT_FOUND"
    assert calls == 1
