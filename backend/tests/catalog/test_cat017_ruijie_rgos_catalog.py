from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "docs" / "knowledge-engine" / "catalog" / "CAT-017-RUIJIE-RGOS.yaml"
BASE_ALLOWLIST = ROOT / "docs" / "knowledge-engine" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_cat017_freezes_ruijie_s6220_hierarchy_and_unique_model_samples():
    data = _load(SAMPLE)
    assert data["task_id"] == "CAT-017"
    assert data["status"] == "reviewed_sample_pending_source_allowlist_and_catalog_migration"
    assert data["vendor"]["vendor_id"] == "ruijie"
    family = data["product_family"]
    series = family["product_series"][0]
    models = series["model_samples"]
    assert family["code"] == "rg_s6220"
    assert series["code"] == "s6220"
    assert len(models) == 3
    codes = [item["model_code"] for item in models]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(series["model_code_rule"], code) for code in codes)
    assert all(item["status"] == "draft" for item in models)


def test_cat017_rgos11_train_and_versions_are_orthogonal_and_valid():
    data = _load(SAMPLE)
    assert data["software_scope"]["primary_version"] == "RGOS 11.0(5)B9P59"
    assert data["software_scope"]["compatibility_version"] == "RGOS 11.0(5)B3P2"
    assert data["software_scope"]["software_train"] == "RGOS 11.0(5)"
    assert data["os_family"]["code"] == "rgos"
    generation = data["os_family"]["generations"][0]
    assert generation["code"] == "rgos11"
    train = generation["release_trains"][0]
    assert train["code"] == "rgos_11_0_5"
    versions = train["software_versions"]
    assert len({item["normalized_version"] for item in versions}) == 3
    for version in versions:
        assert re.fullmatch(train["version_pattern"], version["original_version_string"])
        assert version["normalized_version"] == version["original_version_string"].lower()
        assert version["status"] == "draft"


def test_cat017_platform_mapping_matches_ruijie_driver_and_parser_boundary():
    data = _load(SAMPLE)
    binding = data["platform_binding_advisory"]
    mapping = data["os_family"]["generations"][0]["explicit_platform_mappings"][0]
    assert binding["platform_code"] == "ruijie_rgos"
    assert binding["connection_driver"] == "ruijie_os"
    assert binding["parser_platform"] == "ruijie_rgos"
    assert binding["driver_authority"] is False
    assert binding["execution_write_authority"] is False
    assert mapping["cli_platform"] == "ruijie_rgos"
    assert mapping["connection_driver"] == "ruijie_os"
    assert mapping["parser_platform"] == "ruijie_rgos"
    assert mapping["driver_authority"] is False
    assert "parser_from_version" in binding["forbidden_inference"]


def test_cat017_sources_are_exact_ruijie_evidence_and_not_live_allowlist_entries():
    data = _load(SAMPLE)
    base = _load(BASE_ALLOWLIST)
    assert {item["vendor"] for item in base["vendor_entries"]} == {"Huawei", "Cisco"}
    assert data["source_allowlist"]["status"] == "pending_CAT001_additive_extension"
    assert data["source_allowlist"]["collection_activation"] == "forbidden_until_CAT001_CAT003_CAT004_review"
    for source in data["source_refs"]:
        parsed = urlsplit(source["url"])
        assert parsed.scheme == "https"
        assert parsed.hostname == "www.ruijie.com.cn"
        assert parsed.port in (None, 443)
        assert parsed.username is None and parsed.password is None
        assert parsed.query == ""
        assert parsed.fragment == ""
        assert parsed.path.startswith(source["path_scope"])
        assert source["url"].startswith("https://www.ruijie.com.cn/")


def test_cat017_resolution_unknown_legacy_and_rollback_fail_closed():
    data = _load(SAMPLE)
    rules = data["identity_rules"]
    assert rules["model_resolution"]["full_model_code_required_for_unique_identity"] is True
    assert rules["model_resolution"]["partial_prefix_result"] == "candidate_list_and_clarification"
    assert rules["model_resolution"]["unknown_model_result"] == "UNKNOWN_and_no_vendor_or_driver_guess"
    assert data["version_rules"]["unknown_version"] == "UNKNOWN_and_require_source_or_clarification"
    assert data["unknown_and_legacy_policy"]["never_rewrite_original"] is True
    gate = data["activation_gate"]
    assert "additive_Ruijie_source_allowlist_review" in gate["required_before_active"]
    assert data["rollback"]["production_ddl"] == "none_in_CAT-017"
    assert data["rollback"]["data"] == "retain_reviewed_seed_artifact_and_all_v1_metadata"


def test_cat017_product_adapter_exposes_org_wide_ruijie_seed_and_exact_version():
    from services.product_catalog_service import ProductCatalogError, list_product_catalog

    default_user = {"id": "cat017-viewer", "role": "Viewer", "tenant_id": "tenant-default-reviewed"}
    ruijie = list_product_catalog(default_user, vendor_id="ruijie")
    assert ruijie["total"] == 3
    assert {item["vendor_id"] for item in ruijie["items"]} == {"ruijie"}
    assert {item["platform_binding_advisory"]["platform_code"] for item in ruijie["items"]} == {"ruijie_rgos"}
    versioned = list_product_catalog(default_user, software_version="RGOS 11.0(5)B9P59")
    assert versioned["total"] == 3
    assert {item["vendor_id"] for item in versioned["items"]} == {"ruijie"}
    assert list_product_catalog({"role": "Viewer", "tenant_id": "tenant-other"}, vendor_id="ruijie")["total"] == 3
    with pytest.raises(ProductCatalogError) as invalid:
        list_product_catalog(default_user, software_version="RGOS\n11.0(5)B9P59")
    assert invalid.value.code == "CATALOG_FILTER_INVALID"
