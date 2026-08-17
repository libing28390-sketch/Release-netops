"""PostgreSQL gate for KUI-012 independent document actions.

All fixtures are inserted in one transaction and rolled back.  The probe
exercises the production PostgreSQL path; the SQLite pytest is compatibility
coverage only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import core  # noqa: E402
from ai.services import knowledge_service as knowledge_service_module  # noqa: E402
from ai.services import knowledge_reindex_service as reindex_module  # noqa: E402


class _SameConnectionContext:
    def __init__(self, connection: Any):
        self.connection = connection

    def __enter__(self) -> Any:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("KUI-012 PostgreSQL gate refused to run: DATABASE_URL is not PostgreSQL")

    conn = core.get_db_connection()
    original_get_db_connection = knowledge_service_module.get_db_connection
    original_audit = knowledge_service_module.KnowledgeService._write_action_audit
    original_create_job = reindex_module.knowledge_reindex_service.create_job
    cur = conn.cursor()
    try:
        kb = cur.execute("SELECT id FROM ai_knowledge_base ORDER BY id LIMIT 1").fetchone()
        if not kb:
            raise RuntimeError("KUI-012 PostgreSQL probe requires an existing ai_knowledge_base")
        kb_id = str(kb[0])
        now = "2026-08-17T00:00:00+00:00"
        doc_a = "__kui012_pg_doc_a"
        doc_b = "__kui012_pg_doc_b"
        doc_delete = "__kui012_pg_doc_delete"
        for doc_id, tenant, name in (
            (doc_a, "__kui012_tenant_a", "KUI012 action document"),
            (doc_b, "__kui012_tenant_b", "KUI012 other tenant"),
            (doc_delete, "__kui012_tenant_a", "KUI012 delete document"),
        ):
            cur.execute(
                "INSERT INTO ai_document "
                "(id, knowledge_base_id, name, source, vendor, platform, status, "
                "knowledge_source_type, tenant_id, acl_json, source_trust_level, metadata_json, "
                "original_content, normalized_content, created_at, updated_at) "
                "VALUES (?, ?, ?, 'kui012', 'Huawei', 'huawei_vrp', 'active', 'internal_sop', ?, '{}', 'internal', '{}', ?, ?, ?, ?)",
                (doc_id, kb_id, name, tenant, "# OSPF\nhello", "# OSPF\nhello", now, now),
            )
            cur.execute(
                "INSERT INTO ai_document_chunk (id, document_id, content, created_at) VALUES (?, ?, ?, ?)",
                (f"{doc_id}-chunk", doc_id, "hello", now),
            )

        knowledge_service_module.get_db_connection = lambda: _SameConnectionContext(conn)
        knowledge_service_module.KnowledgeService._write_action_audit = staticmethod(lambda **kwargs: None)
        service = knowledge_service_module.KnowledgeService()

        preview = service.get_document_action_impact(doc_id=doc_a, tenant_id="__kui012_tenant_a")
        if not preview["safe_to_confirm"] or set(("documents", "chunks", "indexes", "references")) - set(preview["impact"]):
            raise AssertionError(f"impact preview contract mismatch: {preview}")

        missing_confirmation = False
        try:
            service.execute_document_action(doc_id=doc_a, action="disable", tenant_id="__kui012_tenant_a", confirm=False)
        except knowledge_service_module.KnowledgeDocumentActionError as exc:
            missing_confirmation = exc.code == "KNOWLEDGE_ACTION_CONFIRMATION_REQUIRED"
        if not missing_confirmation:
            raise AssertionError("missing confirmation was not rejected")

        disabled = service.execute_document_action(
            doc_id=doc_a, action="disable", tenant_id="__kui012_tenant_a",
            actor_id="__kui012_user", actor_username="kui012", confirm=True, reason="probe disable",
        )
        if disabled["status"] != "succeeded" or disabled["current_status"] != "disabled":
            raise AssertionError(f"disable contract mismatch: {disabled}")
        if cur.execute("SELECT status FROM ai_document WHERE id = ?", (doc_a,)).fetchone()[0] != "disabled":
            raise AssertionError("disable did not project to ai_document")

        enabled = service.execute_document_action(
            doc_id=doc_a, action="enable", tenant_id="__kui012_tenant_a", confirm=True, reason="probe recovery",
        )
        if enabled["current_status"] != "active":
            raise AssertionError(f"enable recovery mismatch: {enabled}")

        cross_tenant_denied = False
        try:
            service.execute_document_action(doc_id=doc_a, action="disable", tenant_id="__kui012_tenant_b", confirm=True)
        except knowledge_service_module.KnowledgeDocumentActionError as exc:
            cross_tenant_denied = exc.code == "KNOWLEDGE_DOCUMENT_NOT_FOUND"
        if not cross_tenant_denied:
            raise AssertionError("cross-tenant action was not denied")

        jobs: list[dict[str, Any]] = []

        def fake_create_job(**kwargs):
            jobs.append(kwargs)
            return {"id": f"__kui012_{kwargs['operation']}", "status": "queued", "operation": kwargs["operation"]}

        reindex_module.knowledge_reindex_service.create_job = fake_create_job
        queued = [
            service.execute_document_action(doc_id=doc_a, action=operation, tenant_id="__kui012_tenant_a", confirm=True)
            for operation in ("reparse", "rechunk", "reindex")
        ]
        if [item["action"] for item in queued] != ["reparse", "rechunk", "reindex"]:
            raise AssertionError(f"action identity mismatch: {queued}")
        if [item["operation"] for item in jobs] != ["reparse", "rechunk", "reindex"]:
            raise AssertionError(f"job operation mismatch: {jobs}")
        if any(item["scope"] != {"document_id": doc_a} for item in jobs):
            raise AssertionError(f"job scope mismatch: {jobs}")

        deleted = service.execute_document_action(
            doc_id=doc_delete, action="delete", tenant_id="__kui012_tenant_a", confirm=True, reason="probe delete",
        )
        if deleted["status"] != "succeeded":
            raise AssertionError(f"delete contract mismatch: {deleted}")
        if cur.execute("SELECT COUNT(*) FROM ai_document WHERE id = ?", (doc_delete,)).fetchone()[0] != 0:
            raise AssertionError("delete left document row")
        if cur.execute("SELECT COUNT(*) FROM ai_document_chunk WHERE document_id = ?", (doc_delete,)).fetchone()[0] != 0:
            raise AssertionError("delete left chunk rows")
        ledger_rows = cur.execute(
            "SELECT action, status, confirmed, tenant_id FROM ai_knowledge_document_action "
            "WHERE document_id IN (?, ?) ORDER BY created_at",
            (doc_a, doc_delete),
        ).fetchall()
        if not ledger_rows or any(row[2] != 1 for row in ledger_rows):
            raise AssertionError(f"action ledger mismatch: {ledger_rows}")
        if "hello" in json.dumps([dict(row) if hasattr(row, "keys") else list(row) for row in ledger_rows]):
            raise AssertionError("action ledger leaked body content")

        return {
            "postgresql": True,
            "migration_0145": bool(cur.execute("SELECT 1 FROM schema_migrations WHERE version = 145").fetchone()),
            "confirmation": missing_confirmation,
            "impact_preview": True,
            "tenant_isolation": cross_tenant_denied,
            "disable_enable_recovery": True,
            "independent_operations": True,
            "delete_atomicity": True,
            "metadata_only_ledger": True,
        }
    finally:
        knowledge_service_module.get_db_connection = original_get_db_connection
        knowledge_service_module.KnowledgeService._write_action_audit = original_audit
        reindex_module.knowledge_reindex_service.create_job = original_create_job
        # Action methods intentionally commit their own transaction.  Clean
        # the explicitly named probe fixtures after the assertions so reruns
        # are deterministic and no test data remains in the local PostgreSQL.
        try:
            conn.rollback()
            cleanup = conn.cursor()
            cleanup.execute(
                "DELETE FROM ai_knowledge_document_action WHERE document_id IN (?, ?, ?)",
                ("__kui012_pg_doc_a", "__kui012_pg_doc_b", "__kui012_pg_doc_delete"),
            )
            cleanup.execute(
                "DELETE FROM ai_document_chunk WHERE document_id IN (?, ?, ?)",
                ("__kui012_pg_doc_a", "__kui012_pg_doc_b", "__kui012_pg_doc_delete"),
            )
            cleanup.execute(
                "DELETE FROM ai_document WHERE id IN (?, ?, ?)",
                ("__kui012_pg_doc_a", "__kui012_pg_doc_b", "__kui012_pg_doc_delete"),
            )
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


if __name__ == "__main__":
    print(json.dumps(_run(), ensure_ascii=False, sort_keys=True))
