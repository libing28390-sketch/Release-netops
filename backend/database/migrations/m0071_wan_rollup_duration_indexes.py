"""Add auditable high-load durations and PostgreSQL time-series indexes."""

from __future__ import annotations


VERSION = 71
NAME = "wan_rollup_duration_indexes"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    for table in ("wan_link_samples_5m", "wan_link_samples_1h", "wan_link_samples_daily"):
        columns = _columns(cursor, table, use_pg)
        for name in ("valid_sample_count", "high_70_minutes", "high_85_minutes", "high_95_minutes"):
            if name not in columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} BIGINT NOT NULL DEFAULT 0")
    if use_pg:
        cursor.execute("CREATE INDEX IF NOT EXISTS brin_wan_samples_1m_partitioned_time ON wan_link_samples_1m_partitioned USING BRIN (sampled_at)")
