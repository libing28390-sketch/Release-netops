"""Harden the WAN monitoring model for P0 collection and alert semantics."""

from __future__ import annotations


VERSION = 65
NAME = "wan_p0_hardening"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(cursor, table: str, name: str, definition: str, use_pg: bool) -> None:
    if name not in _columns(cursor, table, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    json_type = "JSONB" if use_pg else "TEXT"
    json_default = "'{}'::jsonb" if use_pg else "'{}'"
    for name, definition in (
        ("in_octets_hc", "NUMERIC(20,0)"),
        ("out_octets_hc", "NUMERIC(20,0)"),
        ("in_octets_32", "BIGINT"),
        ("out_octets_32", "BIGINT"),
        ("counter_width", "INTEGER"),
        ("counter_source", "TEXT DEFAULT 'unknown'"),
        ("counter_quality", "TEXT DEFAULT 'unknown'"),
        ("device_uptime_cs", "BIGINT"),
    ):
        _ensure_column(cursor, "wan_link_samples_1m", name, definition, use_pg)

    _ensure_column(cursor, "wan_alert_events", "direction", "TEXT DEFAULT ''", use_pg)
    _ensure_column(cursor, "wan_alert_events", "acknowledged_at", "TEXT", use_pg)
    _ensure_column(cursor, "wan_alert_events", "acknowledged_by", "TEXT DEFAULT ''", use_pg)
    _ensure_column(cursor, "wan_alert_events", "closed_at", "TEXT", use_pg)
    _ensure_column(cursor, "wan_alert_events", "closed_by", "TEXT DEFAULT ''", use_pg)
    _ensure_column(cursor, "wan_alert_events", "updated_at", "TEXT", use_pg)

    # The legacy event_key uniqueness prevented a recovered rule from firing
    # again. PostgreSQL uses the authoritative partial index; SQLite keeps the
    # old unique column but the service generates a new event key per episode.
    if use_pg:
        cursor.execute("ALTER TABLE wan_alert_events DROP CONSTRAINT IF EXISTS wan_alert_events_event_key_key")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wan_active_event "
        "ON wan_alert_events(link_id, metric) WHERE status = 'firing'"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_samples_quality ON wan_link_samples_1m(link_id, collection_status, sampled_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wan_events_direction ON wan_alert_events(link_id, direction, started_at DESC)")

    # Keep the migration self-contained for installations that already have a
    # partially-created table and make JSON columns non-null at the application
    # boundary rather than rewriting historical records.
    cursor.execute(
        f"UPDATE wan_link_samples_1m SET quality_flags = {json_default} "
        "WHERE quality_flags IS NULL"
    )
