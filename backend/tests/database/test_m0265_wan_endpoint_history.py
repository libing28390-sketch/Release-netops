from __future__ import annotations


def test_m0265_backfills_unambiguous_legacy_endpoints_idempotently(isolated_db):
    from database import get_db_connection
    from database.migrations import m0265_wan_endpoint_history
    from services.wan_circuit_service import save_wan_circuit

    now = "2026-10-04T00:00:00Z"
    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", ("tenant-history", "History Tenant"))
        conn.execute(
            "INSERT INTO sites (id, site_code, site_name, tenant_id) VALUES (?, ?, ?, ?)",
            ("site-history", "HIS", "History Site", "tenant-history"),
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, site_id, site, tenant_id, role, device_category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("device-history", "edge-history", "site-history", "site-history", "tenant-history", "edge", "router"),
        )
        conn.execute(
            "INSERT INTO interfaces (id, device_id, interface_name, if_index, speed) VALUES (?, ?, ?, ?, ?)",
            ("interface-history", "device-history", "GigabitEthernet0/1", 12, 1_000_000_000),
        )
        conn.commit()
    finally:
        conn.close()

    item = save_wan_circuit(
        {
            "link_name": "Legacy line",
            "site_id": "site-history",
            "contracted_download_mbps": 100,
            "contracted_upload_mbps": 50,
            "endpoints": [
                {"side": "A", "endpoint_type": "managed", "site_id": "site-history", "device_id": "device-history", "interface_id": "interface-history"},
                {"side": "Z", "endpoint_type": "unmanaged", "endpoint_name": ""},
            ],
        },
        tenant_id="tenant-history",
        actor_id="test",
    )

    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM wan_link_endpoint_history WHERE link_id = ?", (item["id"],))
        conn.execute("DELETE FROM wan_link_endpoints WHERE link_id = ?", (item["id"],))
        conn.execute(
            "UPDATE wan_links SET created_at = ?, updated_at = ? WHERE id = ?",
            (now, now, item["id"]),
        )
        conn.commit()

        migration_cursor = conn.cursor()
        m0265_wan_endpoint_history.upgrade(migration_cursor, use_pg=True)
        m0265_wan_endpoint_history.upgrade(migration_cursor, use_pg=True)
        conn.commit()

        endpoints = conn.execute(
            "SELECT side, endpoint_type, site_id, device_id, interface_id, if_index, measurement_scope FROM wan_link_endpoints WHERE link_id = ? ORDER BY side",
            (item["id"],),
        ).fetchall()
        assert len(endpoints) == 2
        assert endpoints[0]["side"] == "A"
        assert endpoints[0]["endpoint_type"] == "managed"
        assert endpoints[0]["device_id"] == "device-history"
        assert endpoints[0]["interface_id"] == "interface-history"
        assert endpoints[0]["if_index"] == 12
        assert endpoints[0]["measurement_scope"] == "shared_interface"
        assert endpoints[1]["side"] == "Z"
        assert endpoints[1]["endpoint_type"] == "unmanaged"
        assert endpoints[1]["site_id"] == ""

        history_count = conn.execute(
            "SELECT COUNT(*) FROM wan_link_endpoint_history WHERE link_id = ?",
            (item["id"],),
        ).fetchone()[0]
        assert history_count == 2
    finally:
        conn.close()
