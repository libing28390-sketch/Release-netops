from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from services.document_version_service import DocumentVersionError, record_document_version
from services.ingestion_pipeline_service import ingestion_pipeline
from services.official_url_import_service import import_single_official_url


OFFICIAL_URL = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/system_management_commands.html"


def _payload(**overrides):
    payload = {
        "url": OFFICIAL_URL,
        "source_kind": "command_reference",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "catalog-reviewer",
        "max_retries": 1,
    }
    payload.update(overrides)
    return payload


def _transport(body: bytes):
    return httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=body,
            request=request,
        )
    )


def _public(*_args):
    return ["72.163.4.161"]


@pytest.fixture(autouse=True)
def reset_pipeline():
    ingestion_pipeline.reset_for_tests()
    yield
    ingestion_pipeline.reset_for_tests()


def test_ing013_changed_url_content_appends_document_version_and_supersedes_previous(isolated_db, make_user):
    user = make_user("ing013-version-chain", role="Operator")
    first = import_single_official_url(
        user,
        _payload(idempotency_key="ing013-a"),
        transport=_transport(b"document version one"),
        resolver=_public,
    )
    second = import_single_official_url(
        user,
        _payload(idempotency_key="ing013-b"),
        transport=_transport(b"document version two"),
        resolver=_public,
    )

    assert first["document"]["id"] == second["document"]["id"]
    assert first["document_version"]["id"] != second["document_version"]["id"]
    assert first["document_version"]["version_no"] == 1
    assert second["document_version"]["version_no"] == 2
    assert second["document_version"]["supersedes_version_id"] == first["document_version"]["id"]
    assert second["document_version_decision"] == "new_version"
    assert second["document_version"]["content_hash"] == hashlib.sha256(b"document version two").hexdigest()
    assert second["document"]["current_version_id"] == second["document_version"]["id"]

    conn = isolated_db["module"].get_db_connection()
    try:
        rows = conn.execute(
            "SELECT revision_no, content_hash, CAST(metadata_json AS TEXT) FROM ai_document_revision "
            "WHERE tenant_id = ? AND document_id = ? AND record_type = 'document_revision' "
            "ORDER BY revision_no",
            ("tenant-default", first["document"]["id"]),
        ).fetchall()
        assert [(int(json.loads(row[2] or "{}").get("document_version_no") or row[0]), str(row[1])) for row in rows] == [
            (1, hashlib.sha256(b"document version one").hexdigest()),
            (2, hashlib.sha256(b"document version two").hexdigest()),
        ]
    finally:
        conn.close()


def test_ing013_same_content_replays_document_version_without_duplicate(isolated_db, make_user):
    user = make_user("ing013-replay", role="Operator")
    first = import_single_official_url(
        user,
        _payload(idempotency_key="ing013-replay-a"),
        transport=_transport(b"stable document"),
        resolver=_public,
    )
    second = import_single_official_url(
        user,
        _payload(idempotency_key="ing013-replay-b"),
        transport=_transport(b"stable document"),
        resolver=_public,
    )
    assert second["document"]["id"] == first["document"]["id"]
    assert second["document_version"]["id"] == first["document_version"]["id"]
    assert second["document_version_decision"] == "replay_same_document_content"
    assert second["replayed"] is True

    conn = isolated_db["module"].get_db_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM ai_document_revision WHERE tenant_id = ? AND document_id = ? AND record_type = 'document_revision'",
            ("tenant-default", first["document"]["id"]),
        ).fetchone()[0]
        assert int(count) == 1
    finally:
        conn.close()


def test_ing013_hash_and_tenant_conflicts_fail_closed(isolated_db, make_user):
    user = make_user("ing013-boundary", role="Operator")
    first = import_single_official_url(
        user,
        _payload(idempotency_key="ing013-boundary-a"),
        transport=_transport(b"boundary source"),
        resolver=_public,
    )
    with pytest.raises(DocumentVersionError) as mismatch:
        record_document_version(
            first["source"],
            {**first["version"], "content_hash": "0" * 64},
            user,
            original_content=b"different bytes",
        )
    assert mismatch.value.code == "DOCUMENT_HASH_MISMATCH"
    with pytest.raises(DocumentVersionError) as size_mismatch:
        record_document_version(
            first["source"],
            {**first["version"], "byte_size": int(first["version"]["byte_size"]) + 1},
            user,
            original_content=b"boundary source",
        )
    assert size_mismatch.value.code == "DOCUMENT_BYTE_SIZE_MISMATCH"

    other = dict(user)
    other["tenant_id"] = "tenant-other"
    with pytest.raises(DocumentVersionError) as cross_tenant:
        record_document_version(first["source"], first["version"], other)
    assert cross_tenant.value.code == "DOCUMENT_TENANT_CONFLICT"


def test_ing013_source_reference_is_used_when_raw_bytes_are_not_retained(isolated_db, make_user):
    user = make_user("ing013-reference", role="Operator")
    first = import_single_official_url(
        user,
        _payload(idempotency_key="ing013-reference-a"),
        transport=_transport(b"hash-only source"),
        resolver=_public,
    )
    version = first["document_version"]
    assert version["original_content"] == ""
    assert version["original_content_ref"] == f"source-version://{first['version']['id']}"
    assert "hash-only source" not in str(version)
