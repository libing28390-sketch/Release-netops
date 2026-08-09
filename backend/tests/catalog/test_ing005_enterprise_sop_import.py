from __future__ import annotations

import hashlib

import pytest


def _body() -> bytes:
    return b"# Internal Change SOP\n1. Request approval before a write operation.\n"


def _payload(**overrides):
    payload = {
        "title": "Emergency change SOP",
        "owner": "network-operations",
        "department": "NOC",
        "idempotency_key": "ing005-sop-1",
    }
    payload.update(overrides)
    return payload


def test_ing005_defaults_to_internal_and_keeps_enterprise_domain(isolated_db, make_user):
    from database import get_db_connection
    from services.enterprise_sop_import_service import import_enterprise_sop_file

    operator = make_user("ing005-owner", role="Operator")
    body = _body()
    result = import_enterprise_sop_file(operator, _payload(), content=body, filename="emergency-change.md", content_type="text/markdown")

    assert result["success"] is True
    assert result["classification"] == "INTERNAL"
    assert result["job"]["phase"] == "fetched"
    assert result["source"]["source_type"] == "enterprise"
    assert result["source"]["source_kind"] == "enterprise"
    assert result["source"]["trust_level"] == "internal"
    assert result["source"]["status"] == "disabled"
    assert result["source"]["fetch_enabled"] is False
    assert result["source"]["canonical_url"].startswith("https://internal.nexora.local/tenant/")
    assert "/enterprise-sop/" in result["source"]["canonical_url"]
    assert result["version"]["content_hash"] == hashlib.sha256(body).hexdigest()
    assert result["version"]["metadata"]["classification"] == "INTERNAL"
    assert result["version"]["metadata"]["knowledge_domain"] == "enterprise"
    assert result["version"]["metadata"]["document_kind"] == "enterprise_sop"
    assert result["version"]["metadata"]["provenance"]["classification"] == "INTERNAL"
    assert "content" not in result["version"]

    conn = get_db_connection()
    try:
        events = conn.execute("SELECT event_type, details_json FROM audit_events WHERE target_id = ? ORDER BY created_at", (result["source"]["id"],)).fetchall()
    finally:
        conn.close()
    event_types = [row["event_type"] for row in events]
    assert "enterprise_sop_import_started" in event_types
    assert "enterprise_sop_import_completed" in event_types
    assert all("Emergency change SOP" not in str(row["details_json"]) for row in events)


def test_ing005_rejects_public_or_external_source_claims_before_job_creation(isolated_db, make_user):
    from database import get_db_connection
    from services.enterprise_sop_import_service import EnterpriseSopImportError, import_enterprise_sop_file

    operator = make_user("ing005-boundary", role="Operator")
    with pytest.raises(EnterpriseSopImportError) as public:
        import_enterprise_sop_file(operator, _payload(classification="PUBLIC", idempotency_key="ing005-public"), content=_body(), filename="sop.md", content_type="text/markdown")
    assert public.value.code == "SOP_CLASSIFICATION_FORBIDDEN"
    with pytest.raises(EnterpriseSopImportError) as external:
        import_enterprise_sop_file(operator, _payload(source_url="https://evil.example/sop", idempotency_key="ing005-external"), content=_body(), filename="sop.md", content_type="text/markdown")
    assert external.value.code == "SOP_EXTERNAL_SOURCE_FORBIDDEN"

    conn = get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) AS count FROM kb_source_registry WHERE tenant_id = ?", (operator.get("tenant_id") or "tenant-default",)).fetchone()["count"] == 0
    finally:
        conn.close()


def test_ing005_replays_by_tenant_and_content_without_duplicate_version(isolated_db, make_user):
    from database import get_db_connection
    from services.enterprise_sop_import_service import import_enterprise_sop_file

    operator = make_user("ing005-replay", role="Operator")
    body = _body()
    first = import_enterprise_sop_file(operator, _payload(idempotency_key="ing005-replay"), content=body, filename="sop.md", content_type="text/markdown")
    second = import_enterprise_sop_file(operator, _payload(idempotency_key="ing005-replay"), content=body, filename="sop.md", content_type="text/markdown")
    assert first["success"] is True
    assert second["success"] is True
    assert second["replayed"] is True
    assert second["classification"] == "INTERNAL"
    assert second["version"]["id"] == first["version"]["id"]

    conn = get_db_connection()
    try:
        count = conn.execute("SELECT COUNT(*) AS count FROM kb_source_version WHERE tenant_id = ?", (operator.get("tenant_id") or "tenant-default",)).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


def test_ing005_viewer_is_denied_and_file_boundary_is_reused(isolated_db, make_user):
    from services.enterprise_sop_import_service import EnterpriseSopImportError, import_enterprise_sop_file

    viewer = make_user("ing005-viewer", role="Viewer")
    with pytest.raises(EnterpriseSopImportError) as exc:
        import_enterprise_sop_file(viewer, _payload(idempotency_key="ing005-viewer"), content=_body(), filename="sop.md", content_type="text/markdown")
    assert exc.value.code == "SOURCE_PERMISSION_DENIED"

    operator = make_user("ing005-pdf-mismatch", role="Operator")
    with pytest.raises(Exception) as invalid:
        import_enterprise_sop_file(operator, _payload(idempotency_key="ing005-magic"), content=b"not pdf", filename="sop.pdf", content_type="application/pdf")
    assert getattr(invalid.value, "code", "") == "LOCAL_FILE_MAGIC_MISMATCH"


def test_ing005_api_contract_exposes_sop_route():
    from api.knowledge_ingestion import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/enterprise-sop") and "POST" in methods for path, methods in paths)
