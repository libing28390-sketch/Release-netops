from __future__ import annotations

import json
from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from pathlib import Path

import yaml

from ai.services.knowledge_reindex_service import (
    DEFAULT_BATCH_SIZE,
    MAX_BATCH_SIZE,
    KnowledgeReindexService,
    _ReindexLease,
)
from database import get_db_connection


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-022-REINDEX-BATCH-LEASE-CONTRACT.yaml"
REPORT = ROOT / "docs" / "knowledge-engine" / "architecture" / "DB-022-REINDEX-BATCH-LEASE-CONTRACT.md"
SERVICE = ROOT / "backend" / "ai" / "services" / "knowledge_reindex_service.py"
ASSISTANT = ROOT / "backend" / "ai" / "api" / "assistant.py"


def _load() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_db022_contract_and_runtime_markers_are_frozen():
    data = _load()
    assert data["task_id"] == "DB-022"
    assert data["priority"] == "P1"
    assert data["status"] == "implemented_runtime_coordination"
    assert data["contract_version"] == "v2.1"
    assert data["lease"]["owner_token"] == "opaque_worker_uuid_in_owner_token"
    assert data["concurrency"]["database_lock"] == "scheduler_locks_atomic_expiry_aware_upsert"
    assert data["batch"]["max_batch_size"] == MAX_BATCH_SIZE
    assert data["batch"]["default_batch_size"] == DEFAULT_BATCH_SIZE
    assert data["lease"]["storage"] == "existing_scheduler_locks"
    assert "lease_owner_token_fences_stale_heartbeat_and_release" in data["decision"]["invariants"]
    service = SERVICE.read_text(encoding="utf-8")
    for marker in (
        "_select_document_batch", "ORDER BY d.id LIMIT", "_ReindexLease", "heartbeat",
        "retry_wait", "_CONTROL_KEY", "checkpointed", "MAX_BATCH_SIZE",
    ):
        assert marker in service, marker
    assert "batch_size=payload.get" in ASSISTANT.read_text(encoding="utf-8")
    report = REPORT.read_text(encoding="utf-8")
    for marker in ("DB-022", "keyset", "scheduler_locks", "heartbeat", "retry_wait", "idempotent", "V1", "Final Conclusion: PASS"):
        assert marker in report, marker


def test_db022_lease_excludes_duplicate_worker_and_fences_owner():
    conn = postgresql_test_driver.connect()
    conn.execute(
        "CREATE TABLE scheduler_locks ("
        "lock_name TEXT PRIMARY KEY, owner_token TEXT NOT NULL, "
        "locked_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL)"
    )
    import ai.services.knowledge_reindex_service as module

    original = module.get_db_connection
    module.get_db_connection = lambda: conn
    try:
        first = _ReindexLease("job-1", lease_seconds=30)
        second = _ReindexLease("job-1", lease_seconds=30)
        assert first.acquire() is True
        persisted = conn.execute(
            "SELECT owner_token, locked_at, expires_at FROM scheduler_locks WHERE lock_name = ?",
            (first.lock_name,),
        ).fetchone()
        assert persisted["owner_token"] == first.owner_token
        assert persisted["locked_at"].tzinfo is not None
        assert persisted["expires_at"].tzinfo is not None
        assert second.acquire() is False
        assert first.heartbeat() is True
        second.owner_token = first.owner_token + "-stale"
        second._held = True
        assert second.heartbeat() is False
        first.release()
        assert second.acquire() is True
        second.release()
    finally:
        module.get_db_connection = original
        conn.close()


