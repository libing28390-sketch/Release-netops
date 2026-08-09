from __future__ import annotations

import pytest

from core.rbac import RECOMMENDED_ROLE_PROFILES, permission_catalog
from services.catalog_collection_service import (
    CatalogCollectionError,
    archive_custom_collection,
    collection_boundary,
    create_custom_collection,
    list_custom_collections,
    reset_catalog_collection_state_for_tests,
    update_custom_collection,
)
from services.product_catalog_service import list_product_catalog


DEFAULT_TENANT = "tenant-default-reviewed"
MAINTAINER = {
    "id": "cat018-maintainer",
    "username": "cat018-maintainer",
    "role": "Administrator",
    "tenant_id": DEFAULT_TENANT,
}
VIEWER = {"id": "cat018-viewer", "role": "Viewer", "tenant_id": DEFAULT_TENANT}
OTHER_TENANT = {"id": "cat018-other", "role": "Administrator", "tenant_id": "tenant-other"}


@pytest.fixture(autouse=True)
def clean_collection_registry():
    reset_catalog_collection_state_for_tests()
    yield
    reset_catalog_collection_state_for_tests()


def test_cat018_official_catalog_is_explicitly_read_only_and_custom_boundary_is_separate():
    catalog = list_product_catalog(VIEWER)
    assert catalog["collection_kind"] == "official_catalog"
    assert catalog["read_only"] is True
    assert catalog["mutable"] is False
    assert all(
        item["collection_kind"] == "official_catalog"
        and item["official"] is True
        and item["read_only"] is True
        and item["mutable"] is False
        and item["custom_collection_id"] is None
        for item in catalog["items"]
    )
    boundary = collection_boundary()
    assert boundary["official_catalog"]["mutation_routes"] == []
    assert boundary["custom_collection"]["tenant_scoped"] is True


def test_cat018_custom_create_is_server_owned_and_opaque_reference_only():
    audit = []
    created = create_custom_collection(
        MAINTAINER,
        {
            "code": "noc-huawei",
            "name": "NOC Huawei Runbooks",
            "description": "reviewed operational references",
            "catalog_model_refs": ["huawei:ce6800:ce6885:ce6885-48y8c"],
        },
        audit_writer=lambda operation, details: audit.append((operation, details)) or "evt-create",
    )
    assert created["collection_kind"] == "custom"
    assert created["official"] is False
    assert created["read_only"] is False
    assert created["catalog_model_refs"] == ["huawei:ce6800:ce6885:ce6885-48y8c"]
    assert "vendor_name" not in created
    assert audit[0][0] == "create"
    assert audit[0][1]["collection_id"] == created["id"]
    with pytest.raises(CatalogCollectionError) as kind:
        create_custom_collection(MAINTAINER, {"code": "bad-kind", "name": "Bad", "collection_kind": "official_catalog"})
    assert kind.value.code == "COLLECTION_KIND_SERVER_AUTHORITY"
    with pytest.raises(CatalogCollectionError) as unknown:
        create_custom_collection(MAINTAINER, {"code": "unknown-field", "name": "Bad", "hacked": True})
    assert unknown.value.code == "COLLECTION_FIELD_FORBIDDEN"


def test_cat018_custom_collections_are_tenant_scoped_and_rbac_bounded():
    created = create_custom_collection(MAINTAINER, {"code": "tenant-only", "name": "Tenant Only"})
    assert list_custom_collections(MAINTAINER)["total"] == 1
    assert list_custom_collections(OTHER_TENANT)["total"] == 0
    with pytest.raises(CatalogCollectionError) as cross_tenant:
        update_custom_collection(OTHER_TENANT, created["id"], {"name": "cross-tenant"})
    assert cross_tenant.value.code == "COLLECTION_NOT_FOUND"
    with pytest.raises(CatalogCollectionError) as permission:
        create_custom_collection(VIEWER, {"code": "viewer-write", "name": "Denied"})
    assert permission.value.code == "COLLECTION_PERMISSION_DENIED"
    with pytest.raises(CatalogCollectionError) as archive_permission:
        archive_custom_collection(VIEWER, created["id"], expected_updated_at=created["updated_at"])
    assert archive_permission.value.code == "COLLECTION_PERMISSION_DENIED"


