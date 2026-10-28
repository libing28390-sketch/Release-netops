"""Harden WAN P1/P2 operational traceability and long-running rollups."""

from __future__ import annotations


VERSION = 69
NAME = "wan_p1_p2_hardening"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def _ensure_column(cursor, table: str, name: str, definition: str, use_pg: bool) -> None:
    if name not in _columns(cursor, table, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    time_type = "TIMESTAMPTZ"
    json_type = "JSONB"
    json_default = "'{}'::jsonb"

    for name, definition in (
        ("device_id", "TEXT DEFAULT ''"),
        ("link_group_id", "TEXT DEFAULT ''"),
        ("recurrence", "TEXT DEFAULT 'once'"),
        ("deleted_at", f"{time_type}"),
    ):
        _ensure_column(cursor, "wan_maintenance_windows", name, definition, use_pg)

    for name, definition in (
        ("report_version", "TEXT DEFAULT 'wan-report-v1'"),
        ("data_cutoff_at", f"{time_type}"),
        ("exported_at", f"{time_type}"),
        ("exported_by", "TEXT DEFAULT ''"),
    ):
        _ensure_column(cursor, "wan_report_runs", name, definition, use_pg)

    for name, definition in (
        ("route_evidence_json", f"{json_type} NOT NULL DEFAULT {json_default}"),
        ("updated_by", "TEXT DEFAULT ''"),
    ):
        _ensure_column(cursor, "wan_probe_bindings", name, definition, use_pg)

    for table in ("wan_link_samples_5m", "wan_link_samples_1h", "wan_link_samples_daily"):
        _ensure_column(cursor, table, "p95_download_util_pct", "NUMERIC(7,3)", use_pg)
        _ensure_column(cursor, table, "p95_upload_util_pct", "NUMERIC(7,3)", use_pg)

    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_probe_binding_audit (
            id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, action TEXT NOT NULL,
            actor_id TEXT DEFAULT '', actor_name TEXT DEFAULT '',
            before_json {json_type} NOT NULL DEFAULT {json_default},
            after_json {json_type} NOT NULL DEFAULT {json_default},
            created_at {time_type} NOT NULL
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_probe_binding_audit ON wan_probe_binding_audit(binding_id, created_at DESC)")

    cursor.execute(
        f"""CREATE TABLE IF NOT EXISTS wan_retention_runs (
            id TEXT PRIMARY KEY, started_at {time_type} NOT NULL,
            completed_at {time_type}, status TEXT NOT NULL, policy_json {json_type} NOT NULL DEFAULT {json_default},
            deleted_json {json_type} NOT NULL DEFAULT {json_default}, error_message TEXT DEFAULT ''
        )"""
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_retention_runs_time ON wan_retention_runs(started_at DESC)")
