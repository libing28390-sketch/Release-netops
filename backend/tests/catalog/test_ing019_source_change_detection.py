from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from services.document_lifecycle_service import get_document_lifecycle, transition_document_lifecycle
from services.ingestion_pipeline_service import ingestion_pipeline
from services.official_url_import_service import import_single_official_url


OFFICIAL_URL = (
    "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/"
    "software/release/17-9/command_reference/b_179_9300_cr/"
    "system_management_commands.html"
)


def _payload(**overrides):
    payload = {
        "url": OFFICIAL_URL,
        "source_kind": "command_reference",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "ing019-reviewer",
        "max_retries": 1,
    }
    payload.update(overrides)
    return payload


def _transport(handler):
    return httpx.MockTransport(handler)


def _public(*_args):
    return ["72.163.4.161"]


def _import_official(user, body: bytes, *, key: str):
    return import_single_official_url(
        user,
        _payload(idempotency_key=key),
        transport=_transport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain", "etag": '"baseline"'},
                content=body,
                request=request,
            )
        ),
        resolver=_public,
    )


def _publish(imported: dict, user: dict, *, request_id: str) -> None:
    transition_document_lifecycle(
        imported["document"]["id"],
        "published",
        user,
        document_version_id=imported["document_version"]["id"],
        request_id=request_id,
    )


@pytest.fixture(autouse=True)
def reset_pipeline():
    ingestion_pipeline.reset_for_tests()
    yield
    ingestion_pipeline.reset_for_tests()


def test_ing019_first_official_refresh_is_baseline_with_no_detection(isolated_db, make_user):
    from services.source_registry_service import collect_source, list_source_refresh_observations

    user = make_user("ing019-baseline", role="Operator")
    imported = _import_official(user, b"first official body", key="ing019-baseline")
    source_id = imported["source"]["id"]

    refreshed = collect_source(
        source_id,
        {"method": "GET"},
        user,
        transport=_transport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain", "etag": '"same"'},
                content=b"first official body",
                request=request,
            )
        ),
        resolver=_public,
    )

    assert refreshed["refresh"]["outcome"] == "unchanged"
    assert refreshed["refresh"]["detection_type"] == "none"
    observation = list_source_refresh_observations(source_id, user)[0]
    assert observation["detection_type"] == "none"


def test_ing019_changed_hash_after_baseline_signals_version_update_without_quarantine(isolated_db, make_user):
    from services.official_source_change_service import apply_official_source_detection
    from services.source_registry_service import collect_source, get_source, list_source_refresh_observations

    user = make_user("ing019-version", role="Operator")
    imported = _import_official(user, b"version one", key="ing019-version")
    source_id = imported["source"]["id"]
    changed = collect_source(
        source_id,
        {"method": "GET"},
        user,
        transport=_transport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain", "etag": '"version-two"'},
                content=b"version two",
                request=request,
            )
        ),
        resolver=_public,
    )

    assert changed["refresh"]["detection_type"] == "version_updated"
    assert changed["version"]["content_hash"] == hashlib.sha256(b"version two").hexdigest()
    applied = apply_official_source_detection(
        source_id,
        user,
        detection_type="version_updated",
        reason_code="VERSION_CONTENT_CHANGED",
        source_version_id=changed["version"]["id"],
    )
    assert applied["applied"] is True
    assert applied["documents_quarantined"] == 0
    assert get_source(source_id, user)["status"] == "active"
    assert list_source_refresh_observations(source_id, user)[0]["detection_type"] == "version_updated"


def test_ing019_same_hash_and_304_remain_non_destructive(isolated_db, make_user):
    from services.source_registry_service import collect_source, get_source, list_source_refresh_observations

    user = make_user("ing019-stable", role="Operator")
    imported = _import_official(user, b"stable body", key="ing019-stable")
    source_id = imported["source"]["id"]
    same_hash = collect_source(
        source_id,
        {"method": "GET"},
        user,
        transport=_transport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain", "etag": '"new-validator"'},
                content=b"stable body",
                request=request,
            )
        ),
        resolver=_public,
    )
    not_modified = collect_source(
        source_id,
        {"method": "GET"},
        user,
        transport=_transport(
            lambda request: httpx.Response(304, headers={"etag": '"new-validator"'}, request=request)
        ),
        resolver=_public,
    )

    assert same_hash["refresh"]["detection_type"] == "none"
    assert not_modified["refresh"]["detection_type"] == "none"
    assert get_source(source_id, user)["status"] == "active"
    assert [row["detection_type"] for row in list_source_refresh_observations(source_id, user)[:2]] == ["none", "none"]


