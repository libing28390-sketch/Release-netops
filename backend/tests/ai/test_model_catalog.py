from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi import HTTPException

from ai.api import models as models_api
from ai.schemas.model import AIModelCatalogImportRequest
from ai.services import model_catalog
from database.core import get_db_connection


_USER = {"role": "Administrator", "username": "catalog-test", "tenant_id": "tenant-default"}
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
_TEST_KEY = "catalog-test-secret-123456"


def _insert_provider(provider_id: str, base_url: str, *, provider_type: str = "openai_compatible", patterns=None):
    now = "2026-11-24T00:00:00+00:00"
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_provider (
                id, name, provider_type, base_url, api_key_encrypted, enabled,
                created_at, updated_at, approved_endpoint_patterns_json, data_region
            ) VALUES (?, ?, ?, ?, 'encrypted-test-key', 1, ?, ?, ?, 'global')
            """,
            (provider_id, provider_id, provider_type, base_url, now, now, json.dumps(patterns or [base_url])),
        )
        conn.commit()


def _mock_http(monkeypatch, handler):
    real_client = model_catalog.httpx.Client
    transport = httpx.MockTransport(handler)

    def make_client(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(model_catalog.httpx, "Client", make_client)


def _allow_catalog(monkeypatch, allowed_host="generativelanguage.googleapis.com"):
    monkeypatch.setattr(model_catalog.ai_security_gateway, "assert_egress_allowed", lambda **_kwargs: None)
    monkeypatch.setattr(
        model_catalog,
        "deployment_endpoint_allowed",
        lambda url: (urlsplit(str(url)).hostname or "").lower() == allowed_host,
    )
    monkeypatch.setattr(model_catalog, "decrypt_api_key", lambda _token, *, provider_id: _TEST_KEY)


def test_gemini_catalog_uses_saved_credential_on_fixed_native_endpoint(isolated_db, monkeypatch):
    _insert_provider("provider-gemini", _GEMINI_BASE)
    _allow_catalog(monkeypatch)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/gemini-2.0-flash", "displayName": "Gemini Flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/text-embedding-004", "displayName": "Text Embedding", "supportedGenerationMethods": ["embedContent"]},
                    {"name": "models/gemini-2.0-flash-live-001", "displayName": "Live", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-2.0-flash-preview-image-generation", "supportedGenerationMethods": ["generateContent"]},
                ]
            },
        )

    _mock_http(monkeypatch, handler)
    items = model_catalog.discover_provider_model_catalog("provider-gemini", user=_USER)

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1beta/models"
    assert requests[0].url.query.decode("ascii") == "pageSize=100"
    assert requests[0].headers["x-goog-api-key"] == _TEST_KEY
    assert "authorization" not in requests[0].headers
    assert _TEST_KEY not in str(requests[0].url)
    assert items == [
        {"model_code": "gemini-2.0-flash", "name": "Gemini Flash", "model_type": "chat", "source": "account", "already_registered": False},
        {"model_code": "text-embedding-004", "name": "Text Embedding", "model_type": "embedding", "source": "account", "already_registered": False},
    ]
    assert _TEST_KEY not in json.dumps(items)


def test_gemini_exact_base_approval_falls_back_to_saved_openai_compatible_path(isolated_db, monkeypatch):
    _insert_provider(
        "provider-gemini-fallback",
        _GEMINI_BASE,
        patterns=[_GEMINI_BASE, "https://generativelanguage.googleapis.com/v1beta/openai/*"],
    )
    _allow_catalog(monkeypatch)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "gemini-2.5-flash"}]})

    _mock_http(monkeypatch, handler)
    items = model_catalog.discover_provider_model_catalog("provider-gemini-fallback", user=_USER)

    assert len(requests) == 1
    assert requests[0].url.path == "/v1beta/openai/models"
    assert requests[0].headers["authorization"] == f"Bearer {_TEST_KEY}"
    assert items[0]["model_type"] == "unknown"


def test_catalog_rejects_provider_endpoint_outside_saved_allowlist(isolated_db, monkeypatch):
    _insert_provider("provider-gemini-denied", _GEMINI_BASE, patterns=["https://other.example/v1"])
    _allow_catalog(monkeypatch)
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return httpx.Response(200, json={"models": []})

    _mock_http(monkeypatch, handler)
    with pytest.raises(HTTPException) as exc_info:
        model_catalog.discover_provider_model_catalog("provider-gemini-denied", user=_USER)
    assert exc_info.value.status_code == 403
    assert called is False


def test_catalog_upstream_error_does_not_echo_response_body_or_credential(isolated_db, monkeypatch):
    _insert_provider("provider-gemini-error", _GEMINI_BASE)
    _allow_catalog(monkeypatch)
    redirects = []

    def handler(request):
        redirects.append(request.url)
        return httpx.Response(500, text=f"failed with {_TEST_KEY}")

    _mock_http(monkeypatch, handler)
    with pytest.raises(HTTPException) as exc_info:
        model_catalog.discover_provider_model_catalog("provider-gemini-error", user=_USER)

    assert exc_info.value.status_code == 502
    assert _TEST_KEY not in str(exc_info.value.detail)
    assert len(redirects) == 1


def test_catalog_import_is_atomic_deduplicated_and_does_not_create_routes(isolated_db):
    _insert_provider("provider-import", "https://api.example.com/v1")
    payload = AIModelCatalogImportRequest(
        items=[
            {"model_code": "example-chat-1", "name": "Example Chat", "model_type": "chat"},
            {"model_code": "example-embed-1", "name": "Example Embedding", "model_type": "embedding"},
            {"model_code": "example-chat-1", "name": "Duplicate Entry", "model_type": "chat"},
        ]
    )

    first = models_api.import_provider_model_catalog("provider-import", payload, user=_USER)
    second = models_api.import_provider_model_catalog("provider-import", payload, user=_USER)

    assert first == {"created": 2, "skipped": 1}
    assert second == {"created": 0, "skipped": 3}
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT model_code, model_type, enabled, is_default, thinking_supported,
                   tool_call_supported, json_supported, stream_supported
            FROM ai_model WHERE provider_id = ? ORDER BY model_code
            """,
            ("provider-import",),
        ).fetchall()
        routes = conn.execute("SELECT COUNT(*) FROM ai_model_route").fetchone()[0]

    assert [tuple(row) for row in rows] == [
        ("example-chat-1", "chat", 1, 0, 0, 0, 0, 0),
        ("example-embed-1", "embedding", 1, 0, 0, 0, 0, 0),
    ]
    assert routes == 0


