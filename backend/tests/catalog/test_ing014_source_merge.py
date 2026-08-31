from __future__ import annotations

import httpx
import pytest

from services.document_version_service import DocumentVersionError, record_document_version
from services.ingestion_pipeline_service import ingestion_pipeline
from services.official_url_import_service import import_single_official_url


URL_17_9 = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/system_management_commands.html"
URL_17_18 = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/command_reference/b_1718_9300_cr/system_management_commands.html"


def _payload(url: str, **overrides):
    payload = {
        "url": url,
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


def test_ing014_different_urls_same_content_merge_and_append_source_observation(isolated_db, make_user):
    user = make_user("ing014-merge", role="Operator")
    body = b"one official command body mirrored at two reviewed URLs"
    first = import_single_official_url(
        user,
        _payload(URL_17_9, idempotency_key="ing014-url-a"),
        transport=_transport(body),
        resolver=_public,
    )
    second = import_single_official_url(
        user,
        _payload(URL_17_18, idempotency_key="ing014-url-b"),
        transport=_transport(body),
        resolver=_public,
    )

    assert first["source"]["id"] != second["source"]["id"]
    assert first["document"]["id"] == second["document"]["id"]
    assert first["document_version"]["id"] == second["document_version"]["id"]
    assert second["document_version_decision"] == "merge_same_content_different_source"
    assert second["merged"] is True
    assert second["replayed"] is True
    assert second["source_observation"]["observation_count"] == 1

    conn = isolated_db["module"].get_db_connection()
    try:
        rows = conn.execute(
            "SELECT canonical_url, document_id, legacy_document_version_id FROM ai_document_revision "
            "WHERE tenant_id = ? AND record_type = 'document_source_link' ORDER BY canonical_url",
            ("tenant-default",),
        ).fetchall()
        assert len(rows) == 2
        assert {str(row[0]) for row in rows} == {URL_17_9, URL_17_18}
        assert {str(row[1]) for row in rows} == {first["document"]["id"]}
        assert {str(row[2]) for row in rows} == {first["document_version"]["id"]}
    finally:
        conn.close()


def test_ing014_different_urls_changed_content_keep_separate_documents(isolated_db, make_user):
    user = make_user("ing014-separate", role="Operator")
    first = import_single_official_url(
        user,
        _payload(URL_17_9, idempotency_key="ing014-separate-a"),
        transport=_transport(b"first URL content"),
        resolver=_public,
    )
    second = import_single_official_url(
        user,
        _payload(URL_17_18, idempotency_key="ing014-separate-b"),
        transport=_transport(b"second URL content"),
        resolver=_public,
    )
    assert second["document"]["id"] != first["document"]["id"]
    assert second["document_version"]["id"] != first["document_version"]["id"]
    assert second["document_version_decision"] == "new_version"
    assert second["merged"] is False


def test_ing014_cross_tenant_same_hash_never_merges(isolated_db, make_user):
    first_user = make_user("ing014-tenant-a", role="Operator")
    second_user = make_user("ing014-tenant-b", role="Operator")
    first_user["tenant_id"] = "tenant-a"
    second_user["tenant_id"] = "tenant-b"
    body = b"same bytes are not a cross-tenant cache"
    first = import_single_official_url(
        first_user,
        _payload(URL_17_9, idempotency_key="ing014-tenant-a"),
        transport=_transport(body),
        resolver=_public,
    )
    second = import_single_official_url(
        second_user,
        _payload(URL_17_18, idempotency_key="ing014-tenant-b"),
        transport=_transport(body),
        resolver=_public,
    )
    assert first["document"]["id"] != second["document"]["id"]
    assert second["merged"] is False


def test_ing014_deduplication_uses_authoritative_registry_facts(isolated_db, make_user):
    user = make_user("ing014-authority", role="Operator")
    first = import_single_official_url(
        user,
        _payload(URL_17_9, idempotency_key="ing014-authority-a"),
        transport=_transport(b"authoritative source facts"),
        resolver=_public,
    )

    with pytest.raises(DocumentVersionError) as forged_url:
        record_document_version(
            {**first["source"], "canonical_url": URL_17_18},
            first["version"],
            user,
        )
    assert forged_url.value.code == "DOCUMENT_SOURCE_FACT_MISMATCH"

    with pytest.raises(DocumentVersionError) as forged_hash:
        record_document_version(
            first["source"],
            {**first["version"], "content_hash": "0" * 64},
            user,
        )
    assert forged_hash.value.code == "DOCUMENT_SOURCE_FACT_MISMATCH"
