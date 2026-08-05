"""Add tenant scope to IPAM DHCP leases for safe prefix association."""

from __future__ import annotations


VERSION = 33
NAME = "dhcp_lease_tenant_scope"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {row[0] for row in cursor.fetchall()}
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def upgrade(cursor, use_pg: bool) -> None:
    if "tenant_id" not in _columns(cursor, "ipam_dhcp_leases", use_pg):
        cursor.execute(
            "ALTER TABLE ipam_dhcp_leases ADD COLUMN tenant_id TEXT DEFAULT 'tenant-default'"
        )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ipam_dhcp_tenant_address "
        "ON ipam_dhcp_leases(tenant_id, address)"
    )