@pytest.mark.parametrize(
    ("base", "provider_type", "path", "credential_header", "response", "expected_type"),
    [
        (
            "https://api.anthropic.com/v1", "anthropic", "/v1/models", "x-api-key",
            {"data": [{"id": "claude-test", "display_name": "Claude"}], "has_more": False}, "chat",
        ),
        (
            "https://api.x.ai/v1", "openai_compatible", "/v1/language-models", "authorization",
            {"models": [{"id": "grok-test"}]}, "chat",
        ),
        (
            "https://api.cohere.ai/compatibility/v1", "openai_compatible", "/v1/models", "authorization",
            {"models": [{"name": "embed-test", "endpoints": ["embed"]}]}, "embedding",
        ),
        (
            "https://api.mistral.ai/v1", "openai_compatible", "/v1/models", "authorization",
            {"data": [{"id": "mistral-test", "capabilities": {"completion_chat": True}}]}, "chat",
        ),
    ],
)
def test_catalog_uses_documented_international_endpoints(
    isolated_db, monkeypatch, base, provider_type, path, credential_header, response, expected_type,
):
    _insert_provider("provider-native", base, provider_type=provider_type)
    _allow_catalog(monkeypatch, urlsplit(base).hostname)

    def handler(request):
        assert request.url.path == path
        assert request.headers[credential_header].endswith(_TEST_KEY)
        return httpx.Response(200, json=response)

    _mock_http(monkeypatch, handler)
    items = model_catalog.discover_provider_model_catalog("provider-native", user=_USER)
    assert [item["model_type"] for item in items] == [expected_type]
