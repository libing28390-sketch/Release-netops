"""Add durable discovery-run idempotency, lease, retry and evidence metadata."""

VERSION = 11
NAME = "topology_run_leases"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_columns(cursor, table: str, definitions: list[tuple[str, str]], use_pg: bool) -> None:
    existing = _columns(cursor, table, use_pg)
    for name, definition in definitions:
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_columns(cursor, "topology_discovery_runs", [
        ("idempotency_key", "TEXT DEFAULT ''"),
        ("lease_owner", "TEXT DEFAULT ''"),
        ("lease_expires_at", "TEXT"),
        ("heartbeat_at", "TEXT"),
        ("attempt_count", "INTEGER DEFAULT 0"),
        ("max_attempts", "INTEGER DEFAULT 2"),
        ("timeout_seconds", "INTEGER DEFAULT 300"),
        ("last_error_code", "TEXT DEFAULT ''"),
    ], use_pg)
    _ensure_columns(cursor, "topology_discovery_run_devices", [
        ("attempt_count", "INTEGER DEFAULT 0"),
        ("last_attempt_at", "TEXT"),
    ], use_pg)

    # Partial uniqueness keeps legacy rows with an empty key valid while making
    # retries of the same API request converge on one durable run.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_topology_runs_idempotency "
        "ON topology_discovery_runs(idempotency_key) "
        "WHERE idempotency_key <> ''"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_runs_lease "
        "ON topology_discovery_runs(status, lease_expires_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_run_devices_status "
        "ON topology_discovery_run_devices(run_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_topology_observations_run_collected "
        "ON topology_observations(discovery_run_id, collected_at)"
    )
