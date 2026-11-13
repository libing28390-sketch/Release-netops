"""Remove the obsolete tenant/VRF IP uniqueness index after address-space migration."""

from __future__ import annotations

VERSION = 320
NAME = "ipam_address_space_unique_index_bootstrap"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("IPAM address-space uniqueness requires PostgreSQL")

    # schema._init_db_logic used to recreate this pre-address-space index before
    # running versioned migrations. It incorrectly collides equal addresses in
    # distinct address spaces for the same tenant/VRF.
    cursor.execute("DROP INDEX IF EXISTS uq_ip_addresses_scope_active")
