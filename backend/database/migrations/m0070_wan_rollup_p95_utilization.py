"""Add P95 utilization columns to existing WAN rollup tables."""

from __future__ import annotations


VERSION = 70
NAME = "wan_rollup_p95_utilization"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def upgrade(cursor, use_pg: bool) -> None:
    for table in ("wan_link_samples_5m", "wan_link_samples_1h", "wan_link_samples_daily"):
        columns = _columns(cursor, table, use_pg)
        if "p95_download_util_pct" not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN p95_download_util_pct NUMERIC(7,3)")
        if "p95_upload_util_pct" not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN p95_upload_util_pct NUMERIC(7,3)")
