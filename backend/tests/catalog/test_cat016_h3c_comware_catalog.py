from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "docs" / "knowledge-engine" / "catalog" / "CAT-016-H3C-COMWARE.yaml"
BASE_ALLOWLIST = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_cat016_freezes_h3c_s6520x_hierarchy_and_unique_model_samples():
    data = _load(SAMPLE)
    assert data["task_id"] == "CAT-016"
    assert data["status"] == "reviewed_sample_pending_source_allowlist_and_catalog_migration"
    assert data["vendor"]["vendor_id"] == "h3c"
    family = data["product_family"]
    series = family["product_series"][0]
    models = series["model_samples"]
    assert family["code"] == "s6520x"
    assert series["code"] == "s6520x_ei"
    assert len(models) == 3
    codes = [item["model_code"] for item in models]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(series["model_code_rule"], code) for code in codes)
    assert all(item["status"] == "draft" for item in models)


def test_cat016_comware7_train_and_versions_are_orthogonal_and_valid():
    data = _load(SAMPLE)
    assert data["software_scope"]["primary_version"] == "CMW710-R6823"
    assert data["software_scope"]["compatibility_version"] == "CMW710-R6820"
    assert data["software_scope"]["software_train"] == "CMW710"
    assert data["os_family"]["code"] == "comware"
    generation = data["os_family"]["generations"][0]
    assert generation["code"] == "comware7"
    train = generation["release_trains"][0]
    assert train["code"] == "cmw710"
    versions = train["software_versions"]
    assert len({item["normalized_version"] for item in versions}) == 3
    for version in versions:
        assert re.fullmatch(train["version_pattern"], version["original_version_string"])
        assert version["normalized_version"] == version["original_version_string"].lower()
        assert version["status"] == "draft"


def test_cat016_platform_mapping_matches_h3c_driver_and_parser_boundary():
    data = _load(SAMPLE)
    binding = data["platform_binding_advisory"]
    mapping = data["os_family"]["generations"][0]["explicit_platform_mappings"][0]
    assert binding["platform_code"] == "h3c_comware"
    assert binding["connection_driver"] == "hp_comware"
    assert binding["parser_platform"] == "h3c_comware"
    assert binding["driver_authority"] is False
    assert binding["execution_write_authority"] is False
    assert mapping["cli_platform"] == "h3c_comware"
    assert mapping["connection_driver"] == "hp_comware"
    assert mapping["parser_platform"] == "h3c_comware"
    assert mapping["driver_authority"] is False
    assert "parser_from_version" in binding["forbidden_inference"]


def test_cat016_sources_are_exact_h3c_evidence_and_not_live_allowlist_entries():
    data = _load(SAMPLE)
    base = _load(BASE_ALLOWLIST)
    assert {item["vendor"] for item in base["vendor_entries"]} == {"Huawei", "Cisco"}
    assert data["source_allowlist"]["status"] == "pending_CAT001_additive_extension"
    assert data["source_allowlist"]["collection_activation"] == "forbidden_until_CAT001_CAT003_CAT004_review"
    for source in data["source_refs"]:
        parsed = urlsplit(source["url"])
        assert parsed.scheme == "https"
        assert parsed.hostname == "www.h3c.com"
        assert parsed.port in (None, 443)
        assert parsed.username is None and parsed.password is None
        assert parsed.query == ""
        assert parsed.fragment == ""
        assert parsed.path.startswith(source["path_scope"])
        assert source["url"].startswith("https://www.h3c.com/")


def test_cat016_resolution_unknown_legacy_and_rollback_fail_closed():
    data = _load(SAMPLE)
    rules = data["identity_rules"]
    assert rules["model_resolution"]["full_model_code_required_for_unique_identity"] is True
    assert rules["model_resolution"]["partial_prefix_result"] == "candidate_list_and_clarification"
    assert rules["model_resolution"]["unknown_model_result"] == "UNKNOWN_and_no_vendor_or_driver_guess"
    assert data["version_rules"]["unknown_version"] == "UNKNOWN_and_require_source_or_clarification"
    assert data["unknown_and_legacy_policy"]["never_rewrite_original"] is True
    gate = data["activation_gate"]
    assert "additive_H3C_source_allowlist_review" in gate["required_before_active"]
    assert data["rollback"]["production_ddl"] == "none_in_CAT-016"
    assert data["rollback"]["data"] == "retain_reviewed_seed_artifact_and_all_v1_metadata"


def test_cat016_product_adapter_exposes_org_wide_h3c_seed_and_exact_version():
    from services.product_catalog_service import ProductCatalogError, list_product_catalog

    default_user = {"id": "cat016-viewer", "role": "Viewer", "tenant_id": "tenant-default-reviewed"}
    h3c = list_product_catalog(default_user, vendor_id="h3c")
    assert h3c["total"] == 3
    assert {item["vendor_id"] for item in h3c["items"]} == {"h3c"}
    assert {item["platform_binding_advisory"]["platform_code"] for item in h3c["items"]} == {"h3c_comware"}
    versioned = list_product_catalog(default_user, software_version="CMW710-R6823")
    assert versioned["total"] == 3
    assert {item["vendor_id"] for item in versioned["items"]} == {"h3c"}
    assert list_product_catalog({"role": "Viewer", "tenant_id": "tenant-other"}, vendor_id="h3c")["total"] == 3
    with pytest.raises(ProductCatalogError) as invalid:
        # Control characters must never become a catalog filter or lookup key.
        list_product_catalog(default_user, software_version="CMW710\nR6823")
    assert invalid.value.code == "CATALOG_FILTER_INVALID"
