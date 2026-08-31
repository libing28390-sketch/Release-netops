from __future__ import annotations

import hashlib
import json

import pytest


SOURCE_URL = "https://www.cisco.com/c/en/us/products/switches/catalyst-9300-series-switches/index.html"


def _payload(**overrides):
    payload = {
        "source_url": SOURCE_URL,
        "source_kind": "product_page",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "catalog-reviewer",
        "reviewed_at": "2026-08-09T00:00:00Z",
        "evidence_url": SOURCE_URL,
        "idempotency_key": "ing004-fixture-1",
    }
    payload.update(overrides)
    return payload


def _pdf() -> bytes:
    return b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def _text() -> bytes:
    return b"# Catalyst 9300\nOfficial command reference\n"


def test_ing004_imports_one_official_pdf_and_persists_provenance(isolated_db, make_user):
    from database import get_db_connection
    from services.local_official_file_import_service import import_local_official_file

    operator = make_user("ing004-importer", role="Operator")
    body = _pdf()
    result = import_local_official_file(operator, _payload(), content=body, filename="c9300-guide.pdf", content_type="application/pdf")

    assert result["success"] is True
    assert result["continuation_required"] is True
    assert result["job"]["phase"] == "fetched"
    assert result["version"]["content_hash"] == hashlib.sha256(body).hexdigest()
    assert result["version"]["byte_size"] == len(body)
    assert result["version"]["raw_content_storage"] == "hash_only_memory_boundary"
    assert "content" not in result["version"]
    proof = result["provenance"]
    assert proof["proof_type"] == "official_source_url_plus_local_content_hash"
    assert proof["source_url"] == SOURCE_URL
    assert proof["evidence_url"] == SOURCE_URL
    assert proof["content_hash"] == hashlib.sha256(body).hexdigest()
    assert proof["filename"] == "c9300-guide.pdf"
    assert proof["byte_size"] == len(body)
    assert result["version"]["metadata"]["provenance"] == proof

    conn = get_db_connection()
    try:
        tenant_id = operator.get("tenant_id") or "tenant-default"
        source_count = conn.execute("SELECT COUNT(*) AS count FROM ai_document WHERE tenant_id = ? AND id = ?", (tenant_id, result["source"]["id"])).fetchone()["count"]
        version_count = conn.execute(
            "SELECT COUNT(*) AS count FROM ai_document_revision "
            "WHERE tenant_id = ? AND legacy_source_id = ? AND record_type = 'source_version'",
            (tenant_id, result["source"]["id"]),
        ).fetchone()["count"]
        events = conn.execute("SELECT event_type, details_json FROM audit_events WHERE target_id = ? ORDER BY created_at", (result["source"]["id"],)).fetchall()
    finally:
        conn.close()
    assert source_count == 1
    assert version_count == 1
    event_types = [row["event_type"] for row in events]
    assert "local_file_import_started" in event_types
    assert "local_file_import_completed" in event_types
    assert all(body.decode("latin1") not in str(row["details_json"]) for row in events)


def test_ing004_replays_same_tenant_key_and_deduplicates_same_content(isolated_db, make_user):
    from database import get_db_connection
    from services.local_official_file_import_service import import_local_official_file

    operator = make_user("ing004-replay", role="Operator")
    body = _text()
    first = import_local_official_file(operator, _payload(idempotency_key="ing004-replay"), content=body, filename="guide.md", content_type="text/markdown")
    second = import_local_official_file(operator, _payload(idempotency_key="ing004-replay"), content=body, filename="guide.md", content_type="text/markdown")
    assert first["success"] is True
    assert second["success"] is True
    assert second["replayed"] is True
    assert second["version"]["content_hash"] == first["version"]["content_hash"]

    conn = get_db_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM ai_document_revision "
            "WHERE tenant_id = ? AND legacy_source_id = ? AND record_type = 'source_version'",
            (operator.get("tenant_id") or "tenant-default", first["source"]["id"]),
        ).fetchone()["count"]
    finally:
        conn.close()
    assert count == 1


