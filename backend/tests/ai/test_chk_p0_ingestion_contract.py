import json
import sqlite3

import pytest

from ai.services import knowledge_service as knowledge_service_module


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            knowledge_base_id TEXT,
            name TEXT,
            source TEXT,
            vendor TEXT,
            platform TEXT,
            status TEXT,
            knowledge_source_type TEXT,
            tenant_id TEXT,
            acl_json TEXT,
            source_trust_level TEXT,
            metadata_json TEXT,
            normalized_content TEXT,
            original_content TEXT,
            content_hash TEXT,
            chunking_version TEXT,
            ingestion_status TEXT,
            chunker_version TEXT,
            parser_version TEXT,
            document_version TEXT,
            index_version TEXT,
            embedding_model TEXT,
            embedding_dimensions INTEGER,
            embedding_version TEXT,
            embedding_mode TEXT,
            embedding_contract_version TEXT,
            metadata_parse_status TEXT,
            metadata_parse_error TEXT,
            exclude_from_rag INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT,
            content TEXT,
            raw_content TEXT,
            embedding_content TEXT,
            embedding TEXT,
            metadata_json TEXT,
            page INTEGER,
            section TEXT,
            created_at TEXT,
            parent_chunk_id TEXT,
            chunk_role TEXT,
            chunk_type TEXT,
            ordinal INTEGER,
            heading_path_json TEXT,
            token_count INTEGER,
            content_hash TEXT,
            source_locator_json TEXT,
            chunking_version TEXT,
            is_retrieval_candidate INTEGER,
            oversize_reason TEXT,
            chunker_version TEXT,
            structure_types_json TEXT,
            neighbor_chunk_ids_json TEXT,
            parser_version TEXT,
            document_version TEXT,
            index_version TEXT,
            embedding_model TEXT,
            embedding_dimensions INTEGER,
            embedding_version TEXT,
            embedding_mode TEXT,
            embedding_contract_version TEXT
        );
        """
    )
    return connection


def test_chk008_and_chk004_persist_explicit_graph_and_version_contract(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(knowledge_service_module.embedding_provider, "dimensions", 2)
    monkeypatch.setattr(knowledge_service_module.embedding_provider, "embed_text", lambda text: [0.1, 0.2])

    result = knowledge_service_module.KnowledgeService().add_document_and_chunk(
        knowledge_base_id="kb-1",
        name="OSPF guide",
        content=(
            "# OSPF\n\n## Verification\n"
            "The first diagnostic paragraph contains enough context.\n\n"
            "The second diagnostic paragraph contains the expected state.\n\n"
            "The third diagnostic paragraph contains the remediation."
        ),
        vendor="H3C",
        platform="h3c_comware",
        metadata={"document_version": "source-v4", "index_version": "index-v7"},
    )

    assert result["chunk_count"] >= 1
    document = connection.execute(
        "SELECT chunker_version, parser_version, document_version, index_version, embedding_mode, embedding_contract_version "
        "FROM ai_document"
    ).fetchone()
    assert document[0] == "network-structure-v2"
    assert document[1] == "markdown-network-parser-v2"
    assert document[2] == "source-v4"
    assert document[3] == "index-v7"
    assert document[4] == "local"
    assert document[5].endswith(":2")
    rows = connection.execute(
        "SELECT structure_types_json, neighbor_chunk_ids_json, chunker_version, parser_version, document_version, index_version, embedding_dimensions "
        "FROM ai_document_chunk ORDER BY ordinal"
    ).fetchall()
    assert rows
    assert all(json.loads(row[0]) for row in rows)
    assert all(json.loads(row[1]) is not None for row in rows)
    assert all(row[2] == "network-structure-v2" for row in rows)
    assert all(row[3] == "markdown-network-parser-v2" for row in rows)
    assert all(row[4] == "source-v4" for row in rows)
    assert all(row[5] == "index-v7" for row in rows)
    assert all(row[6] == 2 for row in rows)


def test_chk011_dimension_failure_happens_before_any_document_row(monkeypatch):
    connection = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: connection)
    monkeypatch.setattr(knowledge_service_module.embedding_provider, "dimensions", 2)
    monkeypatch.setattr(knowledge_service_module.embedding_provider, "embed_text", lambda text: [0.1])

    with pytest.raises(ValueError, match="Embedding"):
        knowledge_service_module.KnowledgeService().add_document_and_chunk(
            knowledge_base_id="kb-1",
            name="Broken embedding guide",
            content="# OSPF\n\nshow version",
            vendor="H3C",
        )

    assert connection.execute("SELECT COUNT(*) FROM ai_document").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM ai_document_chunk").fetchone()[0] == 0
