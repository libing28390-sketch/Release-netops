"""
Migration 0003 — IPAM module database schema changes.

Adds columns to `prefixes` table and creates `ipam_pools`, `ipam_vips`,
and `ipam_dhcp_leases` tables. Idempotent and compatible with both SQLite and PostgreSQL.
"""

VERSION = 3
NAME = "ipam_refactor"


def _column_exists(cursor, table_name: str, column_name: str, use_pg: bool) -> bool:
    if use_pg:
        cursor.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            (table_name, column_name)
        )
        return cursor.fetchone() is not None
    else:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns


def upgrade(cursor, use_pg: bool) -> None:
    # 1. Add columns to prefixes table
    columns_to_add = [
        ("name", "TEXT DEFAULT ''"),
        ("gateway", "TEXT DEFAULT ''"),
        ("description", "TEXT DEFAULT ''"),
        ("created_at", "TEXT DEFAULT ''"),
        ("updated_at", "TEXT DEFAULT ''")
    ]
    
    for col_name, col_def in columns_to_add:
        if not _column_exists(cursor, "prefixes", col_name, use_pg):
            cursor.execute(f"ALTER TABLE prefixes ADD COLUMN {col_name} {col_def}")

    # 2. Create ipam_pools table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ipam_pools (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        prefix_id TEXT NOT NULL,
        start_ip TEXT NOT NULL,
        end_ip TEXT NOT NULL,
        description TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        tenant_id TEXT DEFAULT 'tenant-default',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (prefix_id) REFERENCES prefixes (id) ON DELETE CASCADE,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE SET NULL
    )
    """)

    # 3. Create ipam_vips table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ipam_vips (
        id TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        vip_type TEXT NOT NULL,
        device_id TEXT,
        interface_name TEXT DEFAULT '',
        description TEXT DEFAULT '',
        real_servers TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        tenant_id TEXT DEFAULT 'tenant-default',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE SET NULL,
        FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE SET NULL
    )
    """)

    # 4. Create ipam_dhcp_leases table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ipam_dhcp_leases (
        id TEXT PRIMARY KEY,
        address TEXT NOT NULL,
        mac_address TEXT NOT NULL,
        hostname TEXT DEFAULT '',
        dhcp_server TEXT DEFAULT '',
        lease_state TEXT DEFAULT 'active',
        lease_start TEXT DEFAULT '',
        lease_end TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # 5. Create indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ipam_pools_prefix ON ipam_pools(prefix_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ipam_vips_device ON ipam_vips(device_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ipam_dhcp_mac ON ipam_dhcp_leases(mac_address)")
