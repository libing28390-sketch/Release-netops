from __future__ import annotations

import pytest

from services.product_catalog_service import (
    ProductCatalogError,
    create_custom_product_model,
    delete_custom_product_model,
    list_product_aliases,
    list_product_catalog,
    resolve_product_alias_dry_run,
    update_custom_product_model,
)


DEFAULT_USER = {"id": "viewer-1", "role": "Viewer", "tenant_id": "tenant-default-reviewed"}
RUNTIME_DEFAULT_USER = {"id": "admin", "role": "Administrator", "tenant_id": "tenant-default"}


def test_cat013_catalog_listing_is_tenant_scoped_and_filterable():
    result = list_product_catalog(DEFAULT_USER)
    assert result["read_only"] is True
    assert result["persistence_status"] == "contract_only_read_only_seed"
    assert result["total"] == 12
    cisco = list_product_catalog(DEFAULT_USER, vendor_id="cisco")
    assert cisco["total"] == 3
    assert {item["series_code"] for item in cisco["items"]} == {"c9300"}
    filtered = list_product_catalog(DEFAULT_USER, model="48p")
    assert [item["model_code"] for item in filtered["items"]] == ["C9300-48P"]
    assert all(item["status"] == "draft" for item in result["items"])
    assert list_product_catalog({"role": "Viewer", "tenant_id": "tenant-other"})["total"] == 0


def test_cat013_runtime_default_tenant_gets_read_only_reviewed_seed_projection():
    result = list_product_catalog(RUNTIME_DEFAULT_USER)
    assert result["tenant_id"] == "tenant-default"
    assert result["total"] == 12
    assert all(item["tenant_id"] == "tenant-default" for item in result["items"])

    aliases = list_product_aliases(RUNTIME_DEFAULT_USER)
    assert aliases["total"] == 14
    assert all(item["tenant_id"] == "tenant-default" for item in aliases["items"])

    resolution = resolve_product_alias_dry_run(RUNTIME_DEFAULT_USER, "C9300-48P")
    assert resolution["outcome"] == "unique"
    assert resolution["candidates"][0]["model"]["tenant_id"] == "tenant-default"


def test_cat013_alias_queue_exposes_conflicts_without_promoting_drafts():
    result = list_product_aliases(DEFAULT_USER)
    assert result["read_only"] is True
    assert result["total"] == 14
    assert len(result["conflicts"]) == 4
    assert all(item["seed_status"] == "draft" for item in result["items"])
    assert all(item["model"]["product_model_id"] == item["product_model_id"] for item in result["items"])
    pending = list_product_aliases(DEFAULT_USER, conflict_status="ambiguous_pending_review")
    assert pending["total"] == 10
    assert all(item["conflict_status"] == "ambiguous_pending_review" for item in pending["items"])


def test_cat013_alias_dry_run_is_explicit_and_never_authorizes_driver():
    candidates = resolve_product_alias_dry_run(DEFAULT_USER, "CE68")
    assert candidates["dry_run"] is True
    assert candidates["outcome"] == "candidates"
    assert candidates["requires_clarification"] is True
    assert candidates["driver_selection_allowed"] is False
    assert {item["model"]["vendor_id"] for item in candidates["candidates"]} == {"huawei"}
    unique = resolve_product_alias_dry_run(DEFAULT_USER, "C9300-48P")
    assert unique["outcome"] == "unique"
    assert unique["selection_allowed"] is True
    assert unique["candidates"][0]["model"]["model_code"] == "C9300-48P"
    unknown = resolve_product_alias_dry_run({"role": "Viewer", "tenant_id": "tenant-other"}, "CE68")
    assert unknown["outcome"] == "unknown"


def test_cat013_filter_and_query_limits_fail_closed():
    with pytest.raises(ProductCatalogError) as invalid:
        list_product_catalog(DEFAULT_USER, status="published")
    assert invalid.value.code == "CATALOG_STATUS_INVALID"
    with pytest.raises(ProductCatalogError) as control:
        list_product_aliases(DEFAULT_USER, alias="CE\n68")
    assert control.value.code == "CATALOG_FILTER_INVALID"
    with pytest.raises(ProductCatalogError) as empty:
        resolve_product_alias_dry_run(DEFAULT_USER, "   ")
    assert empty.value.code == "CATALOG_QUERY_REQUIRED"


