from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-core-er-model.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db002_canonical_types_and_write_rules_are_explicit():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-002"
    assert data["status"] == "frozen_for_implementation"
    assert data["authority"] == "PostgreSQL"
    expected = {
        "id": ("uuid", False),
        "tenant_id": ("uuid", False),
        "created_at": ("timestamptz", False),
        "updated_at": ("timestamptz", False),
        "created_by": ("uuid", False),
        "updated_by": ("uuid", False),
        "status": ("text", False),
    }
    for name, (canonical_type, nullable) in expected.items():
        field = data["columns"][name]
        assert field["canonical_type"] == canonical_type
        assert field["nullable"] is nullable
        assert field["semantics"]
    assert "server_or_database_default_only; immutable_after_insert" == data["columns"]["created_at"]["write_rule"]
    assert "unknown_behavior" in data["columns"]["status"]


def test_db002_scope_covers_every_db001_tenant_entity():
    db001 = _load(ER_CONTRACT)
    db002 = _load(CONTRACT)
    entity_names = {entity["name"] for entity in db001["entities"]}
    scoped_names = set(db002["scope_matrix"]["tenant_scoped_entities"])
    assert entity_names == scoped_names
    assert db002["scope_matrix"]["global_reference_entities"] == []
    assert "tenant_id_is_in_every_primary_scope_and_authorization_predicate" in db002["common_invariants"]


def test_db002_legacy_gaps_are_recorded_without_claiming_migration():
    data = _load(CONTRACT)
    gaps = data["legacy_gap_audit"]
    for table in ("ai_provider", "ai_model", "ai_model_route", "ai_knowledge_base", "ai_document", "ai_document_chunk", "ai_knowledge_reindex_job"):
        assert gaps[table]["observed"]
        assert gaps[table]["action"]
    assert "tenant-default" in data["legacy_mode"]
    assert "production_postgresql_snapshot_and_schema_revision_available" in data["constraints_before_migration"]


def test_db002_report_has_security_migration_and_rollback_evidence():
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-002", "UUID", "tenant_id", "created_at", "updated_at", "created_by", "status", "PostgreSQL", "回滚", "V1", "PASS"):
        assert marker in report, marker