@pytest.mark.parametrize("status", [404, 410])
def test_ing019_removed_official_source_quarantines_linked_published_document_and_preserves_history(isolated_db, make_user, status):
    from services.source_freshness_service import refresh_sources
    from services.source_registry_service import get_source, list_source_refresh_observations, list_source_versions

    user = make_user(f"ing019-removed-{status}", role="Operator")
    imported = _import_official(user, b"removable body", key=f"ing019-removed-{status}")
    source_id = imported["source"]["id"]
    _publish(imported, user, request_id=f"ing019-publish-{status}")

    refreshed = refresh_sources(
        tenant_id="tenant-default",
        limit=10,
        user=user,
        transport=_transport(lambda request: httpx.Response(status, request=request)),
        resolver=_public,
    )

    assert refreshed["changed"] == 1
    assert get_source(source_id, user)["status"] == "quarantined"
    assert get_document_lifecycle(imported["document"]["id"], user)["document"]["lifecycle_status"] == "quarantined"
    assert len(list_source_versions(source_id, user)) == 1
    observation = list_source_refresh_observations(source_id, user)[0]
    assert observation["detection_type"] == "removed"
    assert observation["error"] == {"code": "OFFICIAL_SOURCE_REMOVED"}


def test_ing019_other_4xx_is_a_failure_and_never_quarantines(isolated_db, make_user):
    from services.source_freshness_service import refresh_sources
    from services.source_registry_service import get_source, list_source_refresh_observations

    user = make_user("ing019-client-error", role="Operator")
    imported = _import_official(user, b"still valid body", key="ing019-client-error")
    source_id = imported["source"]["id"]
    _publish(imported, user, request_id="ing019-client-error-publish")

    refreshed = refresh_sources(
        tenant_id="tenant-default",
        user=user,
        transport=_transport(lambda request: httpx.Response(403, request=request)),
        resolver=_public,
    )

    assert refreshed["failed"] == 1
    assert get_source(source_id, user)["status"] == "active"
    assert get_document_lifecycle(imported["document"]["id"], user)["document"]["lifecycle_status"] == "published"
    assert list_source_refresh_observations(source_id, user)[0]["detection_type"] == "none"


def test_ing019_safe_replacement_quarantines_but_canonical_equivalent_redirect_does_not(isolated_db, make_user):
    from services.source_freshness_service import refresh_sources
    from services.source_registry_service import get_source, list_source_refresh_observations

    user = make_user("ing019-redirect", role="Operator")
    replacement = _import_official(user, b"replacement body", key="ing019-replacement")
    replacement_source_id = replacement["source"]["id"]
    _publish(replacement, user, request_id="ing019-replacement-publish")
    replacement_url = OFFICIAL_URL + "/replaced"

    def replacement_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == OFFICIAL_URL:
            return httpx.Response(302, headers={"location": replacement_url}, request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"replacement body", request=request)

    refresh_sources(
        tenant_id="tenant-default",
        user=user,
        transport=_transport(replacement_handler),
        resolver=_public,
    )
    assert get_source(replacement_source_id, user)["status"] == "quarantined"
    replacement_observation = list_source_refresh_observations(replacement_source_id, user)[0]
    assert replacement_observation["detection_type"] == "replacement"
    assert replacement_observation["replacement_url"] == replacement_url

    equivalent_user = make_user("ing019-equivalent", role="Operator")
    equivalent_user["tenant_id"] = "tenant-equivalent"
    equivalent = _import_official(equivalent_user, b"equivalent body", key="ing019-equivalent")
    equivalent_source_id = equivalent["source"]["id"]
    equivalent_redirect = OFFICIAL_URL.replace("https://www.cisco.com", "https://www.cisco.com:443")
    equivalent_calls = []

    def equivalent_handler(request: httpx.Request) -> httpx.Response:
        equivalent_calls.append(str(request.url))
        if len(equivalent_calls) == 1:
            return httpx.Response(302, headers={"location": equivalent_redirect}, request=request)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"equivalent body", request=request)

    refresh_sources(
        tenant_id="tenant-equivalent",
        user=equivalent_user,
        transport=_transport(equivalent_handler),
        resolver=_public,
    )
    assert get_source(equivalent_source_id, equivalent_user)["status"] == "active"
    assert list_source_refresh_observations(equivalent_source_id, equivalent_user)[0]["detection_type"] == "none"


