"""Index the association lookups used while deleting inventory assets."""

from __future__ import annotations


VERSION = 282
NAME = "asset_delete_lookup_indexes"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("asset delete lookup indexes require PostgreSQL")

    indexes = (
        ("idx_ip_addresses_device_id", "ip_addresses", "device_id"),
        ("idx_ip_addresses_interface_id", "ip_addresses", "interface_id"),
        ("idx_ip_inventory_device_id", "ip_inventory", "device_id"),
        ("idx_prefixes_gateway_device_id", "prefixes", "gateway_device_id"),
        ("idx_prefixes_gateway_interface_id", "prefixes", "gateway_interface_id"),
        ("idx_topo_links_target_device_id", "topology_links", "target_device_id"),
        ("idx_device_telemetry_hourly_device_id", "device_telemetry_hourly", "device_id"),
        ("idx_pam_session_tokens_asset_id", "pam_session_tokens", "asset_id"),
    )
    for index_name, table_name, column_name in indexes:
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({column_name})"
        )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    index_names = (
        "idx_ip_addresses_device_id",
        "idx_ip_addresses_interface_id",
        "idx_ip_inventory_device_id",
        "idx_prefixes_gateway_device_id",
        "idx_prefixes_gateway_interface_id",
        "idx_topo_links_target_device_id",
        "idx_device_telemetry_hourly_device_id",
        "idx_pam_session_tokens_asset_id",
    )
    for index_name in index_names:
        cursor.execute(f"DROP INDEX IF EXISTS {index_name}")
