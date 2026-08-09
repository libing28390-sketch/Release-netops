from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "docs" / "knowledge-engine-v2" / "catalog" / "CAT-006-CISCO-C9300.yaml"
CAT001 = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _allowlisted_urls() -> set[str]:
    data = _load(CAT001)
    return {
        str(url)
        for vendor in data["vendor_entries"]
        if vendor["vendor"] == "Cisco"
        for host in vendor["official_hosts"]
        for url in host["source_urls"]
    }


def test_cat006_freezes_cisco_catalyst_hierarchy_and_unique_model_samples():
    data = _load(SAMPLE)
    assert data["task_id"] == "CAT-006"
    assert data["status"] == "reviewed_sample_pending_catalog_migration"
    assert data["vendor"]["vendor_id"] == "cisco"
    family = data["product_family"]
    series = family["product_series"][0]
    models = series["model_samples"]
    assert family["code"] == "catalyst_9300"
    assert series["code"] == "c9300"
    assert len(models) >= 3
    codes = [item["model_code"] for item in models]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(series["model_code_rule"], code) for code in codes)
    assert all(item["status"] == "draft" for item in models)


def test_cat006_sources_stay_inside_cat001_cisco_allowlist():
    data = _load(SAMPLE)
    allowlisted = _allowlisted_urls()
    for source in data["source_refs"]:
        parsed = urlsplit(source["url"])
        assert source["url"] in allowlisted
        assert parsed.scheme == "https"
        assert parsed.hostname == "www.cisco.com"
        assert parsed.query == ""
        assert parsed.fragment == ""
        assert parsed.username is None and parsed.password is None
        assert parsed.path.startswith(source["path_scope"])


def test_cat006_keeps_software_and_driver_orthogonal_and_fail_closed():
    data = _load(SAMPLE)
    scope = data["software_scope"]
    binding = data["platform_binding_advisory"]
    rules = data["identity_rules"]
    assert scope["primary_version"] == "17.9.x"
    assert scope["compatibility_version"] == "17.18.x"
    assert scope["os_family"] == "IOS-XE"
    assert binding["driver_authority"] is False
    assert binding["execution_write_authority"] is False
    assert rules["model_resolution"]["full_model_code_required_for_unique_identity"] is True
    assert rules["model_resolution"]["partial_prefix_result"] == "candidate_list_and_clarification"
    assert rules["model_resolution"]["unknown_model_result"] == "UNKNOWN_and_no_vendor_or_driver_guess"


def test_cat006_activation_and_rollback_do_not_create_production_ddl():
    data = _load(SAMPLE)
    gate = data["activation_gate"]
    assert gate["catalog_rows"] == "reviewed_seed_only_until_DB006_migration"
    assert "duplicate_and_ambiguous_model_report" in gate["required_before_active"]
    assert data["rollback"]["production_ddl"] == "none_in_CAT-006"
    assert data["rollback"]["data"] == "retain_reviewed_seed_artifact_and_all_v1_metadata"
