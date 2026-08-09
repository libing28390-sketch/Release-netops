from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-010-CHUNK-INDEX-RELATIONSHIPS.yaml"
REPORT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-010-CHUNK-INDEX-RELATIONSHIPS.md"
ER_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-001-core-er-model.yaml"
COMMON_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-002-COMMON-COLUMN-SEMANTICS.yaml"
LIFECYCLE_CONTRACT = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-003-LIFECYCLE-POLICY.yaml"
M0111 = ROOT / "backend" / "database" / "migrations" / "m0111_ai_chunking_v2.py"
ENGINE = ROOT / "backend" / "ai" / "chunking" / "engine.py"
RETRIEVER = ROOT / "backend" / "ai" / "services" / "rag_retriever.py"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_db010_freezes_chunk_generation_parent_child_edge_and_index_entities():
    data = _load(CONTRACT)
    assert data["task_id"] == "DB-010"
    assert data["priority"] == "P0"
    assert data["status"] == "frozen_for_implementation"
    assert data["decision"]["choice"] == "versioned_chunk_graph_with_atomic_index_generations"
    assert list(data["entities"]) == [
        "kb_chunk_version",
        "kb_chunk",
        "kb_chunk_edge",
        "kb_embedding_model",
        "kb_chunk_embedding",
        "kb_index_version",
    ]


def test_db010_entities_match_db001_and_common_tenant_columns():
    data = _load(CONTRACT)
    er_entities = {entity["name"]: entity for entity in _load(ER_CONTRACT)["entities"]}
    common = set(_load(COMMON_CONTRACT)["columns"])
    expected_common = {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "status"}
    assert common.issuperset(expected_common)
    for name, entity in data["entities"].items():
        assert name in er_entities
        assert set(entity["required_columns"]) == set(er_entities[name]["required_columns"])
        assert entity["unique_keys"] == er_entities[name]["unique_keys"]
        assert set(expected_common).issubset(entity["required_columns"])
        assert entity["foreign_keys"] == er_entities[name].get("foreign_keys", [])


def test_db010_parent_child_is_explicit_same_generation_dag_and_roles_are_allowlisted():
    data = _load(CONTRACT)
    chunk = data["entities"]["kb_chunk"]
    roles = set(chunk["role_contract"]["allowed_roles"])
    assert {"standalone", "parent", "child", "command", "output"}.issubset(roles)
    assert chunk["role_contract"]["child_role_rule"] == "child_requires_parent_chunk_id"
    assert chunk["role_contract"]["standalone_role_rule"] == "standalone_must_not_have_parent_chunk_id"
    parent = chunk["parent_child_contract"]
    assert parent["parent_chunk_id"] == "nullable_self_reference_with_same_tenant_and_chunk_version"
    assert parent["self_parent"] == "forbidden"
    assert parent["cycle_detection"] == "required_before_generation_activation"
    assert data["entities"]["kb_chunk_version"]["generation_contract"]["immutability"] == "append_new_generation_instead_of_mutating_existing_chunks"
    engine = ENGINE.read_text(encoding="utf-8")
    for field in ("class Chunk", "parent_chunk_id", "chunk_role", "content_hash", "is_retrieval_candidate"):
        assert field in engine


def test_db010_neighbors_are_explicit_edges_not_ordinal_inference():
    data = _load(CONTRACT)
    edge = data["entities"]["kb_chunk_edge"]["edge_contract"]
    assert {"neighbor", "next", "previous", "semantic"}.issubset(set(edge["allowed_edge_kinds"]))
    assert edge["parent_child_separation"] == "parent_chunk_id_is_structural; edge_table_does_not_replace_it"
    assert edge["same_generation"] == "from_and_to_chunks_must_reference_the_declared_chunk_version"
    assert edge["self_edge"] == "forbidden"
    assert edge["ordinal_delta"] == "derived_to_ordinal_minus_from_ordinal_and_must_not_be_authority"
    retriever = RETRIEVER.read_text(encoding="utf-8")
    for field in ("chunk_role", "parent_chunk_id", "ordinal", "embedding_model", "_expand_document_context"):
        assert field in retriever


