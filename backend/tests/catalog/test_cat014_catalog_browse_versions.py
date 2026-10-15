from __future__ import annotations

import inspect

import pytest

from services.product_catalog_service import ProductCatalogError, list_product_catalog


DEFAULT_USER = {"id": "viewer-1", "role": "Viewer", "tenant_id": "tenant-default-reviewed"}


def test_cat014_browse_filters_cover_vendor_family_series_model_and_version():
    assert list_product_catalog(DEFAULT_USER, vendor_id="huawei")["total"] == 3
    assert list_product_catalog(DEFAULT_USER, family_code="catalyst_9300")["total"] == 3
    assert list_product_catalog(DEFAULT_USER, series_code="c9300", model="48p")["items"][0]["model_code"] == "C9300-48P"
    versioned = list_product_catalog(DEFAULT_USER, software_version="17.9.x")
    assert versioned["total"] == 3
    assert {item["vendor_id"] for item in versioned["items"]} == {"cisco"}
    assert list_product_catalog(DEFAULT_USER, software_version="V300R024C10SPC500")["total"] == 3


def test_cat014_hierarchy_is_a_bounded_vendor_family_series_model_index():
    result = list_product_catalog(DEFAULT_USER)

    hierarchy = result["facets"]["hierarchy"]
    assert {item["vendor_id"] for item in hierarchy} == {"cisco", "h3c", "huawei", "ruijie"}
    assert all(set(item) == {"vendor_id", "vendor_name", "model_count", "families"} for item in hierarchy)

    cisco = next(item for item in hierarchy if item["vendor_id"] == "cisco")
    family = next(item for item in cisco["families"] if item["family_code"] == "catalyst_9300")
    series = next(item for item in family["series"] if item["series_code"] == "c9300")
    model = next(item for item in series["models"] if item["model_code"] == "C9300-48P")

    assert cisco["model_count"] == family["model_count"] == series["model_count"] == 3
    assert model == {
        "product_model_id": "cisco:catalyst_9300:c9300:c9300-48p",
        "model_code": "C9300-48P",
        "display_name": "Catalyst C9300-48P",
        "status": "draft",
    }
    assert "source_artifact" not in model
    assert "software_scope" not in model


def test_cat014_version_filter_is_exact_and_org_wide():
    assert list_product_catalog(DEFAULT_USER, software_version="17.9")["total"] == 0
    assert list_product_catalog({"role": "Viewer", "tenant_id": "tenant-other"}, software_version="17.9.x")["total"] == 3


def test_cat014_invalid_version_filter_fails_closed():
    with pytest.raises(ProductCatalogError) as invalid:
        list_product_catalog(DEFAULT_USER, software_version="17\n9.x")
    assert invalid.value.code == "CATALOG_FILTER_INVALID"


def test_cat014_api_contract_exposes_version_query_without_write_route():
    from api.knowledge_catalog import api_list_catalog, router

    assert "software_version" in inspect.signature(api_list_catalog).parameters
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert any(path == "/knowledge/catalog" and "GET" in methods for path, methods in routes)
    assert not any(path.rstrip("/") == "/knowledge/catalog" and "POST" in methods for path, methods in routes)
