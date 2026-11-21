from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog
from database import get_db_connection
from database.migrations.m0282_asset_delete_lookup_indexes import downgrade, upgrade


EXPECTED_INDEXES = {
    "idx_ip_addresses_device_id",
    "idx_ip_addresses_interface_id",
    "idx_ip_inventory_device_id",
    "idx_prefixes_gateway_device_id",
    "idx_prefixes_gateway_interface_id",
    "idx_topo_links_target_device_id",
    "idx_device_telemetry_hourly_device_id",
    "idx_pam_session_tokens_asset_id",
}


def test_asset_delete_lookup_indexes_migrate_idempotently(isolated_db) -> None:
    conn = get_db_connection()
    try:
        for index_name in EXPECTED_INDEXES:
            conn.execute(f"DROP INDEX IF EXISTS {index_name}")
        conn.commit()

        upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        assert EXPECTED_INDEXES <= pg_catalog.index_names(conn)

        downgrade(conn.cursor(), use_pg=True)
        conn.commit()

        assert not EXPECTED_INDEXES & pg_catalog.index_names(conn)
    finally:
        conn.close()