def test_db010_embedding_and_index_versions_form_one_atomic_contract():
    data = _load(CONTRACT)
    model = data["entities"]["kb_embedding_model"]
    embedding = data["entities"]["kb_chunk_embedding"]
    index = data["entities"]["kb_index_version"]
    assert model["unique_keys"] == [["tenant_id", "provider_id", "model_code", "contract_version"]]
    assert model["contract"]["dimension"] == "positive_integer_and_immutable_for_contract_version"
    assert "provider_reference" in model["contract"]
    assert embedding["unique_keys"] == [["tenant_id", "chunk_id", "embedding_model_id", "index_version_id"]]
    assert embedding["invariants"]["vector_contract"] == "dimension_equals_embedding_model_dimension_and_contract_version_is_compatible"
    assert index["cutover_contract"]["atomicity"] == "publish_pointer_and_status_in_one_transaction"
    assert index["cutover_contract"]["reader_rule"] == "readers_select_one_active_ready_generation; never_mix_generations"
    assert index["cutover_contract"]["rollback_to_id"] == "nullable_previous_ready_generation_same_tenant"


def test_db010_derived_lifecycle_and_cutover_states_are_fail_closed():
    data = _load(CONTRACT)
    lifecycle = _load(LIFECYCLE_CONTRACT)
    derived = set(lifecycle["entity_policies"]["derived_retrieval"]["allowed"])
    for name in data["entities"]:
        assert set(data["entities"][name]["lifecycle_statuses"]) == derived
    index = data["entities"]["kb_index_version"]
    assert {"planned", "building", "verifying", "ready", "failed", "rolling_back", "rolled_back"}.issubset(set(index["build_states"]))
    assert index["cutover_contract"]["verification"] == "verified_at_required_before_active"
    assert index["cutover_contract"]["failure"] == "failed_generation_is_not_readable_and_remains_auditable"


def test_db010_audits_real_v1_chunking_migration_and_keeps_compatibility():
    data = _load(CONTRACT)
    migration = M0111.read_text(encoding="utf-8")
    engine = ENGINE.read_text(encoding="utf-8")
    legacy = data["legacy_gap_audit"]["ai_document_chunk"]
    for field in ("parent_chunk_id", "chunk_role", "chunk_type", "ordinal", "raw_content", "embedding_content", "content_hash", "is_retrieval_candidate"):
        assert field in migration
        assert field in legacy["current_fields"]
    for field in ("deterministic_chunk_id", "parent_chunk_id", "chunk_role", "content_hash", "ordinal"):
        assert field in engine or (field == "deterministic_chunk_id" and "chunk_id" in engine)
    assert legacy["mapping"] == "ai_document_chunk_to_kb_chunk_plus_kb_chunk_version; legacy_embedding_to_kb_chunk_embedding_after_model_contract_validation"
    assert data["migration_contract"]["production_gate"] == "forbidden_until_MIG_and_REL_and_shadow_acl_retrieval_checks_pass"


def test_db010_tenant_security_migration_rollback_and_report_evidence_are_present():
    data = _load(CONTRACT)
    security = data["tenant_security_and_audit"]
    assert security["tenant_scope"] == "composite_tenant_id_plus_parent_id_foreign_keys_on_every_relation"
    assert security["authorization"]
    assert security["audit_events"]
    assert "cross_tenant_parent_or_edge" in security["deny_conditions"]
    assert data["migration_contract"]["status"] == "contract_only_no_production_ddl_in_db_010"
    assert data["migration_contract"]["rollback"]
    assert data["rollback"]["runtime"]
    report = REPORT.read_text(encoding="utf-8")
    for marker in (
        "DB-010", "Chunk Version", "Parent/Child", "Neighbor", "Chunk Role", "Index Version",
        "kb_chunk_version", "kb_chunk_edge", "kb_chunk_embedding", "ACL", "回滚", "V1",
        "DB-011", "DB-012", "Final Conclusion: PASS",
    ):
        assert marker in report, marker
