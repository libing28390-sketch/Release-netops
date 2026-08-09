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


def test_cat014_version_filter_is_exact_and_tenant_scoped():
    assert list_product_catalog(DEFAULT_USER, software_version="17.9")["total"] == 0
    assert list_product_catalog({"role": "Viewer", "tenant_id": "tenant-other"}, software_version="17.9.x")["total"] == 0


def test_cat014_invalid_version_filter_fails_closed():
    with pytest.raises(ProductCatalogError) as invalid:
        list_product_catalog(DEFAULT_USER, software_version="17\n9.x")
    assert invalid.value.code == "CATALOG_FILTER_INVALID"


def test_cat014_api_contract_exposes_version_query_without_write_route():
    from api.knowledge_catalog import api_list_catalog, router

    assert "software_version" in inspect.signature(api_list_catalog).parameters
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert any(path == "/knowledge-v2/catalog" and "GET" in methods for path, methods in routes)
    assert not any(path.rstrip("/") == "/knowledge-v2/catalog" and "POST" in methods for path, methods in routes)
