from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from services.ingestion_pipeline_service import ingestion_pipeline
from services.official_document_publisher import _feature_for
from services.official_url_import_service import OfficialUrlImportError, import_single_official_url


OFFICIAL_URL = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/system_management_commands.html"
TROUBLESHOOTING_URL = "https://www.h3c.com/cn/d_202603/2776299_30005_0.htm"


def _payload(**overrides):
    payload = {
        "url": OFFICIAL_URL,
        "source_kind": "command_reference",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "catalog-reviewer",
        "idempotency_key": "ing002-cisco-001",
        "max_retries": 1,
    }
    payload.update(overrides)
    return payload


def _public(*_args):
    return ["72.163.4.161"]


def _transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def reset_pipeline():
    ingestion_pipeline.reset_for_tests()
    yield
    ingestion_pipeline.reset_for_tests()


def test_ing002_fetches_one_reviewed_url_and_stops_at_fetched_continuation(isolated_db, make_user):
    user = make_user("ing002-importer", role="Operator")
    body = b"Cisco official command reference"
    result = import_single_official_url(
        user,
        _payload(),
        transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain", "etag": '"v1"'}, content=body, request=request)),
        resolver=_public,
    )
    assert result["success"] is True
    assert result["continuation_required"] is True
    assert result["job"]["job_kind"] == "document_import"
    assert result["job"]["execution_state"] == "running"
    assert result["job"]["phase"] == "fetched"
    assert result["job"]["progress_percent"] == 0.0
    assert result["version"]["content_hash"] == hashlib.sha256(body).hexdigest()
    assert result["version"]["status"] == "fetched"
    assert result["version"]["raw_content_storage"] == "hash_only_memory_boundary"
    assert "content" not in result["fetch"]
    assert result["source"]["status"] == "active"
    assert result["source"]["validation_status"] == "valid"


def test_ing002_explicit_publish_completes_local_projection(isolated_db, make_user):
    user = make_user("ing002-publisher", role="Operator")
    body = b"OSPF configuration guide\nrouter ospf 1\n network 192.0.2.0 0.0.0.255 area 0"
    result = import_single_official_url(
        user,
        _payload(idempotency_key="ing002-publish", publish_to_knowledge_base=True),
        transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=body, request=request)),
        resolver=_public,
    )
    assert result["success"] is True
    assert result["published"] is True
    assert result["continuation_required"] is False
    assert result["job"]["phase"] == "completed"
    assert result["job"]["execution_state"] == "succeeded"
    assert result["publication"]["chunk_count"] >= 1
    with isolated_db["module"].get_db_connection() as conn:
        row = conn.execute(
            "SELECT source, knowledge_source_type, status FROM ai_document WHERE knowledge_source_type = 'official_url'"
        ).fetchone()
    assert row and row[0] == OFFICIAL_URL and row[1] == "official_url" and row[2] == "active"


