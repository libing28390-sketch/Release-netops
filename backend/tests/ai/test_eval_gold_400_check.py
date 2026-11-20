from __future__ import annotations

import sys
import hashlib
from pathlib import Path

import yaml

scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from knowledge_eval_gold_400_check import validate_dataset


def _case(case_id: int, *, category: str, vendor: str, split: str, secondary: bool = False) -> dict:
    source = {
        "Huawei": ("local.huawei.huawei_vrp.vlan.v1", "https://info.support.huawei.com/enterprise/en/doc/EDOC1100419268/221a9cda/configuration-examples-for-vlans"),
        "Cisco": ("local.cisco.cisco_iosxe.vlan.v1", "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf"),
        "H3C": ("local.h3c.h3c_comware.vlan.v1", "https://www.h3c.com/en/d_201905/1189999_294551_0.htm"),
        "Ruijie": ("local.ruijie.ruijie_rgos.vlan.v1", "https://www.ruijie.com.cn/fw/wt/18515/"),
        "cross_vendor_or_unknown": ("local.cisco.cisco_iosxe.vlan.v1", "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9400/software/release/17-3/configuration_guide/vlan/b_173_vlan_9400_cg.pdf"),
    }[vendor]
    document_id, source_url = source
    value = {
        "id": f"GOLD400-{case_id:03d}",
        "query": f"synthetic network query {case_id}",
        "category": category,
        "vendor": vendor,
        "platform": "synthetic_platform",
        "feature": "vlan",
        "expected_outcome": "answer",
        "gold_document_ids": [document_id],
        "acceptable_document_ids": [],
        "citation_required": True,
        "risk_level": "low",
        "split": split,
        "golden_answer": "Use the reviewed synthetic evidence and verify the result.",
        "source_evidence": [{"document_id": document_id, "locator": "official-page:feature=vlan", "url": source_url, "source_type": "official_vendor_documentation"}],
        "annotator": "annotator-a",
        "reviewer": "reviewer-a",
        "reviewed_at": "2026-09-03T00:00:00Z",
        "annotation_status": "approved",
    }
    if secondary:
        value["secondary_reviewer"] = "reviewer-b"
    if category in {"knowledge_config_reference", "troubleshooting", "configuration_validation_diagnostic", "tool_call_dangerous_operation"}:
        value.update({"domain_reviewed": True, "domain_reviewer": "domain-reviewer", "domain_reviewed_at": "2026-09-03T00:00:00Z"})
    return value


def _write_dataset(tmp_path: Path, cases: list[dict]) -> Path:
    path = tmp_path / "eval-golden-400.yaml"
    manifest_path = Path(__file__).resolve().parents[3] / "data" / "kb_import" / "manifest.json"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "dataset_id": "nexora-kb-eval-gold-400-v1-20260903",
                "status": "frozen",
                "case_count": len(cases),
                "synthetic_data": True,
                "production_eligible": False,
                "test_only": True,
                "source_policy": {
                    "database": "PostgreSQL",
                    "external_network": "forbidden",
                    "secrets": "forbidden",
                    "production_data": "forbidden",
                    "official_sources": "required",
                    "source_collection": "official_url_backed_local_summary",
                },
                "collection": {
                    "mode": "official_url_backed_local_summary",
                    "source_manifest": "data/kb_import/manifest.json",
                    "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    "collected_at": "2026-09-05",
                    "content_origin": "local_summary_derived_from_official_pages",
                    "human_review_required": False,
                },
                "coverage": {"train_debug_hidden": {"train": 240, "debug": 80, "hidden": 80}},
                "review_policy": {
                    "human_review_required": False,
                    "minimum_double_review_cases": 0,
                    "review_mode": "official_source_provenance_automated",
                },
                "cases": cases,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_gold_400_contract_accepts_complete_distribution(tmp_path: Path) -> None:
    categories = (
        ["knowledge_config_reference"] * 140
        + ["troubleshooting"] * 70
        + ["configuration_validation_diagnostic"] * 50
        + ["asset_alarm_query"] * 40
        + ["intent_clarification_missing_parameter"] * 40
        + ["tool_call_dangerous_operation"] * 30
        + ["negative_security_no_match"] * 30
    )
    vendors = (["Huawei"] * 100 + ["Cisco"] * 100 + ["H3C"] * 80 + ["Ruijie"] * 60 + ["cross_vendor_or_unknown"] * 60)
    splits = ["train"] * 240 + ["debug"] * 80 + ["hidden"] * 80
    cases = [_case(i + 1, category=categories[i], vendor=vendors[i], split=splits[i], secondary=i < 80) for i in range(400)]
    report = validate_dataset(_write_dataset(tmp_path, cases))
    assert report["status"] == "PASS", report
    assert report["case_count"] == 400
    assert report["double_review_count"] == 0
    assert report["human_review_required"] is False
    assert report["official_source_evidence_case_count"] == 400


def test_gold_400_contract_rejects_secret_without_requiring_review(tmp_path: Path) -> None:
    case = _case(1, category="negative_security_no_match", vendor="cross_vendor_or_unknown", split="hidden")
    case.pop("reviewer")
    case.pop("reviewed_at")
    case.pop("annotation_status")
    case["risk_level"] = "unclassified"
    case["query"] = "api_key=fixture-secret"
    report = validate_dataset(_write_dataset(tmp_path, [case]))
    assert report["status"] == "FAIL"
    assert report["error_count"] > 0
    assert not any("human-approved" in error for error in report["errors"])
    assert any("secret-like" in error for error in report["errors"])
    assert any("risk_level is invalid" in error for error in report["errors"])


def test_gold_400_contract_rejects_review_policy_drift(tmp_path: Path) -> None:
    case = _case(1, category="negative_security_no_match", vendor="cross_vendor_or_unknown", split="hidden")
    path = _write_dataset(tmp_path, [case])
    dataset = yaml.safe_load(path.read_text(encoding="utf-8"))
    dataset["review_policy"]["human_review_required"] = True
    path.write_text(yaml.safe_dump(dataset, allow_unicode=True, sort_keys=False), encoding="utf-8")

    report = validate_dataset(path)

    assert report["status"] == "FAIL"
    assert any("human_review_required must be false" in error for error in report["errors"])


def test_gold_400_contract_is_not_ready_without_real_dataset(tmp_path: Path) -> None:
    report = validate_dataset(tmp_path / "missing.yaml")
    assert report["status"] == "NOT_READY"


def test_gold_400_test_fixture_is_rejected_by_production_gate(tmp_path: Path) -> None:
    case = _case(
        1,
        category="negative_security_no_match",
        vendor="cross_vendor_or_unknown",
        split="hidden",
    )
    path = _write_dataset(tmp_path, [case])
    dataset = yaml.safe_load(path.read_text(encoding="utf-8"))
    dataset["test_only"] = True
    path.write_text(yaml.safe_dump(dataset, allow_unicode=True, sort_keys=False), encoding="utf-8")

    report = validate_dataset(path, require_production=True)

    assert report["status"] == "FAIL"
    assert any("test-only dataset" in error for error in report["errors"])
