from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "docs" / "knowledge-engine" / "catalog" / "CAT-008-CISCO-OS-BOUNDARY.yaml"


def _load() -> dict:
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


def test_cat008_freezes_four_cisco_os_boundaries():
    data = _load()
    assert data["task_id"] == "CAT-008"
    assert [item["code"] for item in data["os_families"]] == ["ios", "ios_xe", "nx_os", "ios_xr"]
    by_code = {item["code"]: item for item in data["os_families"]}
    assert by_code["ios"]["c9300_applicability"] == "forbidden"
    assert by_code["ios_xe"]["c9300_applicability"] == "supported"
    assert by_code["nx_os"]["c9300_applicability"] == "forbidden"
    assert by_code["ios_xr"]["c9300_applicability"] == "forbidden"
    for item in data["os_families"]:
        assert re.fullmatch(item["version_pattern"], {"ios": "15.7(3)M", "ios_xe": "17.9.4", "nx_os": "9.3.8", "ios_xr": "7.5.2"}[item["code"]])


def test_cat008_maps_c9300_only_to_explicit_ios_xe_scope():
    data = _load()
    relation = data["product_applicability"]
    assert relation["vendor_required"] == "cisco"
    assert relation["product_series"] == "c9300"
    assert relation["supported_os_family"] == "ios_xe"
    assert relation["supported_version_scope"] == ["17.9.x", "17.18.x"]
    assert relation["supported_platform_mapping"] == "cisco_ios"
    assert set(relation["forbidden_os_families"]) == {"ios", "nx_os", "ios_xr"}
    assert relation["unknown_os_behavior"] == "candidate_list_and_clarification"


def test_cat008_driver_and_legacy_boundaries_are_fail_closed():
    data = _load()
    mappings = {item["code"]: item["explicit_platform_mapping"] for item in data["os_families"]}
    assert mappings["ios_xe"]["platform_code"] == "cisco_ios"
    assert mappings["ios_xe"]["accepted_aliases"] == ["cisco_iosxe", "cisco_xe"]
    assert mappings["nx_os"]["platform_code"] == "cisco_nxos"
    assert mappings["ios_xr"]["platform_code"] == "cisco_iosxr"
    assert all(item["driver_authority"] is False for item in mappings.values())
    assert data["legacy_compatibility"]["no_original_rewrite"] is True
    assert data["resolution_boundary"]["rules"]["c9300_without_os_family"] == "series_candidate_only_and_clarify"
    assert data["resolution_boundary"]["rules"]["no_first_match_fallback"] is True


def test_cat008_activation_and_rollback_do_not_create_production_ddl():
    data = _load()
    assert data["activation_gate"]["catalog_rows"] == "reviewed_boundary_only_until_DB007_migration"
    assert "c9300_applicability_evidence" in data["activation_gate"]["required_before_active"]
    assert data["rollback"]["production_ddl"] == "none_in_CAT-008"