def test_ing002_reviewed_feature_scope_is_preserved_for_a_broad_source(isolated_db, make_user):
    user = make_user("ing002-explicit-feature", role="Operator")
    result = import_single_official_url(
        user,
        _payload(
            idempotency_key="ing002-explicit-feature",
            name="Reviewed VLAN commands",
            feature="vlan",
            feature_domain="switching",
            publish_to_knowledge_base=True,
        ),
        transport=_transport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"show license tech support\nSmartAgent status",
                request=request,
            )
        ),
        resolver=_public,
    )
    assert result["success"] is True and result["published"] is True
    with isolated_db["module"].get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT feature, feature_domain, metadata_json
            FROM ai_document
            WHERE source = ? AND metadata_json->>'feature_source' = 'explicit'
            """,
            (OFFICIAL_URL,),
        ).fetchone()
    assert row and row[0] == "vlan" and row[1] == "switching"
    assert row[2]["feature_source"] == "explicit"


def test_ing002_troubleshooting_source_publishes_allowlisted_document_kind(isolated_db, make_user):
    user = make_user("ing002-troubleshooting", role="Operator")
    payload = {
        "url": TROUBLESHOOTING_URL,
        "source_kind": "troubleshooting_guide",
        "vendor": "H3C",
        "product_family": "H3C Switches",
        "version_scope": {"primary": "reviewed-current", "compatibility": "CMW710"},
        "terms_review_status": "approved",
        "reviewer": "catalog-reviewer",
        "idempotency_key": "ing002-troubleshooting-publish",
        "publish_to_knowledge_base": True,
    }
    body = b"OSPF neighbor troubleshooting\nCheck adjacency state and interface errors."
    result = import_single_official_url(
        user,
        payload,
        transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=body, request=request)),
        resolver=_public,
    )
    assert result["success"] is True
    assert result["published"] is True
    with isolated_db["module"].get_db_connection() as conn:
        row = conn.execute(
            "SELECT document_category, metadata_json, status, lifecycle_status "
            "FROM ai_document WHERE source = ? AND document_category = 'troubleshooting'",
            (TROUBLESHOOTING_URL,),
        ).fetchone()
    metadata = row[1] if row and isinstance(row[1], dict) else json.loads((row[1] if row else "") or "{}")
    assert row and row[0] == "troubleshooting" and metadata.get("source_kind") == "troubleshooting_guide"
    assert row[2] == "active" and row[3] == "published"


def test_ing002_same_idempotency_replays_version_without_second_fetch(isolated_db, make_user):
    user = make_user("ing002-replay", role="Operator")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"same", request=request)

    first = import_single_official_url(user, _payload(), transport=_transport(handler), resolver=_public)
    second = import_single_official_url(user, _payload(), transport=_transport(handler), resolver=_public)
    assert first["success"] is True and second["success"] is True
    assert second["replayed"] is True
    assert second["job"]["id"] == first["job"]["id"]
    assert second["version"]["content_hash"] == first["version"]["content_hash"]
    assert len(calls) == 1


def test_ing012_same_url_same_content_with_different_request_keys_replays_version(isolated_db, make_user):
    user = make_user("ing012-replay", role="Operator")
    body = b"same-url-same-content"
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=body, request=request)

    first = import_single_official_url(
        user,
        _payload(idempotency_key="ing012-key-a"),
        transport=_transport(handler),
        resolver=_public,
    )
    second = import_single_official_url(
        user,
        _payload(idempotency_key="ing012-key-b"),
        transport=_transport(handler),
        resolver=_public,
    )

    assert first["version"]["id"] == second["version"]["id"]
    assert second["replayed"] is True
    assert second["idempotency"]["decision"] == "replay_same_url_same_content"
    assert second["continuation_required"] is False
    assert len(calls) == 2


def test_ing012_same_url_changed_content_is_a_new_version(isolated_db, make_user):
    user = make_user("ing012-new-version", role="Operator")
    bodies = [b"version-one", b"version-two"]

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies.pop(0)
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=body, request=request)

    first = import_single_official_url(
        user,
        _payload(idempotency_key="ing012-version-a"),
        transport=_transport(handler),
        resolver=_public,
    )
    second = import_single_official_url(
        user,
        _payload(idempotency_key="ing012-version-b"),
        transport=_transport(handler),
        resolver=_public,
    )

    assert first["version"]["id"] != second["version"]["id"]
    assert second["replayed"] is False
    assert second["idempotency"]["decision"] == "new_version"
    assert second["continuation_required"] is True


def test_ing012_same_url_content_is_tenant_scoped(isolated_db, make_user):
    first_user = make_user("ing012-tenant-a", role="Operator")
    second_user = make_user("ing012-tenant-b", role="Operator")
    first_user["tenant_id"] = "tenant-a"
    second_user["tenant_id"] = "tenant-b"
    body = b"tenant-isolated-content"
    handler = lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=body, request=request)

    first = import_single_official_url(
        first_user,
        _payload(idempotency_key="ing012-tenant-a"),
        transport=_transport(handler),
        resolver=_public,
    )
    second = import_single_official_url(
        second_user,
        _payload(idempotency_key="ing012-tenant-b"),
        transport=_transport(handler),
        resolver=_public,
    )

    assert first["source"]["tenant_id"] == "tenant-a"
    assert second["source"]["tenant_id"] == "tenant-b"
    assert first["version"]["id"] != second["version"]["id"]
    assert second["replayed"] is False


def test_ing002_unallowlisted_url_fails_before_source_persist_or_network(isolated_db, make_user):
    from services.source_registry_service import list_sources

    user = make_user("ing002-boundary", role="Operator")
    with pytest.raises(OfficialUrlImportError) as invalid:
        import_single_official_url(user, _payload(url="https://www.cisco.com/unsupported/secret"), transport=_transport(lambda request: pytest.fail("network must not run")), resolver=_public)
    assert invalid.value.code == "OFFICIAL_URL_NOT_ALLOWLISTED"
    assert list_sources(user, tenant_id="tenant-default") == []


def test_ing002_missing_review_evidence_and_query_url_fail_closed(isolated_db, make_user):
    user = make_user("ing002-input", role="Operator")
    with pytest.raises(OfficialUrlImportError) as terms:
        import_single_official_url(user, _payload(terms_review_status="pending"))
    assert terms.value.code == "IMPORT_TERMS_REVIEW_REQUIRED"
    with pytest.raises(OfficialUrlImportError) as query:
        import_single_official_url(user, _payload(url=OFFICIAL_URL + "?token=bad"))
    assert query.value.code == "URL_QUERY_FORBIDDEN"


def test_ing002_ssrf_failure_is_redacted_and_recorded_as_non_retryable(isolated_db, make_user):
    user = make_user("ing002-ssrf", role="Operator")
    result = import_single_official_url(
        user,
        _payload(idempotency_key="ing002-ssrf"),
        transport=_transport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"never", request=request)),
        resolver=lambda *_: ["10.0.0.8"],
    )
    assert result["success"] is False
    assert result["job"]["execution_state"] == "failed"
    assert result["error"]["code"] == "SECRET_OR_SSRF_VIOLATION"
    assert result["error"]["retryable"] is False
    assert "10.0.0.8" not in str(result["error"])


def test_ing002_api_contract_exposes_single_url_job_route():
    from api.knowledge_ingestion import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path == "/knowledge/ingestion/official-url" and "POST" in methods for path, methods in paths)


def test_official_feature_inference_uses_source_identity_not_document_body():
    assert _feature_for(
        "Catalyst System Management Command Reference",
        "https://www.cisco.com/c/en/system_management_commands.html",
    ) == ("", "general")
    assert _feature_for(
        "OSPF Command Reference",
        "https://docs.example.test/routing/ospf_commands.html",
    ) == ("ospf", "routing")
