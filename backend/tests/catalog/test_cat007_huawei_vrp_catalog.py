from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[3]
SAMPLE = ROOT / "docs" / "knowledge-engine-v2" / "catalog" / "CAT-007-HUAWEI-VRP.yaml"
CAT001 = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "CAT-001-OFFICIAL-SOURCE-ALLOWLIST.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _allowlisted_urls() -> set[str]:
    data = _load(CAT001)
    return {
        str(url)
        for vendor in data["vendor_entries"]
        if vendor["vendor"] == "Huawei"
        for host in vendor["official_hosts"]
        for url in host["source_urls"]
    }


def test_cat007_freezes_vrp_family_generations_trains_and_versions():
    data = _load(SAMPLE)
    assert data["task_id"] == "CAT-007"
    assert data["status"] == "reviewed_sample_pending_os_catalog_migration"
    assert data["vendor"]["vendor_id"] == "huawei"
    family = data["os_family"]
    assert family["code"] == "vrp"
    generations = {item["code"]: item for item in family["generations"]}
    assert set(generations) == {"vrp5", "vrp8"}
    trains = [train for generation in generations.values() for train in generation["release_trains"]]
    assert {train["code"] for train in trains} == {"v200", "v300"}
    versions = [version for train in trains for version in train["software_versions"]]
    assert len({version["normalized_version"] for version in versions}) == len(versions)
    for train in trains:
        for version in train["software_versions"]:
            assert re.fullmatch(train["version_pattern"], version["original_version_string"])
            assert version["normalized_version"] == version["original_version_string"].lower()
            assert version["status"] == "draft"


def test_cat007_sources_stay_inside_cat001_huawei_allowlist():
    data = _load(SAMPLE)
    allowlisted = _allowlisted_urls()
    for source in data["source_refs"]:
        parsed = urlsplit(source["url"])
        assert source["url"] in allowlisted
        assert parsed.scheme == "https"
        assert parsed.hostname in {"support.huawei.com", "info.support.huawei.com"}
        assert parsed.query == ""
        assert parsed.fragment == ""
        assert parsed.username is None and parsed.password is None
        assert parsed.path.startswith(source["path_scope"])


def test_cat007_unknown_and_legacy_rules_fail_closed_without_driver_inference():
    data = _load(SAMPLE)
    rules = data["resolution_rules"]
    assert rules["generation_resolution"]["bare_vrp"] == "candidate_list_and_clarification"
    assert rules["train_resolution"]["V600"] == "out_of_first_batch_preserve_v1_value_and_require_review"
    assert rules["version_resolution"]["unknown_version"] == "UNKNOWN_and_require_source_or_clarification"
    assert rules["platform_resolution"]["rule"] == "explicit_reviewed_mapping_only"
    assert "infer_cli_platform_or_driver_from_version_or_train" in rules["platform_resolution"]["forbidden"]
    assert data["unknown_and_legacy_policy"]["never_rewrite_original"] is True


def test_cat007_activation_and_rollback_do_not_create_production_ddl():
    data = _load(SAMPLE)
    gate = data["activation_gate"]
    assert gate["catalog_rows"] == "reviewed_seed_only_until_DB007_migration"
    assert "version_scheme_validation" in gate["required_before_active"]
    assert data["rollback"]["production_ddl"] == "none_in_CAT-007"
