"""API-008: tenant/user scope for sessions, agent traces, tools and evidence.

The V1 AI tables predate the V2 authorization boundary.  This migration is
additive: legacy columns remain for compatibility, while new writes and
readers use stable opaque principals.  PostgreSQL is the release authority;
the SQLite branch only keeps migration discovery/import tests working.
"""

from __future__ import annotations

import hashlib


VERSION = 146
NAME = "ai_session_scope_hardening"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    try:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]) for row in rows}

    except Exception:
        return set()


def _ensure_columns(cursor, table: str, definitions: dict[str, str], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    if not existing:
        return
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _opaque_user(tenant_id: str | None, user_id: str | None) -> str:
    tenant = str(tenant_id or "tenant-default")
    user = str(user_id or "anonymous")
    digest = hashlib.sha256(f"{tenant}:agent-owner:{user}".encode("utf-8")).hexdigest()[:32]
    return f"nxa_user_{digest}"


def _backfill_agent_scope(cursor) -> None:
    try:
        rows = cursor.execute("SELECT id, tenant_id, user_id FROM ai_agent_run").fetchall()
    except Exception:
        return
    for row in rows:
        tenant = str(row[1] or "tenant-default")
        cursor.execute(
            "UPDATE ai_agent_run SET tenant_id = ?, user_id_opaque = COALESCE(NULLIF(user_id_opaque, ''), ?) WHERE id = ?",
            (tenant, _opaque_user(tenant, row[2]), row[0]),
        )


def _copy_scope_from_parent(cursor, child: str, parent: str, key: str) -> None:
    # Correlated subqueries work on both PostgreSQL and the compatibility
    # SQLite fixtures and avoid a dialect-specific UPDATE ... FROM branch.
    try:
        cursor.execute(
            f"""UPDATE {child}
               SET tenant_id = COALESCE((SELECT p.tenant_id FROM {parent} p WHERE p.id = {child}.{key}), tenant_id),
                   user_id_opaque = COALESCE((SELECT p.user_id_opaque FROM {parent} p WHERE p.id = {child}.{key}), user_id_opaque)
               WHERE {key} IS NOT NULL"""
        )
    except Exception:
        return


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(
        cursor,
        "ai_agent_run",
        {"tenant_id": "TEXT NOT NULL DEFAULT 'tenant-default'", "user_id_opaque": "TEXT"},
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_agent_step",
        {"tenant_id": "TEXT NOT NULL DEFAULT 'tenant-default'", "user_id_opaque": "TEXT"},
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_tool_calls",
        {"tenant_id": "TEXT NOT NULL DEFAULT 'tenant-default'", "user_id_opaque": "TEXT"},
        use_pg,
    )
    _ensure_columns(
        cursor,
        "ai_evidence",
        {"tenant_id": "TEXT NOT NULL DEFAULT 'tenant-default'", "user_id_opaque": "TEXT"},
        use_pg,
    )
    _ensure_columns(cursor, "ai_diagnostic_cases", {"created_by_opaque": "TEXT"}, use_pg)
    _ensure_columns(cursor, "ai_diagnostic_runs", {"user_id_opaque": "TEXT"}, use_pg)
    _ensure_columns(cursor, "ai_diagnostic_steps", {"user_id_opaque": "TEXT"}, use_pg)

    _backfill_agent_scope(cursor)
    _copy_scope_from_parent(cursor, "ai_agent_step", "ai_agent_run", "run_id")
    _copy_scope_from_parent(cursor, "ai_tool_calls", "ai_tasks", "task_id")
    _copy_scope_from_parent(cursor, "ai_evidence", "ai_tasks", "task_id")

    try:
        rows = cursor.execute("SELECT id, tenant_id, created_by FROM ai_diagnostic_cases").fetchall()
        for row in rows:
            cursor.execute(
                "UPDATE ai_diagnostic_cases SET created_by_opaque = COALESCE(NULLIF(created_by_opaque, ''), ?) WHERE id = ?",
                (_opaque_user(row[1], row[2]), row[0]),
            )
    except Exception:
        pass
    try:
        cursor.execute(
            """UPDATE ai_diagnostic_runs
               SET user_id_opaque = COALESCE(NULLIF(user_id_opaque, ''),
                   (SELECT c.created_by_opaque FROM ai_diagnostic_cases c WHERE c.id = ai_diagnostic_runs.case_id))"""
        )
        cursor.execute(
            """UPDATE ai_diagnostic_steps
               SET user_id_opaque = COALESCE(NULLIF(user_id_opaque, ''),
                   (SELECT r.user_id_opaque FROM ai_diagnostic_runs r WHERE r.id = ai_diagnostic_steps.run_id))"""
        )
    except Exception:
        pass

    indexes = (
        "CREATE INDEX IF NOT EXISTS ix_ai_agent_run_scope ON ai_agent_run(tenant_id, user_id_opaque, status, started_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_agent_step_scope ON ai_agent_step(tenant_id, user_id_opaque, run_id, step_no)",
        "CREATE INDEX IF NOT EXISTS ix_ai_tool_calls_scope ON ai_tool_calls(tenant_id, user_id_opaque, task_id, step_no)",
        "CREATE INDEX IF NOT EXISTS ix_ai_evidence_scope ON ai_evidence(tenant_id, user_id_opaque, task_id, collected_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_diagnostic_case_scope ON ai_diagnostic_cases(tenant_id, created_by_opaque, status, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_diagnostic_run_scope ON ai_diagnostic_runs(tenant_id, user_id_opaque, state, started_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_diagnostic_step_scope ON ai_diagnostic_steps(tenant_id, user_id_opaque, run_id, step_no)",
    )
    for statement in indexes:
        try:
            cursor.execute(statement)
        except Exception:
            # A partially provisioned legacy table should not prevent the
            # remaining additive scopes from being applied on next startup.
            continue


def downgrade(cursor, use_pg: bool) -> None:
    # Scope columns/indexes are security evidence.  Rollback disables new
    # readers/writers; dropping them would make historical rows ambiguous.
    return None
