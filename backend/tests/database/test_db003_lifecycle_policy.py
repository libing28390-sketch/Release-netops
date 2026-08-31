from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-003-LIFECYCLE-POLICY.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-003-LIFECYCLE-BEHAVIOR.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-001-core-er-model.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db003_declares_four_distinct_lifecycle_behaviors():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-003"
    assert data["status"] == "frozen_for_implementation"
    behaviors = data["behaviors"]
    assert set(behaviors) == {"soft_delete", "disable", "archive", "purge"}
    assert behaviors["soft_delete"]["status"] == "deleted"
    assert behaviors["disable"]["status"] == "disabled"
    assert behaviors["archive"]["status"] == "archived"
    assert behaviors["purge"]["status"] == "purged"
    assert behaviors["soft_delete"]["reversible"] is True
    assert behaviors["disable"]["reversible"] is True
    assert behaviors["archive"]["reversible"] is True
    assert behaviors["purge"]["reversible"] is False
    for behavior in behaviors.values():
        assert behavior["permission"]
        assert behavior["preconditions"]
        assert behavior["required_fields"]
        assert behavior["rollback"]


def test_db003_state_machine_has_safe_terminal_and_no_implicit_active_restore():
    data = _load(CONTRACT)
    states = set(data["state_values"])
    assert set(data["terminal_states"]) == {"purged"}
    for transition in data["transitions"]:
        assert transition["from"] in states
        assert transition["to"] in states
        assert transition["permission"]
    assert {t["from"] for t in data["transitions"] if t["to"] == "purged"} == {"deleted", "purged"}
    assert any(t["from"] == "purged" and t["to"] == "purged" for t in data["transitions"])
    assert not any(t["from"] == "purged" and t["to"] != "purged" for t in data["transitions"])
    assert data["behaviors"]["purge"]["rollback"].startswith("forbidden")


def test_db003_policies_cover_db001_entities_and_require_tenant_audit_controls():
    data = _load(CONTRACT)
    db001 = _load(ER_CONTRACT)
    entity_names = {entity["name"] for entity in db001["entities"]}
    policy_names = set()
    for policy in data["entity_policies"].values():
        policy_names.update(policy["entities"])
        assert policy["allowed"]
        assert policy["purge_rule"]
    assert policy_names <= entity_names
    audit = data["concurrency_and_audit"]
    assert "tenant_id" in audit["compare_and_set"]
    assert audit["idempotency"]
    assert audit["audit_event"]
    assert data["security"]["purge"]


def test_db003_report_records_visibility_security_and_irreversible_boundary():
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-003", "软删除", "禁用", "归档", "净化删除", "purged", "V1", "回滚", "PASS"):
        assert marker in report, marker