def test_ing019_non_official_source_is_not_acted_on(isolated_db, make_user):
    from services.official_source_change_service import apply_official_source_detection
    from services.source_registry_service import create_source, enable_source, get_source

    user = make_user("ing019-non-official", role="Operator")
    source = create_source(
        {
            "source_type": "internal",
            "source_kind": "internal",
            "canonical_url": "https://docs.example/internal/runbook",
            "name": "Internal runbook",
            "trust_level": "internal",
            "metadata": {"owner": "network-team"},
        },
        user,
    )
    enable_source(source["id"], user)

    applied = apply_official_source_detection(
        source["id"], user, detection_type="removed", reason_code="HTTP_404"
    )
    assert applied["applied"] is False
    assert applied["reason"] == "non_official_source"
    assert get_source(source["id"], user)["status"] == "active"


def test_ing019_detection_is_tenant_isolated_idempotent_and_exposes_redacted_signal(isolated_db, make_user):
    from api.knowledge_sources import api_list_source_refresh_observations
    from services.official_source_change_service import apply_official_source_detection
    from services.source_registry_service import get_source, record_source_refresh_observation

    tenant_a = make_user("ing019-tenant-a", role="Operator")
    tenant_a["tenant_id"] = "tenant-a"
    tenant_b = make_user("ing019-tenant-b", role="Operator")
    tenant_b["tenant_id"] = "tenant-b"
    source_a = _import_official(tenant_a, b"tenant a", key="ing019-tenant-a")
    source_b = _import_official(tenant_b, b"tenant b", key="ing019-tenant-b")
    _publish(source_a, tenant_a, request_id="ing019-tenant-a-publish")
    _publish(source_b, tenant_b, request_id="ing019-tenant-b-publish")

    record_source_refresh_observation(
        source_a["source"]["id"],
        {
            "request_method": "GET",
            "http_status": 404,
            "outcome": "failed",
            "error_code": "OFFICIAL_SOURCE_REMOVED",
            "error": {"code": "OFFICIAL_SOURCE_REMOVED"},
            "detection_type": "removed",
            "version_signal": {"previous_content_hash": source_a["version"]["content_hash"], "http_status": 404},
        },
        tenant_a,
    )
    first = apply_official_source_detection(
        source_a["source"]["id"], tenant_a, detection_type="removed", reason_code="HTTP_404"
    )
    replay = apply_official_source_detection(
        source_a["source"]["id"], tenant_a, detection_type="removed", reason_code="HTTP_404"
    )

    assert first["documents_quarantined"] == 1
    assert replay["documents_quarantined"] == 0
    assert get_source(source_a["source"]["id"], tenant_a)["status"] == "quarantined"
    assert get_source(source_b["source"]["id"], tenant_b)["status"] == "active"
    response = api_list_source_refresh_observations(source_a["source"]["id"], user=tenant_a)
    observation = response["data"][0]
    assert observation["version_signal"] == {
        "previous_content_hash": source_a["version"]["content_hash"],
        "http_status": 404,
    }
    assert "version_signal_json" not in observation
    assert "content" not in observation
    assert "secret" not in str(response).lower()


