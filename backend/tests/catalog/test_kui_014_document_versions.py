from __future__ import annotations

import httpx
import pytest

from api.knowledge_documents import router
from services.document_lifecycle_service import rollback_document_version, transition_document_lifecycle
from services.document_version_service import DocumentVersionError, compare_document_versions
from services.ingestion_pipeline_service import ingestion_pipeline
from services.official_url_import_service import import_single_official_url


URL = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/kui014.html"


def _payload(**overrides):
    payload = {
        "url": URL,
        "source_kind": "command_reference",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "kui014-reviewer",
        "max_retries": 1,
    }
    payload.update(overrides)
    return payload


def _transport(body: bytes, etag: str):
    return httpx.MockTransport(lambda request: httpx.Response(
        200,
        headers={"content-type": "text/plain", "etag": etag},
        content=body,
        request=request,
    ))


def _public(*_args):
    return ["72.163.4.161"]


@pytest.fixture(autouse=True)
def reset_pipeline():
    ingestion_pipeline.reset_for_tests()
    yield
    ingestion_pipeline.reset_for_tests()


def test_kui014_compare_publish_supersede_and_atomic_rollback(isolated_db, make_user):
    user = make_user("kui014-version-admin", role="Operator")
    first = import_single_official_url(
        user,
        _payload(idempotency_key="kui014-a"),
        transport=_transport(b"show version\nold output\n", '"kui014-a"'),
        resolver=_public,
    )
    second = import_single_official_url(
        user,
        _payload(idempotency_key="kui014-b"),
        transport=_transport(b"show version\nnew output\n", '"kui014-b"'),
        resolver=_public,
    )
    assert first["document"]["id"] == second["document"]["id"]
    document_id = first["document"]["id"]
    first_id = first["document_version"]["id"]
    second_id = second["document_version"]["id"]

    compared = compare_document_versions(document_id, first_id, second_id, user)
    assert compared["content_changed"] is True
    assert compared["line_diff"]["left_lines"] >= 0
    assert compared["raw_content_included"] is False
    assert "original_content" not in compared
    assert "normalized_content" not in compared

    published_first = transition_document_lifecycle(
        document_id, "published", user, document_version_id=first_id, request_id="kui014-publish-a"
    )
    assert published_first["document"]["current_version_id"] == first_id
    transition_document_lifecycle(
        document_id, "published", user, document_version_id=second_id, request_id="kui014-publish-b"
    )
    superseded = transition_document_lifecycle(
        document_id,
        "superseded",
        user,
        document_version_id=first_id,
        replacement_version_id=second_id,
        request_id="kui014-supersede",
        reason="newer version approved",
    )
    assert superseded["document_version"]["lifecycle_status"] == "superseded"
    assert superseded["document"]["current_version_id"] == second_id

    rolled_back = rollback_document_version(
        document_id,
        first_id,
        user,
        request_id="kui014-rollback",
        reason="validated rollback",
    )
    assert rolled_back["document"]["current_version_id"] == first_id
    assert rolled_back["document"]["lifecycle_status"] == "published"
    assert rolled_back["document_version"]["lifecycle_status"] == "published"
    assert rolled_back["event"]["operation"] == "rollback"
    replay = rollback_document_version(document_id, first_id, user, request_id="kui014-rollback")
    assert replay["idempotent"] is True


def test_kui014_compare_is_tenant_scoped_and_routes_are_confirmed(isolated_db, make_user):
    user = make_user("kui014-scope", role="Operator")
    imported = import_single_official_url(
        user,
        _payload(idempotency_key="kui014-scope"),
        transport=_transport(b"scope body", '"kui014-scope"'),
        resolver=_public,
    )
    other = dict(user)
    other["tenant_id"] = "tenant-kui014-other"
    with pytest.raises(DocumentVersionError) as exc:
        compare_document_versions(
            imported["document"]["id"],
            imported["document_version"]["id"],
            "missing-version",
            other,
        )
    assert exc.value.code == "DOCUMENT_VERSION_NOT_FOUND"

    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/{document_id}/versions") and "GET" in methods for path, methods in routes)
    assert any(path.endswith("/{document_id}/versions/compare") and "GET" in methods for path, methods in routes)
    assert any(path.endswith("/{document_id}/versions/{version_id}/publish") and "POST" in methods for path, methods in routes)
    assert any(path.endswith("/{document_id}/versions/{version_id}/supersede") and "POST" in methods for path, methods in routes)
    assert any(path.endswith("/{document_id}/versions/{version_id}/rollback") and "POST" in methods for path, methods in routes)
