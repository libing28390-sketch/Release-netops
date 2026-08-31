import importlib
from backend.tests.pg_test_utils import postgresql_test_driver
import pytest


knowledge_service_module = importlib.import_module("ai.services.knowledge_service")
assistant_module = importlib.import_module("ai.api.assistant")


def _connection():
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.executescript(
        """
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY,
            knowledge_base_id TEXT,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            tenant_id TEXT NOT NULL,
            updated_at TEXT,
            original_content TEXT,
            normalized_content TEXT,
            metadata_json TEXT DEFAULT '{}',
            document_id TEXT,
            vendor TEXT,
            platform TEXT
        );
        CREATE TABLE ai_document_chunk (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            content TEXT
        );
        CREATE TABLE ai_document_revision (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            record_type TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE ai_knowledge_document_action (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            confirmed INTEGER NOT NULL,
            actor_id TEXT,
            actor_username TEXT,
            reason TEXT NOT NULL DEFAULT '',
            job_id TEXT,
            impact_json TEXT NOT NULL DEFAULT '{}',
            recovery_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        INSERT INTO ai_document (id, knowledge_base_id, name, status, tenant_id, updated_at, original_content, normalized_content, metadata_json, document_id, vendor, platform)
        VALUES ('doc-a', 'kb-a', 'OSPF guide', 'active', 'tenant-a', '2026-08-17', '# OSPF\nhello', '# OSPF\nhello', '{}', 'doc-a', 'Huawei', 'huawei_vrp');
        INSERT INTO ai_document_chunk (id, document_id, content) VALUES ('chunk-a', 'doc-a', 'hello');
        INSERT INTO ai_document_revision (id, tenant_id, document_id, record_type) VALUES ('rev-source-a', 'tenant-a', 'doc-a', 'source_observation');
        INSERT INTO ai_document_revision (id, tenant_id, document_id, record_type) VALUES ('rev-document-a', 'tenant-a', 'doc-a', 'document_revision');
        INSERT INTO ai_document (id, knowledge_base_id, name, status, tenant_id, updated_at, original_content, normalized_content, metadata_json, document_id, vendor, platform)
        VALUES ('doc-b', 'kb-b', 'Other tenant', 'active', 'tenant-b', '2026-08-17', '# OSPF\nother', '# OSPF\nother', '{}', 'doc-b', 'Huawei', 'huawei_vrp');
        """
    )
    return conn


def test_confirmation_is_required_before_any_mutation(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: conn)
    service = knowledge_service_module.KnowledgeService()

    with pytest.raises(knowledge_service_module.KnowledgeDocumentActionError) as exc:
        service.execute_document_action(doc_id="doc-a", action="disable", tenant_id="tenant-a", confirm=False)
    assert exc.value.code == "KNOWLEDGE_ACTION_CONFIRMATION_REQUIRED"
    assert conn.execute("SELECT status FROM ai_document WHERE id = 'doc-a'").fetchone()[0] == "active"
    assert conn.execute("SELECT COUNT(*) FROM ai_knowledge_document_action").fetchone()[0] == 0


def test_impact_preview_is_read_only_and_counts_references(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: conn)
    preview = knowledge_service_module.KnowledgeService().get_document_action_impact(doc_id="doc-a", tenant_id="tenant-a")
    assert preview["safe_to_confirm"] is True
    assert preview["impact"] == {
        "documents": 1,
        "chunks": 1,
        "indexes": 1,
        "references": 2,
        "reference_details": [
            {"type": "document_revision", "count": 1},
            {"type": "v1_provenance_event", "count": 1},
        ],
        "reference_scope": "ai_document_revision",
    }
    assert conn.execute("SELECT status FROM ai_document WHERE id = 'doc-a'").fetchone()[0] == "active"
    assert conn.execute("SELECT COUNT(*) FROM ai_knowledge_document_action").fetchone()[0] == 0


def test_disable_is_tenant_scoped_idempotent_and_audited(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: conn)
    monkeypatch.setattr(knowledge_service_module.retrieval_cache, "invalidate_documents", lambda ids: None)
    result = knowledge_service_module.KnowledgeService().execute_document_action(
        doc_id="doc-a", action="disable", tenant_id="tenant-a", actor_id="u-a", actor_username="alice", confirm=True, reason="retire",
    )
    assert result["status"] == "succeeded"
    assert result["impact"]["chunks"] == 1
    assert conn.execute("SELECT status FROM ai_document WHERE id = 'doc-a'").fetchone()[0] == "disabled"
    audit = conn.execute("SELECT action, status, confirmed, reason FROM ai_knowledge_document_action").fetchone()
    assert tuple(audit) == ("disable", "succeeded", 1, "retire")

    with pytest.raises(knowledge_service_module.KnowledgeDocumentActionError) as exc:
        knowledge_service_module.KnowledgeService().execute_document_action(
            doc_id="doc-a", action="enable", tenant_id="tenant-b", confirm=True,
        )
    assert exc.value.code == "KNOWLEDGE_DOCUMENT_NOT_FOUND"


def test_delete_action_removes_chunks_but_keeps_redacted_ledger(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: conn)
    monkeypatch.setattr(knowledge_service_module.retrieval_cache, "invalidate_documents", lambda ids: None)
    result = knowledge_service_module.KnowledgeService().execute_document_action(
        doc_id="doc-a", action="delete", tenant_id="tenant-a", confirm=True, reason="duplicate upload",
    )
    assert result["status"] == "succeeded"
    assert conn.execute("SELECT COUNT(*) FROM ai_document WHERE id = 'doc-a'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ai_document_chunk WHERE document_id = 'doc-a'").fetchone()[0] == 0
    row = conn.execute("SELECT document_id, action, impact_json FROM ai_knowledge_document_action").fetchone()
    assert row[0] == "doc-a" and row[1] == "delete"
    assert "hello" not in row[2]


def test_reparse_rechunk_reindex_are_distinct_confirmed_job_operations(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(knowledge_service_module, "get_db_connection", lambda: conn)
    monkeypatch.setattr(knowledge_service_module.retrieval_cache, "invalidate_documents", lambda ids: None)
    reindex_module = importlib.import_module("ai.services.knowledge_reindex_service")
    jobs = []

    def fake_create_job(**kwargs):
        jobs.append(kwargs)
        return {"id": f"job-{kwargs['operation']}", "status": "queued", "operation": kwargs["operation"]}

    monkeypatch.setattr(reindex_module.knowledge_reindex_service, "create_job", fake_create_job)
    service = knowledge_service_module.KnowledgeService()
    for operation in ("reparse", "rechunk", "reindex"):
        result = service.execute_document_action(
            doc_id="doc-a", action=operation, tenant_id="tenant-a", confirm=True,
        )
        assert result["status"] == "queued"
        assert result["job_id"] == f"job-{operation}"
    assert [item["operation"] for item in jobs] == ["reparse", "rechunk", "reindex"]
    assert all(item["scope"] == {"document_id": "doc-a"} for item in jobs)
    assert conn.execute("SELECT COUNT(*) FROM ai_knowledge_document_action WHERE status = 'queued'").fetchone()[0] == 3


def test_action_request_forbids_unknown_fields():
    with pytest.raises(Exception):
        assistant_module.KnowledgeDocumentActionRequest(confirm=True, raw_content="secret")