def test_cat013_api_contract_is_read_only_until_catalog_migration():
    from api.knowledge_catalog import router

    routes = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert any(path == "/knowledge/catalog" and "GET" in methods for path, methods in routes)
    assert any(path == "/knowledge/catalog/aliases" and "GET" in methods for path, methods in routes)
    assert any(path == "/knowledge/catalog/resolve" and "POST" in methods for path, methods in routes)
    assert not any(path.rstrip("/") == "/knowledge/catalog" and "POST" in methods for path, methods in routes)


def test_cat013_custom_master_data_is_tenant_scoped_audited_and_soft_deletable(isolated_db):
    del isolated_db
    admin = {"id": "catalog-admin", "username": "catalog-admin", "role": "Administrator", "tenant_id": "tenant-custom"}
    viewer = {"id": "catalog-viewer", "username": "catalog-viewer", "role": "Viewer", "tenant_id": "tenant-custom"}
    payload = {
        "vendor_code": "arista",
        "vendor_name": "Arista",
        "family_code": "eos",
        "family_name": "EOS",
        "series_code": "7050",
        "series_name": "7050 Series",
        "model_code": "DCS-7050SX3",
        "display_name": "Arista DCS-7050SX3",
        "status": "active",
        "description": "Tenant-owned switch model",
        "software_scope": {"primary_version": "4.31", "os_family": "EOS"},
        "change_reason": "Add the validated tenant hardware profile",
    }

    created = create_custom_product_model(admin, payload)
    assert created["collection_kind"] == "custom_catalog"
    assert created["mutable"] is True
    assert created["status"] == "active"

    listed = list_product_catalog(admin)
    assert listed["total"] == 1
    assert listed["items"][0]["product_model_id"] == created["product_model_id"]
    assert listed["read_only"] is False
    assert list_product_catalog({**admin, "tenant_id": "tenant-other"})["total"] == 0

    updated = update_custom_product_model(
        admin,
        created["product_model_id"],
        {
            "display_name": "Arista DCS-7050SX3 validated",
            "expected_updated_at": str(created["updated_at"]),
            "change_reason": "Clarify the validated display name",
        },
    )
    assert updated["display_name"].endswith("validated")
    with pytest.raises(ProductCatalogError) as stale:
        update_custom_product_model(
            admin,
            created["product_model_id"],
            {"description": "stale write", "expected_updated_at": str(created["updated_at"])},
        )
    assert stale.value.code == "CATALOG_VERSION_CONFLICT"

    with pytest.raises(ProductCatalogError) as denied:
        create_custom_product_model(viewer, payload | {"model_code": "DCS-7050SX3-VIEWER"})
    assert denied.value.status_code == 403

    deleted = delete_custom_product_model(
        admin,
        created["product_model_id"],
        reason="Retire the tenant profile",
    )
    assert deleted["status"] == "deleted"
    assert list_product_catalog(admin)["total"] == 0
    deleted_view = list_product_catalog(admin, status="deleted")
    assert deleted_view["total"] == 1
    assert deleted_view["items"][0]["status"] == "deleted"

    from database import get_db_connection

    with get_db_connection() as connection:
        audit_count = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE category = ? AND target_id = ?",
            ("knowledge_catalog", created["product_model_id"]),
        ).fetchone()[0]
    assert audit_count == 3


def test_cat013_official_master_data_remains_immutable(isolated_db):
    del isolated_db
    admin = {"id": "catalog-admin", "username": "catalog-admin", "role": "Administrator", "tenant_id": "tenant-default"}
    official = list_product_catalog(admin)["items"][0]
    with pytest.raises(ProductCatalogError) as duplicate_error:
        create_custom_product_model(
            admin,
            {
                "vendor_code": official["vendor_id"],
                "vendor_name": official["vendor_name"],
                "family_code": official["family_code"],
                "family_name": official["family_name"],
                "series_code": official["series_code"],
                "series_name": official["series_name"],
                "model_code": official["model_code"],
                "display_name": "Duplicate official model",
            },
        )
    assert duplicate_error.value.code == "CATALOG_MODEL_DUPLICATE"
    with pytest.raises(ProductCatalogError) as update_error:
        update_custom_product_model(admin, official["product_model_id"], {"display_name": "Should not change"})
    assert update_error.value.code == "CATALOG_OFFICIAL_READ_ONLY"
    with pytest.raises(ProductCatalogError) as delete_error:
        delete_custom_product_model(admin, official["product_model_id"])
    assert delete_error.value.code == "CATALOG_OFFICIAL_READ_ONLY"
