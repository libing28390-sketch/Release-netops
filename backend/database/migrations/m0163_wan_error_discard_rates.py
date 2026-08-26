"""Add per-second WAN error/discard rates alongside counter deltas.

The raw WAN model already persisted monotonic error/discard increments.  This
additive migration keeps the sampling interval explicit by storing the
derived rates too, so a 30-second poll and a five-minute backfill can be
compared without re-guessing the interval later.  Rollups retain the average
rate while their existing total columns remain the authoritative count.
"""

from __future__ import annotations


VERSION = 163
NAME = "wan_error_discard_rates"


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
    columns = _columns(cursor, table, use_pg)
    if not columns:
        # A deliberately minimal legacy/test schema may not have reached the
        # rollup migration yet.  The next migration run will revisit this
        # module after the table is created.
        return
    if name not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    rate_type = "NUMERIC(20,6)"
    raw_tables = ["wan_link_samples_1m"]
    # SQLite has a compatibility projection; adding the columns keeps direct
    # local/test queries schema-compatible with PostgreSQL.
    raw_tables.append("wan_link_samples_1m_partitioned")
    for table in raw_tables:
        try:
            for name, definition in (
                ("in_errors", "BIGINT"),
                ("out_errors", "BIGINT"),
                ("in_discards", "BIGINT"),
                ("out_discards", "BIGINT"),
                ("in_error_rate", rate_type),
                ("out_error_rate", rate_type),
                ("in_discard_rate", rate_type),
                ("out_discard_rate", rate_type),
            ):
                _ensure_column(cursor, table, name, definition, use_pg)
        except Exception:
            # The partitioned compatibility table is not present on some
            # legacy SQLite databases.  The authoritative raw table above is
            # still upgraded; PostgreSQL errors must propagate.
            if use_pg or table == "wan_link_samples_1m":
                raise
    for table in ("wan_link_samples_5m", "wan_link_samples_1h", "wan_link_samples_daily"):
        for name in ("avg_in_error_rate", "avg_out_error_rate", "avg_in_discard_rate", "avg_out_discard_rate"):
            _ensure_column(cursor, table, name, rate_type, use_pg)


__all__ = ["VERSION", "NAME", "upgrade"]
