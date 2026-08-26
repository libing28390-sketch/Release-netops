"""Add indexes used by the paginated IPAM inventory and prefix views."""

from __future__ import annotations


VERSION = 45
NAME = "ipam_inventory_indexes"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_network_endpoints_active_seen_ip "
        "ON network_endpoints(is_active, last_seen, ip)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ip_addresses_subnet_status_address "
        "ON ip_addresses(subnet_id, status, address)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_prefixes_site_status_prefix "
        "ON prefixes(site_id, status, prefix)"
    )