def test_ing019_change_action_failure_is_durable_and_retryable(isolated_db, make_user, monkeypatch):
    from database import get_db_connection
    import services.official_source_change_service as change_service
    from services.official_source_change_service import apply_official_source_detection
    from services.source_registry_service import record_source_refresh_observation

    user = make_user("ing019-retry", role="Operator")
    imported = _import_official(user, b"retryable body", key="ing019-retry")
    _publish(imported, user, request_id="ing019-retry-publish")
    source_id = imported["source"]["id"]
    observation = record_source_refresh_observation(
        source_id,
        {
            "request_method": "GET",
            "http_status": 404,
            "outcome": "failed",
            "error_code": "OFFICIAL_SOURCE_REMOVED",
            "error": {"code": "OFFICIAL_SOURCE_REMOVED"},
            "detection_type": "removed",
            "version_signal": {"http_status": 404},
        },
        user,
    )
    original_transition = change_service.transition_document_lifecycle

    def unavailable(*_args, **_kwargs):
        raise change_service.DocumentLifecycleError("DOCUMENT_CHANGE_DEPENDENCY_FAILED", "dependency unavailable", status_code=503)

    monkeypatch.setattr(change_service, "transition_document_lifecycle", unavailable)
    failed = apply_official_source_detection(
        source_id,
        user,
        detection_type="removed",
        reason_code="HTTP_404",
        refresh_observation_id=observation["id"],
    )
    assert failed["applied"] is False
    assert failed["action_status"] == "failed"
    assert failed["document_errors"] == [{"document_id": imported["document"]["id"], "code": "DOCUMENT_CHANGE_DEPENDENCY_FAILED"}]
    with get_db_connection() as conn:
        state_row = conn.execute(
            "SELECT metadata_json FROM ai_document_revision "
            "WHERE tenant_id = ? AND id = ? AND record_type = 'source_observation'",
            ("tenant-default", observation["id"]),
        ).fetchone()
    state = state_row[0] if isinstance(state_row[0], dict) else json.loads(state_row[0] or "{}")
    assert state["change_application"] == {
        "status": "failed",
        "attempt_count": 1,
        "last_error_code": "DOCUMENT_CHANGE_DEPENDENCY_FAILED",
        "updated_at": state["change_application"]["updated_at"],
        "applied_at": "",
    }

    monkeypatch.setattr(change_service, "transition_document_lifecycle", original_transition)
    recovered = apply_official_source_detection(
        source_id,
        user,
        detection_type="removed",
        reason_code="HTTP_404",
        refresh_observation_id=observation["id"],
    )
    assert recovered["applied"] is True
    assert recovered["action_status"] == "applied"
    assert recovered["documents_quarantined"] == 1
    with get_db_connection() as conn:
        state_row = conn.execute(
            "SELECT metadata_json FROM ai_document_revision "
            "WHERE tenant_id = ? AND id = ? AND record_type = 'source_observation'",
            ("tenant-default", observation["id"]),
        ).fetchone()
    state = state_row[0] if isinstance(state_row[0], dict) else json.loads(state_row[0] or "{}")
    assert state["change_application"]["status"] == "applied"
    assert state["change_application"]["attempt_count"] == 2
    assert state["change_application"]["last_error_code"] == ""


def test_ing019_change_action_requires_source_update_permission(isolated_db, make_user):
    from services.official_source_change_service import apply_official_source_detection
    from services.source_registry_service import SourceRegistryError, record_source_refresh_observation

    operator = make_user("ing019-action-owner", role="Operator")
    imported = _import_official(operator, b"permission body", key="ing019-action-owner")
    observation = record_source_refresh_observation(
        imported["source"]["id"],
        {
            "request_method": "GET",
            "http_status": 404,
            "outcome": "failed",
            "error_code": "OFFICIAL_SOURCE_REMOVED",
            "error": {"code": "OFFICIAL_SOURCE_REMOVED"},
            "detection_type": "removed",
            "version_signal": {"http_status": 404},
        },
        operator,
    )
    viewer = make_user("ing019-action-viewer", role="Viewer")
    with pytest.raises(SourceRegistryError) as denied:
        apply_official_source_detection(
            imported["source"]["id"],
            viewer,
            detection_type="removed",
            reason_code="HTTP_404",
            refresh_observation_id=observation["id"],
        )
    assert denied.value.code == "SOURCE_CHANGE_PERMISSION_DENIED"