@pytest.mark.parametrize(
    ("filename", "content_type", "body", "code"),
    [
        ("..\\escape.pdf", "application/pdf", _pdf(), "LOCAL_FILE_NAME_INVALID"),
        ("guide.exe", "application/octet-stream", b"MZ", "LOCAL_FILE_TYPE_FORBIDDEN"),
        ("guide.pdf", "application/pdf", b"not a pdf", "LOCAL_FILE_MAGIC_MISMATCH"),
        ("guide.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"not a docx", "LOCAL_FILE_MAGIC_MISMATCH"),
        ("guide.md", "text/markdown", b"\x00binary", "LOCAL_FILE_BINARY_FORBIDDEN"),
    ],
)
def test_ing004_file_name_type_and_magic_fail_closed(isolated_db, make_user, filename, content_type, body, code):
    from services.local_official_file_import_service import LocalOfficialFileImportError, import_local_official_file

    operator = make_user("ing004-invalid-file", role="Operator")
    with pytest.raises(LocalOfficialFileImportError) as exc:
        import_local_official_file(operator, _payload(idempotency_key=f"bad-{code}"), content=body, filename=filename, content_type=content_type)
    assert exc.value.code == code


def test_ing004_requires_official_proof_before_job_or_source_creation(isolated_db, make_user):
    from database import get_db_connection
    from services.local_official_file_import_service import LocalOfficialFileImportError, import_local_official_file

    operator = make_user("ing004-no-proof", role="Operator")
    with pytest.raises(LocalOfficialFileImportError) as missing:
        import_local_official_file(operator, _payload(terms_review_status="pending"), content=_pdf(), filename="guide.pdf", content_type="application/pdf")
    assert missing.value.code == "IMPORT_TERMS_REVIEW_REQUIRED"
    with pytest.raises(LocalOfficialFileImportError) as query:
        import_local_official_file(operator, _payload(source_url=SOURCE_URL + "?download=1"), content=_pdf(), filename="guide.pdf", content_type="application/pdf")
    assert query.value.code == "URL_QUERY_FORBIDDEN"

    conn = get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) AS count FROM ai_document WHERE tenant_id = ?", (operator.get("tenant_id") or "tenant-default",)).fetchone()["count"] == 0
    finally:
        conn.close()


def test_ing004_evidence_url_cannot_be_replaced_by_unreviewed_url(isolated_db, make_user):
    from services.local_official_file_import_service import LocalOfficialFileImportError, import_local_official_file

    operator = make_user("ing004-evidence", role="Operator")
    with pytest.raises(LocalOfficialFileImportError) as exc:
        import_local_official_file(operator, _payload(evidence_url="https://evil.example/file.pdf"), content=_pdf(), filename="guide.pdf", content_type="application/pdf")
    assert exc.value.code == "PROVENANCE_EVIDENCE_URL_MISMATCH"


def test_ing004_viewer_cannot_create_local_official_file_job(isolated_db, make_user):
    from services.local_official_file_import_service import LocalOfficialFileImportError, import_local_official_file

    viewer = make_user("ing004-viewer", role="Viewer")
    with pytest.raises(LocalOfficialFileImportError) as exc:
        import_local_official_file(viewer, _payload(idempotency_key="viewer-denied"), content=_pdf(), filename="guide.pdf", content_type="application/pdf")
    assert exc.value.code == "SOURCE_PERMISSION_DENIED"


def test_ing004_server_owns_hash_and_rejects_cross_tenant_replay(isolated_db, make_user):
    from services.local_official_file_import_service import import_local_official_file

    first_user = make_user("ing004-tenant-a", role="Operator")
    other_user = make_user("ing004-tenant-b", role="Operator")
    other_user["tenant_id"] = "tenant-ing004-b"
    body = _pdf()
    first = import_local_official_file(first_user, _payload(idempotency_key="same-key"), content=body, filename="guide.pdf", content_type="application/pdf")
    second = import_local_official_file(other_user, _payload(idempotency_key="same-key"), content=body, filename="guide.pdf", content_type="application/pdf")
    assert first["success"] is True
    assert second["success"] is True
    assert second["replayed"] is False
    assert first["job"]["tenant_id"] != second["job"]["tenant_id"]
    assert first["version"]["content_hash"] == second["version"]["content_hash"]


def test_ing004_api_contract_exposes_multipart_official_file_route():
    from api.knowledge_ingestion import router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/official-file") and "POST" in methods for path, methods in paths)
