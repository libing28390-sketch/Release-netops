from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-core-er-model.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-CORE-ER-MODEL.md"


def _contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_db001_contract_freezes_authority_and_naming():
    data = _contract()
    assert data["task_id"] == "DB-001"
    assert data["status"] == "frozen_for_implementation"
    assert data["authority"]["production_database"] == "PostgreSQL"
    assert data["authority"]["local_test_database"] == "SQLite_compatibility_only"
    naming = data["naming"]
    assert naming["table_case"] == "lower_snake_case"
    assert naming["primary_key"] == "id"
    assert naming["foreign_key"] == "referenced_entity_id"
    assert naming["tenant_key"] == "tenant_id"
    assert naming["created_timestamp"] == "created_at"
    assert naming["updated_timestamp"] == "updated_at"
    assert "camelCase" in naming["forbidden_names"]


def test_db001_entities_have_common_scope_and_no_dangling_foreign_keys():
    data = _contract()
    entities = data["entities"]
    entity_names = {entity["name"] for entity in entities}
    assert len(entity_names) == len(entities)
    common = {column["name"] for column in data["common_columns"]}
    required_common = {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"}
    assert required_common <= common
    for entity in entities:
        assert required_common <= set(entity["required_columns"]), entity["name"]
        for foreign_key in entity.get("foreign_keys", []):
            target = foreign_key.split("->", 1)[1].strip().rsplit(".", 1)[0]
            assert target in entity_names, (entity["name"], foreign_key)


def test_db001_preserves_orthogonal_facts_and_rebuildable_derivatives():
    data = _contract()
    names = {entity["name"] for entity in data["entities"]}
    for required in (
        "kb_document",
        "kb_document_version",
        "kb_chunk_version",
        "kb_chunk",
        "kb_embedding_model",
        "kb_chunk_embedding",
        "kb_index_version",
        "ai_provider",
        "ai_model",
        "ai_model_route",
    ):
        assert required in names
    assert "original_document_version_is_immutable_fact_source" in data["invariants"]
    assert "chunks_embeddings_and_indexes_are_derived_generations" in data["invariants"]
    assert "product_os_and_software_version_are_orthogonal" in data["invariants"]
    mapping = data["compatibility_mapping"]
    assert mapping["ai_document"] == "kb_document_plus_kb_document_version"
    assert mapping["ai_document_chunk"] == "kb_chunk_plus_kb_chunk_embedding"
    assert "adapter" in mapping["rule"]


def test_db001_report_records_er_scope_migration_and_rollback():
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-001",
        "PostgreSQL",
        "kb_document_version",
        "kb_chunk_embedding",
        "ai_model_route",
        "V1",
        "回滚",
        "PASS",
    ):
        assert marker in report, marker
