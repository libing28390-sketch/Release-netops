from __future__ import annotations

import httpx
import pytest

from services.safe_outbound_http import OutboundCollectionError, safe_fetch_url


def _public_resolver(_host: str, _port: int):
    return ["93.184.216.34"]


def test_safe_fetch_url_allows_only_bounded_read_only_public_content() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<p>ok</p>",
            request=request,
        )

    result = safe_fetch_url(
        "https://example.com/public?q=weather",
        method="GET",
        allowed_hosts=("example.com",),
        timeout_seconds=5,
        max_bytes=1024,
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )

    assert seen and seen[0].method == "GET"
    assert result.content == b"<p>ok</p>"
    assert result.content_type == "text/html"
    assert result.resolved_addresses == ("93.184.216.34",)


def test_safe_fetch_url_rejects_credentials_redirects_and_private_targets() -> None:
    with pytest.raises(OutboundCollectionError) as credential_exc:
        safe_fetch_url("https://example.com/search?token=secret", resolver=_public_resolver)
    assert credential_exc.value.code == "OUTBOUND_QUERY_CREDENTIAL_FORBIDDEN"

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://other.example/"}, request=request)

    with pytest.raises(OutboundCollectionError) as redirect_exc:
        safe_fetch_url(
            "https://example.com/redirect",
            allowed_hosts=("example.com",),
            transport=httpx.MockTransport(redirect_handler),
            resolver=_public_resolver,
        )
    assert redirect_exc.value.code == "OUTBOUND_REDIRECT_FORBIDDEN"

    with pytest.raises(OutboundCollectionError) as private_exc:
        safe_fetch_url("https://127.0.0.1/", resolver=_public_resolver)
    assert private_exc.value.code == "OUTBOUND_IP_LITERAL_FORBIDDEN"
