from __future__ import annotations

import pytest

from services.product_catalog_service import (
    ProductCatalogError,
    list_product_aliases,
    list_product_catalog,
    resolve_product_alias_dry_run,
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
    assert any(path == "/knowledge-v2/catalog" and "GET" in methods for path, methods in routes)
    assert any(path == "/knowledge-v2/catalog/aliases" and "GET" in methods for path, methods in routes)
    assert any(path == "/knowledge-v2/catalog/resolve" and "POST" in methods for path, methods in routes)
    assert not any(path.rstrip("/") == "/knowledge-v2/catalog" and "POST" in methods for path, methods in routes)
