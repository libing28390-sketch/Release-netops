"""H5: a Provider's egress allowlist may only narrow the deployment allowlist.

``approved_endpoint_patterns`` is edited with ``ai.provider.manage``;
``AI_PROVIDER_ENDPOINT_ALLOWLIST`` is server configuration.  The first must
stay inside the second, so the permission that edits a Provider cannot widen
where its API key and prompts are sent.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException

from core.config import settings

CODE = "AI_PROVIDER_ALLOWLIST_EXCEEDS_DEPLOYMENT"
USER = {"username": "admin", "role": "Administrator", "user_id": "u-admin"}
BASE_URL = "https://api.example-a.com/v1"


def _create(**overrides):
    from ai.api.providers import create_provider
    from ai.schemas.provider import AIProviderCreate

    values = {"name": f"Compat-{uuid.uuid4().hex[:6]}", "provider_type": "openai_compatible", "base_url": BASE_URL}
    values.update(overrides)
    return create_provider(AIProviderCreate(**values), user=USER)


def _update(provider_id: str, **fields):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate

    return update_provider(provider_id, AIProviderUpdate(**fields), user=USER)


def _assert_ceiling_error(exc_info, *, configured: bool) -> dict:
    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == CODE
    assert "AI_PROVIDER_ENDPOINT_ALLOWLIST" in detail["message"]
    assert detail["details"]["deployment_allowlist_configured"] is configured
    return detail


def _stored_patterns(provider_id: str) -> list[str]:
    from database.core import get_db_connection

    with get_db_connection() as conn:
        raw = conn.execute("SELECT approved_endpoint_patterns_json FROM ai_provider WHERE id = ?", (provider_id,)).fetchone()[0]
    return raw if isinstance(raw, list) else json.loads(raw or "[]")


# ── deployment allowlist configured ─────────────────────────────────────────


def test_narrowing_inside_the_deployment_allowlist_is_accepted(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.example-a.com")
    created = _create(approved_endpoint_patterns=["https://api.example-a.com/v1/*", BASE_URL])
    assert created.approved_endpoint_patterns == ["https://api.example-a.com/v1/*", BASE_URL]

    updated = _update(created.id, approved_endpoint_patterns=["https://api.example-a.com/*"])
    assert updated.approved_endpoint_patterns == ["https://api.example-a.com/*"]


def test_a_deployment_wildcard_entry_may_be_repeated_or_narrowed(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "*.example-a.com")
    created = _create(approved_endpoint_patterns=["https://*.example-a.com/*"])
    assert created.approved_endpoint_patterns == ["https://*.example-a.com/*"]
    updated = _update(created.id, approved_endpoint_patterns=["https://api.example-a.com/*"])
    assert updated.approved_endpoint_patterns == ["https://api.example-a.com/*"]


def test_a_pattern_outside_the_deployment_allowlist_is_rejected(isolated_db, monkeypatch):
    from database.core import get_db_connection

    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.example-a.com")
    name = f"Compat-{uuid.uuid4().hex[:6]}"
    with pytest.raises(HTTPException) as exc_info:
        _create(name=name, approved_endpoint_patterns=[BASE_URL, "https://api.example-b.com/v1"])
    detail = _assert_ceiling_error(exc_info, configured=True)
    assert detail["details"]["rejected_patterns"] == ["https://api.example-b.com/v1"]
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_provider WHERE name = ?", (name,)).fetchone()[0] == 0

    created = _create()
    with pytest.raises(HTTPException) as exc_info:
        _update(created.id, approved_endpoint_patterns=[BASE_URL, "https://attacker.example.com/*"])
    _assert_ceiling_error(exc_info, configured=True)
    assert _stored_patterns(created.id) == [BASE_URL]


@pytest.mark.parametrize(
    "wider",
    [
        "https://*",
        "https://*/*",
        "https://*.example-a.com/*",
        "https://api.example-a.com*",
        "https://api.example-a.co?/*",
        "https://user@api.example-a.com/*",
    ],
)
def test_a_wildcard_wider_than_the_deployment_allowlist_is_rejected(isolated_db, monkeypatch, wider):
    # A URL entry in the deployment setting is reduced to its host, exactly
    # as the request-time check does.
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "https://api.example-a.com/*")
    created = _create()
    with pytest.raises(HTTPException) as exc_info:
        _update(created.id, approved_endpoint_patterns=[wider, BASE_URL])
    detail = _assert_ceiling_error(exc_info, configured=True)
    assert detail["details"]["rejected_patterns"] == [wider]
    assert _stored_patterns(created.id) == [BASE_URL]


def test_the_auto_filled_allowlist_follows_the_same_rule(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.example-a.com")
    created = _create()
    assert created.approved_endpoint_patterns == [BASE_URL]

    # A Base URL outside the deployment allowlist never reaches the
    # auto-fill: the existing deployment endpoint check rejects it first.
    with pytest.raises(HTTPException) as exc_info:
        _update(created.id, base_url="https://api.example-b.com/v1")
    assert exc_info.value.status_code == 400
    assert "AI_PROVIDER_ENDPOINT_ALLOWLIST" in str(exc_info.value.detail)

    moved = _update(created.id, base_url="https://api.example-a.com/v2")
    assert moved.approved_endpoint_patterns == ["https://api.example-a.com/v2"]


# ── no deployment allowlist ─────────────────────────────────────────────────


def test_without_a_deployment_allowlist_only_the_own_base_url_is_accepted(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "")
    created = _create()
    assert created.approved_endpoint_patterns == [BASE_URL]
    assert _update(created.id, approved_endpoint_patterns=[BASE_URL + "/"]).approved_endpoint_patterns == [BASE_URL]

    for patterns in (["https://api.example-a.com/*"], [BASE_URL, "https://api.example-b.com/v1"], ["https://*"]):
        with pytest.raises(HTTPException) as exc_info:
            _update(created.id, approved_endpoint_patterns=patterns)
        detail = _assert_ceiling_error(exc_info, configured=False)
        assert "Base URL" in detail["message"]
    assert _stored_patterns(created.id) == [BASE_URL]

    with pytest.raises(HTTPException) as exc_info:
        _create(approved_endpoint_patterns=["https://api.example-a.com/v1*"])
    _assert_ceiling_error(exc_info, configured=False)


def test_local_providers_are_not_affected(isolated_db, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.example-a.com")
    created = _create(provider_type="ollama", base_url="http://127.0.0.1:11434")
    assert created.provider_type == "ollama"


# ── audit ───────────────────────────────────────────────────────────────────


def test_an_allowlist_change_is_audited_with_high_severity(isolated_db, monkeypatch):
    from database.core import get_db_connection

    monkeypatch.setattr(settings, "AI_PROVIDER_ENDPOINT_ALLOWLIST", "api.example-a.com")
    created = _create()
    _update(created.id, approved_endpoint_patterns=["https://api.example-a.com/*"])
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT event_type, severity, details_json FROM audit_events "
            "WHERE target_type = 'ai_provider' AND target_id = ? AND event_type = 'ai_provider.updated'",
            (created.id,),
        ).fetchall()
    assert len(rows) == 1
    event_type, severity, details_json = rows[0]
    details = details_json if isinstance(details_json, dict) else json.loads(details_json or "{}")
    assert details["changed_fields"] == ["approved_endpoint_patterns"]
    assert severity == "high"
