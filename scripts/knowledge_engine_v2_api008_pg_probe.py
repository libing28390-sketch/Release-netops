"""PostgreSQL-only API-008 tenant/user isolation probe.

All tables live in a temporary schema and the connection is rolled back.  The
probe exercises the migration plus the real conversation, diagnostics and
Agent trace readers, proving that a known foreign id returns no data.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ai.api import agents as agent_api  # noqa: E402
from ai.security import security_service  # noqa: E402
from ai.security.tokenization import opaque_user_id  # noqa: E402
from ai.services import conversation_service  # noqa: E402
from database import core  # noqa: E402
from database.migrations import m0146_ai_session_scope_hardening as migration  # noqa: E402


class _SameConnection:
    def __init__(self, connection: Any):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return self.connection.cursor(*args, **kwargs)


def run() -> dict[str, Any]:
    if not core._USE_PG:
        raise SystemExit("API-008 PostgreSQL probe refused: DATABASE_URL is not PostgreSQL")
    conn = core.get_db_connection()
    schema = f"api008_probe_{uuid.uuid4().hex[:10]}"
    originals = {
        "conversation": conversation_service.get_db_connection,
        "security": security_service.get_db_connection,
        "agents": agent_api.get_db_connection,
    }
    try:
        conn.execute("BEGIN")
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET LOCAL search_path TO "{schema}"')
        conn.execute("CREATE TABLE ai_agent_run (id TEXT PRIMARY KEY, agent_id TEXT, user_id TEXT, question TEXT, status TEXT, started_at TEXT, finished_at TEXT, final_result TEXT)")
        conn.execute("CREATE TABLE ai_agent_step (id TEXT PRIMARY KEY, run_id TEXT, step_no INTEGER, step_type TEXT, tool_name TEXT, tool_input TEXT, tool_output TEXT, status TEXT, started_at TEXT, finished_at TEXT)")
        conn.execute("CREATE TABLE ai_tasks (id TEXT PRIMARY KEY, conversation_id TEXT, tenant_id TEXT NOT NULL, user_id_opaque TEXT NOT NULL, scene TEXT NOT NULL, state TEXT NOT NULL, max_steps INTEGER NOT NULL, max_tool_calls INTEGER NOT NULL, deadline_at TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, started_at TEXT, finished_at TEXT, error_code TEXT, created_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE ai_tool_calls (id TEXT PRIMARY KEY, task_id TEXT, step_no INTEGER, tool_name TEXT, input_schema_version TEXT, input_safe_json TEXT, result_safe_json TEXT, source TEXT, freshness TEXT, status TEXT, policy_decision TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE ai_evidence (id TEXT PRIMARY KEY, task_id TEXT, tool_call_id TEXT, source_type TEXT, source_id TEXT, citation TEXT, fact_json TEXT, confidence REAL, collected_at TEXT)")
        conn.execute("CREATE TABLE ai_conversations (id TEXT PRIMARY KEY, tenant_id TEXT, user_id_opaque TEXT, title TEXT, status TEXT, context_budget INTEGER, created_at TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE ai_messages (id TEXT PRIMARY KEY, conversation_id TEXT, sequence_no INTEGER, role TEXT, content_safe TEXT, citations_json TEXT, token_count INTEGER, created_at TEXT)")
        conn.execute("CREATE TABLE ai_conversation_feedback (id TEXT PRIMARY KEY, tenant_id TEXT, conversation_id TEXT, message_id TEXT, user_id_opaque TEXT, rating TEXT, reasons_json TEXT, comment_safe TEXT, created_at TEXT, UNIQUE (tenant_id, conversation_id, message_id, user_id_opaque))")
        conn.execute("CREATE TABLE ai_diagnostic_cases (id TEXT PRIMARY KEY, tenant_id TEXT, conversation_id TEXT, title TEXT, status TEXT, symptom_safe TEXT, scope_json TEXT, plan_json TEXT, evidence_json TEXT, conclusion_json TEXT, handoff_json TEXT, created_by TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("CREATE TABLE ai_diagnostic_runs (id TEXT PRIMARY KEY, case_id TEXT, tenant_id TEXT, state TEXT, playbook_code TEXT, vendor TEXT, platform TEXT, device_id TEXT, read_only INTEGER, started_at TEXT, finished_at TEXT, error_code TEXT)")
        conn.execute("CREATE TABLE ai_diagnostic_steps (id TEXT PRIMARY KEY, run_id TEXT, tenant_id TEXT, step_no INTEGER, purpose TEXT, command_safe TEXT, target_safe TEXT, status TEXT, evidence_json TEXT, duration_ms INTEGER, error_code TEXT, created_at TEXT, UNIQUE (run_id, step_no))")

        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)

        tenant_a, tenant_b = "api008-tenant-a", "api008-tenant-b"
        alice, bob = "alice", "bob"
        alice_agent = opaque_user_id(alice, tenant_id=tenant_a, task_id="agent-owner")
        bob_agent = opaque_user_id(bob, tenant_id=tenant_a, task_id="agent-owner")
        alice_owner = opaque_user_id(alice, tenant_id=tenant_a, task_id="conversation-owner")
        alice_diag = opaque_user_id(alice, tenant_id=tenant_a, task_id="diagnostic-owner")
        conn.execute("INSERT INTO ai_agent_run (id, agent_id, tenant_id, user_id_opaque, question, status, started_at) VALUES ('run-a', 'agent', ?, ?, 'q-a', 'finished', 'now')", (tenant_a, alice_agent))
        conn.execute("INSERT INTO ai_agent_step (id, run_id, tenant_id, user_id_opaque, step_no, step_type, status, started_at) VALUES ('step-a', 'run-a', ?, ?, 1, 'final_answer', 'success', 'now')", (tenant_a, alice_agent))
        conn.execute("INSERT INTO ai_tool_calls (id, task_id, tenant_id, user_id_opaque, step_no, tool_name, status, policy_decision, created_at) VALUES ('tool-a', 'run-a', ?, ?, 1, 'search_ip', 'success', 'allow', 'now')", (tenant_a, alice_agent))
        conn.execute("INSERT INTO ai_evidence (id, task_id, tool_call_id, tenant_id, user_id_opaque, source_type, source_id, confidence, collected_at) VALUES ('ev-a', 'run-a', 'tool-a', ?, ?, 'cmdb', 'device-a', 1, 'now')", (tenant_a, alice_agent))
        conn.execute("INSERT INTO ai_conversations (id, tenant_id, user_id_opaque, title, status, context_budget, created_at, updated_at) VALUES ('conv-a', ?, ?, 'A', 'active', 32768, 'now', 'now')", (tenant_a, alice_owner))
        conn.execute("INSERT INTO ai_messages (id, conversation_id, sequence_no, role, content_safe, citations_json, token_count, created_at) VALUES ('msg-a', 'conv-a', 1, 'user', 'safe', '[]', 1, 'now')")
        conn.execute("INSERT INTO ai_diagnostic_cases (id, tenant_id, title, status, symptom_safe, scope_json, plan_json, evidence_json, conclusion_json, handoff_json, created_by, created_by_opaque, created_at, updated_at) VALUES ('case-a', ?, 'A', 'open', '', '{}', '[]', '[]', '{}', '{}', ?, ?, 'now', 'now')", (tenant_a, alice_diag, alice_diag))
        # Keep the entire probe inside one transaction.  Committing here would
        # leave the ad-hoc schema behind and defeat the rollback guarantee.

        conversation_service.get_db_connection = lambda: _SameConnection(conn)
        security_service.get_db_connection = lambda: _SameConnection(conn)
        agent_api.get_db_connection = lambda: _SameConnection(conn)

        if conversation_service.get_task(task_id="missing", tenant_id=tenant_b, user_id=bob) is not None:
            raise AssertionError("foreign task unexpectedly visible")
        try:
            conversation_service.create_task(tenant_id=tenant_b, user_id=bob, scene="chat", conversation_id="conv-a")
        except LookupError:
            pass
        else:
            raise AssertionError("foreign conversation accepted for task")

        try:
            security_service.record_feedback(tenant_id=tenant_a, conversation_id="conv-a", message_id="msg-a", user_id=bob, rating="positive")
        except LookupError:
            pass
        else:
            raise AssertionError("foreign conversation feedback accepted")

        try:
            security_service.handoff_case(tenant_id=tenant_a, case_id="case-a", user_id=bob, handoff={"summary": "x"})
        except LookupError:
            pass
        else:
            raise AssertionError("foreign diagnostic case accepted")

        try:
            security_service.create_diagnostic_case(
                tenant_id=tenant_a,
                user_id=bob,
                title="foreign conversation",
                conversation_id="conv-a",
            )
        except LookupError:
            pass
        else:
            raise AssertionError("foreign conversation linked to diagnostic case")

        trace = agent_api.get_agent_run_trace("run-a", user={"username": alice, "tenant_id": tenant_a})
        if trace["run_id"] != "run-a" or len(trace["tool_calls"]) != 1 or len(trace["evidence"]) != 1:
            raise AssertionError(f"scoped agent trace missing: {trace}")
        try:
            agent_api.get_agent_run_trace("run-a", user={"username": bob, "tenant_id": tenant_a})
        except Exception as exc:
            if getattr(exc, "status_code", None) != 404:
                raise
        else:
            raise AssertionError("foreign agent trace unexpectedly visible")

        return {
            "postgresql": True,
            "migration_idempotent": True,
            "conversation_task_scope": True,
            "feedback_scope": True,
            "diagnostic_case_scope": True,
            "agent_trace_tool_evidence_scope": True,
            "production_database_write": False,
            "rollback": "transaction_rollback",
        }
    finally:
        conversation_service.get_db_connection = originals["conversation"]
        security_service.get_db_connection = originals["security"]
        agent_api.get_db_connection = originals["agents"]
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
