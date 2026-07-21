"""Add public_ip_source and public_ip_verified columns to outbound_probe_runs and outbound_egress_ip_events."""

VERSION = 27
NAME = "outbound_egress_metadata"


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
    # Add columns to outbound_probe_runs
    cols_runs = _columns(cursor, "outbound_probe_runs", use_pg)
    if "public_ip_source" not in cols_runs:
        cursor.execute("ALTER TABLE outbound_probe_runs ADD COLUMN public_ip_source VARCHAR(32) DEFAULT 'unknown'")
    if "public_ip_verified" not in cols_runs:
        # SQLite uses standard BOOLEAN mapping
        default_val = "FALSE" if use_pg else "0"
        cursor.execute(f"ALTER TABLE outbound_probe_runs ADD COLUMN public_ip_verified BOOLEAN DEFAULT {default_val}")

    # Add columns to outbound_egress_ip_events
    cols_events = _columns(cursor, "outbound_egress_ip_events", use_pg)
    if "public_ip_source" not in cols_events:
        cursor.execute("ALTER TABLE outbound_egress_ip_events ADD COLUMN public_ip_source VARCHAR(32) DEFAULT 'unknown'")
    if "public_ip_verified" not in cols_events:
        default_val = "FALSE" if use_pg else "0"
        cursor.execute(f"ALTER TABLE outbound_egress_ip_events ADD COLUMN public_ip_verified BOOLEAN DEFAULT {default_val}")