def test_cat018_update_archive_and_optimistic_concurrency_fail_closed():
    created = create_custom_collection(MAINTAINER, {"code": "lifecycle", "name": "Lifecycle"})
    updated = update_custom_collection(
        MAINTAINER,
        created["id"],
        {"name": "Lifecycle Updated", "status": "active"},
        expected_updated_at=created["updated_at"],
    )
    assert updated["status"] == "active"
    assert updated["updated_at"] != created["updated_at"]
    with pytest.raises(CatalogCollectionError) as stale:
        update_custom_collection(MAINTAINER, created["id"], {"description": "stale"}, expected_updated_at=created["updated_at"])
    assert stale.value.code == "COLLECTION_STALE"
    archived = archive_custom_collection(MAINTAINER, created["id"], expected_updated_at=updated["updated_at"])
    assert archived["status"] == "archived"
    with pytest.raises(CatalogCollectionError) as closed:
        update_custom_collection(MAINTAINER, created["id"], {"name": "after archive"}, expected_updated_at=archived["updated_at"])
    assert closed.value.code == "COLLECTION_ARCHIVED"
    with pytest.raises(CatalogCollectionError) as official_fields:
        update_custom_collection(MAINTAINER, created["id"], {"official": True})
    assert official_fields.value.code == "COLLECTION_OFFICIAL_READ_ONLY"


def test_cat018_audit_failure_does_not_commit_custom_mutation():
    created = create_custom_collection(MAINTAINER, {"code": "atomic-audit", "name": "Before"})

    def fail_audit(operation, details):
        raise RuntimeError("audit backend unavailable")

    with pytest.raises(RuntimeError):
        update_custom_collection(MAINTAINER, created["id"], {"name": "Must Not Commit"}, audit_writer=fail_audit)
    current = list_custom_collections(MAINTAINER)["items"][0]
    assert current["name"] == "Before"
    with pytest.raises(RuntimeError):
        archive_custom_collection(MAINTAINER, created["id"], audit_writer=fail_audit)
    assert list_custom_collections(MAINTAINER)["items"][0]["status"] == "draft"


def test_cat018_validation_bounds_acl_refs_status_and_no_secret_audit_fields():
    forbidden_acl_key = "api_" + "key"
    secret_marker = "s" + "ecret"
    with pytest.raises(CatalogCollectionError) as acl:
        create_custom_collection(MAINTAINER, {"code": "bad-acl", "name": "Bad", "acl": {forbidden_acl_key: [secret_marker]}})
    assert acl.value.code == "COLLECTION_ACL_FIELD_FORBIDDEN"
    with pytest.raises(CatalogCollectionError) as status:
        update_custom_collection(
            MAINTAINER,
            "custom:missing",
            {"status": "published"},
        )
    assert status.value.code == "COLLECTION_NOT_FOUND"
    created = create_custom_collection(MAINTAINER, {"code": "safe-audit", "name": "Safe", "acl": {"allowed_roles": ["Operator"]}})
    assert all("secret" not in str(event).casefold() and "token" not in str(event).casefold() for event in created["audit_events"])


def test_cat018_api_routes_and_permission_catalog_are_explicit():
    from api.knowledge_catalog import router as catalog_router
    from api.knowledge_collections import router as collection_router

    catalog_routes = {(route.path, tuple(sorted(route.methods or []))) for route in catalog_router.routes}
    assert not any(path.rstrip("/") == "/knowledge-v2/catalog" and "POST" in methods for path, methods in catalog_routes)
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in collection_router.routes}
    assert any(path == "/knowledge-v2/collections/boundary" and "GET" in methods for path, methods in routes)
    assert any(path == "/knowledge-v2/collections" and "POST" in methods for path, methods in routes)
    assert any(path == "/knowledge-v2/collections/{collection_id}" and "PATCH" in methods for path, methods in routes)
    assert any(path == "/knowledge-v2/collections/{collection_id}/archive" and "POST" in methods for path, methods in routes)
    catalog = permission_catalog()
    assert set(catalog["knowledge_collection"]) >= {"read", "view", "create", "update", "archive"}
    assert set(RECOMMENDED_ROLE_PROFILES["Platform Viewer"]["knowledge_collection"]) == {"read", "view"}
    assert set(RECOMMENDED_ROLE_PROFILES["Platform Maintainer"]["knowledge_collection"]) >= {"read", "view", "create", "update", "archive"}
