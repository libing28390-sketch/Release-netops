"""Normalize legacy outbound probe flags to PostgreSQL BOOLEAN columns."""

VERSION = 26
NAME = "outbound_postgresql_flags"


def _data_type(cursor, table: str, column: str) -> str | None:
    row = cursor.execute(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s AND column_name = %s",
        (table, column),
    ).fetchone()
    return str(row[0]).lower() if row else None


def _to_boolean(cursor, table: str, column: str, default_sql: str) -> None:
    if _data_type(cursor, table, column) == "boolean":
        return
    cursor.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
    cursor.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BOOLEAN USING ({column} <> 0)"
    )
    cursor.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {default_sql}")


def upgrade(cursor, _use_pg: bool) -> None:
    pass
    # m0024/m0025 were previously applied in some PostgreSQL installations
    # with integer flags. Convert only when needed, so fresh installations
    # remain idempotent.
    for table, columns in {
        "outbound_probe_targets": {"is_active": "TRUE", "enabled": "TRUE"},
        "outbound_probe_samples": {"public_ip_changed": "FALSE"},
        "outbound_probe_nodes": {"enabled": "TRUE"},
        "outbound_probe_runs": {"public_ip_changed": "FALSE"},
        "outbound_probe_results": {"success": "FALSE"},
        "outbound_egress_ip_events": {"consistent": "FALSE"},
    }.items():
        for column, default_sql in columns.items():
            _to_boolean(cursor, table, column, default_sql)
