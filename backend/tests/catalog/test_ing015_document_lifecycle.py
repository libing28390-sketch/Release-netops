from __future__ import annotations

import httpx
import pytest

from services.document_lifecycle_service import DocumentLifecycleError, get_document_lifecycle, transition_document_lifecycle
from services.ingestion_pipeline_service import ingestion_pipeline
from services.official_url_import_service import import_single_official_url


URL = "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-9/command_reference/b_179_9300_cr/lifecycle_commands.html"


def _payload(**overrides):
    payload = {
        "url": URL,
        "source_kind": "command_reference",
        "vendor": "Cisco",
        "product_family": "Catalyst 9300",
        "version_scope": {"primary": "17.9.x", "compatibility": "17.18.x"},
        "terms_review_status": "approved",
        "reviewer": "lifecycle-reviewer",
        "max_retries": 1,
    }
    payload.update(overrides)
    return payload


def _transport(body: bytes):
    return httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=body, request=request))


def _public(*_args):
    return ["72.163.4.161"]


@pytest.fixture(autouse=True)
def reset_pipeline():
    ingestion_pipeline.reset_for_tests()
    yield
    ingestion_pipeline.reset_for_tests()


def test_ing015_publish_quarantine_disable_and_request_idempotency(isolated_db, make_user):
    user = make_user("ing015-lifecycle", role="Operator")
    imported = import_single_official_url(user, _payload(idempotency_key="ing015-lifecycle-a"), transport=_transport(b"lifecycle body"), resolver=_public)
    document_id = imported["document"]["id"]
    version_id = imported["document_version"]["id"]

    initial = get_document_lifecycle(document_id, user)
    assert initial["document"]["lifecycle_status"] == "draft"
    published = transition_document_lifecycle(document_id, "published", user, document_version_id=version_id, request_id="ing015-publish")
    assert published["document"]["lifecycle_status"] == "published"
    assert published["document"]["retrieval_eligible"] is True
    assert published["document_version"]["status"] == "active"

    replay = transition_document_lifecycle(document_id, "published", user, document_version_id=version_id, request_id="ing015-publish")
    assert replay["idempotent"] is True
    assert replay["event"]["event_id"] == published["event"]["event_id"]

    quarantined = transition_document_lifecycle(document_id, "quarantined", user, document_version_id=version_id, reason="security review", request_id="ing015-quarantine")
    assert quarantined["document"]["lifecycle_status"] == "quarantined"
    assert quarantined["document"]["retrieval_eligible"] is False
    disabled = transition_document_lifecycle(document_id, "disabled", user, document_version_id=version_id, reason="maintenance", request_id="ing015-disable")
    assert disabled["document"]["lifecycle_status"] == "disabled"
    assert disabled["document_version"]["status"] == "disabled"


def test_ing015_superseded_version_keeps_published_replacement(isolated_db, make_user):
    user = make_user("ing015-superseded", role="Operator")
    first = import_single_official_url(user, _payload(idempotency_key="ing015-version-a"), transport=_transport(b"first lifecycle version"), resolver=_public)
    second = import_single_official_url(user, _payload(idempotency_key="ing015-version-b"), transport=_transport(b"second lifecycle version"), resolver=_public)
    assert second["document"]["id"] == first["document"]["id"]
    transition_document_lifecycle(first["document"]["id"], "published", user, document_version_id=first["document_version"]["id"], request_id="ing015-publish-old")
    transition_document_lifecycle(second["document"]["id"], "published", user, document_version_id=second["document_version"]["id"], request_id="ing015-publish-new")
    result = transition_document_lifecycle(
        first["document"]["id"],
        "superseded",
        user,
        document_version_id=first["document_version"]["id"],
        replacement_version_id=second["document_version"]["id"],
        reason="newer verified version",
        request_id="ing015-supersede",
    )
    assert result["document_version"]["lifecycle_status"] == "superseded"
    assert result["document_version"]["status"] == "archived"
    assert result["document"]["lifecycle_status"] == "published"
    assert result["document"]["retrieval_eligible"] is True


def test_ing015_rejects_invalid_transition_stale_cas_cross_tenant_and_viewer(isolated_db, make_user):
    user = make_user("ing015-boundary", role="Operator")
    imported = import_single_official_url(user, _payload(idempotency_key="ing015-boundary"), transport=_transport(b"boundary lifecycle"), resolver=_public)
    document_id = imported["document"]["id"]
    version_id = imported["document_version"]["id"]
    with pytest.raises(DocumentLifecycleError) as missing_replacement:
        transition_document_lifecycle(document_id, "superseded", user, document_version_id=version_id, request_id="ing015-bad-supersede")
    assert missing_replacement.value.code == "DOCUMENT_REPLACEMENT_REQUIRED"
    with pytest.raises(DocumentLifecycleError) as stale:
        transition_document_lifecycle(document_id, "published", user, document_version_id=version_id, expected_status="published", request_id="ing015-stale")
    assert stale.value.code == "DOCUMENT_LIFECYCLE_STALE"

    viewer = make_user("ing015-viewer", role="Viewer")
    with pytest.raises(DocumentLifecycleError) as denied:
        transition_document_lifecycle(document_id, "published", viewer, document_version_id=version_id, request_id="ing015-viewer")
    assert denied.value.code == "DOCUMENT_LIFECYCLE_PERMISSION_DENIED"

    other = dict(user)
    other["tenant_id"] = "tenant-other"
    with pytest.raises(DocumentLifecycleError) as not_found:
        get_document_lifecycle(document_id, other)
    assert not_found.value.code == "DOCUMENT_NOT_FOUND"


def test_ing015_api_contract_exposes_lifecycle_routes():
    from api.knowledge_documents import router

    routes = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/knowledge-v2/documents/{document_id}/lifecycle") and "GET" in methods for path, methods in routes)
    assert any(path.endswith("/knowledge-v2/documents/{document_id}/lifecycle") and "POST" in methods for path, methods in routes)

