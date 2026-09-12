"""Enterprise CMDB/IPAM Phase 7 & 8 distributed locks table migration."""

VERSION = 9
NAME = "enterprise_cmdb_ipam_phase7_phase8"


def upgrade(cursor, use_pg: bool) -> None:
    # Create scheduler_locks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduler_locks (
            lock_name TEXT PRIMARY KEY,
            locked_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    # Add index for expires_at
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduler_locks_expires ON scheduler_locks(expires_at)")