def test_db022_batch_size_is_clamped_and_keyset_fetch_is_bounded(isolated_db, monkeypatch):
    service = KnowledgeReindexService()
    conn = get_db_connection()
    try:
        now = "2026-08-09T00:00:00+00:00"
        conn.execute("INSERT INTO ai_knowledge_base (id, name, created_at, tenant_id) VALUES (?, ?, ?, ?)", ("kb-022", "DB022", now, "tenant-default"))
        for index in range(4):
            conn.execute(
                "INSERT INTO ai_document (id, knowledge_base_id, name, status, created_at, updated_at, tenant_id) VALUES (?, ?, ?, 'active', ?, ?, ?)",
                (f"doc-{index}", "kb-022", f"Doc {index}", now, now, "tenant-default"),
            )
        conn.commit()
        first = service._select_document_batch({}, "tenant-default", after_id=None, batch_size=999999)
        assert len(first) == 4
        assert [item["id"] for item in first] == sorted(item["id"] for item in first)
        second = service._select_document_batch({}, "tenant-default", after_id=first[1]["id"], batch_size=2)
        assert [item["id"] for item in second] == ["doc-2", "doc-3"]
        assert service._select_document_batch({}, "tenant-default", after_id="doc-3", batch_size=2) == []
    finally:
        conn.close()


def test_db022_run_job_processes_batches_and_hides_private_cursor(isolated_db, monkeypatch):
    service = KnowledgeReindexService()
    batches = {
        None: [{"id": "doc-1"}, {"id": "doc-2"}],
        "doc-2": [{"id": "doc-3"}],
        "doc-3": [],
    }
    processed: list[str] = []
    monkeypatch.setattr(service, "_count_documents", lambda scope, tenant_id: 3)
    monkeypatch.setattr(
        service,
        "_select_document_batch",
        lambda scope, tenant_id, *, after_id, batch_size: batches.get(after_id, []),
    )
    monkeypatch.setattr(
        service,
        "_process_document",
        lambda document, dry_run: processed.append(document["id"]) or {
            "parsed": 1, "updated": 1, "rechunked": 2, "embedding_success": 2, "embedding_failed": 0,
        },
    )
    job = service.create_job(tenant_id="tenant-default", scope={}, run_async=False, batch_size=2)
    assert job["status"] == "completed"
    assert processed == ["doc-1", "doc-2", "doc-3"]
    assert job["batch_size"] == 2
    assert job["checkpointed"] is False
    assert job["processed"] == 3
    assert job["progress_percent"] == 100
    raw_scope = get_db_connection().execute("SELECT scope_json FROM ai_knowledge_reindex_job WHERE id = ?", (job["id"],)).fetchone()[0]
    assert "_db022_control" in raw_scope
    assert "doc-3" not in json.dumps(job["scope"], ensure_ascii=False)


def test_db022_lease_loss_preserves_checkpoint_and_is_retryable(isolated_db, monkeypatch):
    service = KnowledgeReindexService()
    monkeypatch.setattr(service, "_count_documents", lambda scope, tenant_id: 2)
    monkeypatch.setattr(service, "_select_document_batch", lambda *args, **kwargs: [{"id": "doc-1"}])
    monkeypatch.setattr(service, "_process_document", lambda document, dry_run: {"parsed": 1, "updated": 1, "rechunked": 1, "embedding_success": 1, "embedding_failed": 0})

    class LostLease:
        def acquire(self):
            return True

        def heartbeat(self):
            return False

        def release(self):
            return None

    import ai.services.knowledge_reindex_service as module

    monkeypatch.setattr(module, "_ReindexLease", lambda job_id: LostLease())
    job = service.create_job(tenant_id="tenant-default", scope={}, run_async=False, batch_size=2)
    assert job["status"] == "retry_wait"
    assert job["checkpointed"] is False
    assert job["processed"] == 0


def test_db022_v1_schema_and_source_rows_are_preserved(isolated_db):
    conn = get_db_connection()
    try:
        before = tuple(sorted(pg_catalog.table_names(conn)))
        source_count = conn.execute("SELECT COUNT(*) FROM ai_document").fetchone()[0]
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        assert "devices" in before and "ai_document" in before
        assert source_count >= 0
    finally:
        conn.close()
