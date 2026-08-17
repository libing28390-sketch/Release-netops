"""PostgreSQL-only API-009 task execution state-machine probe."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ai.security.tokenization import opaque_user_id  # noqa: E402
from ai.services import conversation_service  # noqa: E402
from database import core  # noqa: E402
from database.migrations import m0147_ai_task_execution_guards as migration  # noqa: E402


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

    def commit(self):
        # Service methods commit per operation in production.  Keep the probe
        # inside its outer transaction so SET LOCAL search_path remains scoped.
        return None

    def rollback(self):
        return None


def _now(offset: int = 0) -> str:
    return (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=offset)).isoformat()


def _insert_task(conn, *, task_id: str, tenant: str, user: str, state: str = "queued", max_steps: int = 4, max_tools: int = 4, deadline: str | None = None, cancel: int = 0) -> None:
    owner = opaque_user_id(user, tenant_id=tenant, task_id=task_id)
    conn.execute(
        """INSERT INTO ai_tasks
           (id, conversation_id, tenant_id, user_id_opaque, scene, state,
            max_steps, max_tool_calls, deadline_at, cancel_requested, created_at)
           VALUES (?, NULL, ?, ?, 'probe', ?, ?, ?, ?, ?, ?)""",
        (task_id, tenant, owner, state, max_steps, max_tools, deadline, cancel, _now()),
    )


def run() -> dict[str, Any]:
    if not core._USE_PG:
        raise SystemExit("API-009 PostgreSQL probe refused: DATABASE_URL is not PostgreSQL")
    conn = core.get_db_connection()
    schema = f"api009_probe_{uuid.uuid4().hex[:10]}"
    original = conversation_service.get_db_connection
    try:
        conn.execute("BEGIN")
        conn.execute(f'CREATE SCHEMA "{schema}"')
        conn.execute(f'SET LOCAL search_path TO "{schema}"')
        conn.execute(
            """CREATE TABLE ai_tasks (
                id TEXT PRIMARY KEY, conversation_id TEXT, tenant_id TEXT NOT NULL,
                user_id_opaque TEXT NOT NULL, scene TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued', max_steps INTEGER NOT NULL DEFAULT 8,
                max_tool_calls INTEGER NOT NULL DEFAULT 12, deadline_at TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0, started_at TEXT,
                finished_at TEXT, error_code TEXT, created_at TEXT NOT NULL)"""
        )
        conn.execute("CREATE TABLE ai_tool_calls (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, step_no INTEGER NOT NULL)")
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        columns = {row[0] for row in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'ai_tasks'").fetchall()}
        if not {"current_steps", "current_tool_calls", "execution_token", "version", "updated_at", "cancel_requested_at"}.issubset(columns):
            raise AssertionError(f"m0147 columns missing: {sorted(columns)}")

        tenant, user, foreign_user = "api009-tenant", "alice", "bob"
        _insert_task(conn, task_id="task-step", tenant=tenant, user=user, max_steps=2, max_tools=4, deadline=_now(300))
        _insert_task(conn, task_id="task-tool", tenant=tenant, user=user, max_steps=4, max_tools=1, deadline=_now(300))
        _insert_task(conn, task_id="task-timeout", tenant=tenant, user=user, deadline=_now(-30))
        _insert_task(conn, task_id="task-cancel", tenant=tenant, user=user, deadline=_now(300))
        _insert_task(conn, task_id="task-complete", tenant=tenant, user=user, max_steps=4, max_tools=4, deadline=_now(300))
        _insert_task(conn, task_id="task-running-timeout", tenant=tenant, user=user, deadline=_now(300))
        _insert_task(conn, task_id="task-fail", tenant=tenant, user=user, deadline=_now(300))
        # Keep the temporary schema and its SET LOCAL search_path inside the
        # outer transaction; committing would reset search_path to public.

        conversation_service.get_db_connection = lambda: _SameConnection(conn)

        first_claim = conversation_service.claim_task(task_id="task-step", tenant_id=tenant, user_id=user)
        if not first_claim or conversation_service.claim_task(task_id="task-step", tenant_id=tenant, user_id=user) is not None:
            raise AssertionError("queued task was claimed more than once")
        if conversation_service.claim_task(task_id="task-step", tenant_id=tenant, user_id=foreign_user) is not None:
            raise AssertionError("foreign user claimed task")

        step_one = conversation_service.consume_task_step(task_id="task-step", tenant_id=tenant, user_id=user, execution_token=first_claim["execution_token"])
        step_two = conversation_service.consume_task_step(task_id="task-step", tenant_id=tenant, user_id=user, execution_token=first_claim["execution_token"])
        if not step_one or step_one["current_steps"] != 1 or not step_two or step_two["state"] != "step_limit":
            raise AssertionError(f"step budget failed: {step_one} / {step_two}")
        if conversation_service.complete_task(task_id="task-step", tenant_id=tenant, user_id=user, execution_token=first_claim["execution_token"]):
            raise AssertionError("step-limited task completed")

        tool_claim = conversation_service.claim_task(task_id="task-tool", tenant_id=tenant, user_id=user)
        tool_one = conversation_service.consume_task_tool_call(task_id="task-tool", tenant_id=tenant, user_id=user, execution_token=tool_claim["execution_token"])
        if not tool_one or tool_one["state"] != "budget_exceeded":
            raise AssertionError(f"tool budget failed: {tool_one}")

        if conversation_service.claim_task(task_id="task-timeout", tenant_id=tenant, user_id=user) is not None:
            raise AssertionError("expired task was claimed")
        timeout_state = conversation_service.get_task(task_id="task-timeout", tenant_id=tenant, user_id=user)
        if not timeout_state or timeout_state["state"] != "timeout":
            raise AssertionError(f"timeout state failed: {timeout_state}")

        if not conversation_service.request_cancel(task_id="task-cancel", tenant_id=tenant, user_id=user):
            raise AssertionError("cancel request was not recorded")
        if not conversation_service.request_cancel(task_id="task-cancel", tenant_id=tenant, user_id=user):
            raise AssertionError("cancel request was not idempotent")
        if conversation_service.claim_task(task_id="task-cancel", tenant_id=tenant, user_id=user) is not None:
            raise AssertionError("cancelled task was claimed")
        cancel_state = conversation_service.get_task(task_id="task-cancel", tenant_id=tenant, user_id=user)
        if not cancel_state or cancel_state["state"] != "cancelled":
            raise AssertionError(f"cancel state failed: {cancel_state}")

        complete_claim = conversation_service.claim_task(task_id="task-complete", tenant_id=tenant, user_id=user)
        if not complete_claim or not conversation_service.complete_task(task_id="task-complete", tenant_id=tenant, user_id=user, execution_token=complete_claim["execution_token"]):
            raise AssertionError("running task did not complete")
        if conversation_service.complete_task(task_id="task-complete", tenant_id=tenant, user_id=user, execution_token=complete_claim["execution_token"]):
            raise AssertionError("terminal task completed twice")

        running_timeout_claim = conversation_service.claim_task(task_id="task-running-timeout", tenant_id=tenant, user_id=user)
        conn.execute("UPDATE ai_tasks SET deadline_at = ? WHERE id = 'task-running-timeout'", (_now(-30),))
        timeout_running = conversation_service.reconcile_task(task_id="task-running-timeout", tenant_id=tenant, user_id=user)
        if not running_timeout_claim or not timeout_running or timeout_running["state"] != "timeout":
            raise AssertionError(f"running timeout state failed: {timeout_running}")

        fail_claim = conversation_service.claim_task(task_id="task-fail", tenant_id=tenant, user_id=user)
        if not fail_claim or not conversation_service.fail_task(task_id="task-fail", tenant_id=tenant, user_id=user, execution_token=fail_claim["execution_token"], error_code="PROBE_FAILED"):
            raise AssertionError("running task did not fail")
        if conversation_service.fail_task(task_id="task-fail", tenant_id=tenant, user_id=user, execution_token=fail_claim["execution_token"], error_code="PROBE_FAILED"):
            raise AssertionError("failed task transitioned twice")

        return {
            "postgresql": True,
            "migration_idempotent": True,
            "single_claim": True,
            "step_budget": True,
            "tool_budget": True,
            "timeout_terminal": True,
            "running_timeout_terminal": True,
            "cancel_idempotent": True,
            "completion_once": True,
            "failure_once": True,
            "foreign_scope_rejected": True,
            "production_database_write": False,
            "rollback": "transaction_rollback",
        }
    finally:
        conversation_service.get_db_connection = original
        conn.rollback()
        conn.close()


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, sort_keys=True))
