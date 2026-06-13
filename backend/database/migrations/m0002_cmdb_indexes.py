"""
Migration 0002 — CMDB tenant/credential lookup indexes.

Adds covering indexes for the foreign keys most frequently filtered by the new
CMDB CRUD endpoints (tenant scoping and credential-vault joins). All statements
are idempotent and backend-agnostic.
"""

VERSION = 2
NAME = "cmdb_indexes"

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_sites_tenant ON sites(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_vrfs_tenant ON vrfs(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_vlans_tenant ON vlans(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_devices_credential ON devices(credential_id)",
)


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    for stmt in _INDEXES:
        cursor.execute(stmt)
