import pytest
from database import get_db_connection, init_db
from services.ip_locator_service import get_route_cache, _set_cached_arp
from services.diagnose_service import match_route_offline

def test_route_and_arp_intelligence_tables_exist(isolated_db):
    conn = get_db_connection()
    try:
        # 1. Verify tables exist
        for table in ["route_table", "arp_table", "mac_table", "neighbor_table"]:
            cursor = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            assert cursor.fetchone() is not None, f"Table {table} must exist"
    finally:
        conn.close()

def test_route_table_sync_and_lpm_matching(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM route_table")
        conn.execute("DELETE FROM devices")
        conn.execute("INSERT INTO devices (id, hostname, ip_address, status) VALUES ('dev-route-1', 'router-1', '10.0.0.1', 'online')")
        
        # Insert test routes into route_table directly
        conn.execute(
            '''
            INSERT INTO route_table (
                id, device_id, destination, next_hop, outgoing_interface, protocol, metric, preference, last_updated, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''',
            ("r-1", "dev-route-1", "10.0.0.0/8", "10.1.1.1", "GigabitEthernet0/1", "ospf", 10, 110, "2026-06-13T12:00:00")
        )
        conn.execute(
            '''
            INSERT INTO route_table (
                id, device_id, destination, next_hop, outgoing_interface, protocol, metric, preference, last_updated, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''',
            ("r-2", "dev-route-1", "10.2.0.0/16", "10.2.2.2", "GigabitEthernet0/2", "static", 1, 1, "2026-06-13T12:00:00")
        )
        conn.commit()
    finally:
        conn.close()

    # Test match_route_offline LPM matching
    # 10.2.1.1 should match 10.2.0.0/16 (LPM length 16) instead of 10.0.0.0/8 (LPM length 8)
    routes = match_route_offline("dev-route-1", "10.2.1.1")
    assert len(routes) == 1
    assert routes[0]['prefix'] == "10.2.0.0"
    assert routes[0]['mask'] == "255.255.0.0"
    assert routes[0]['next_hop'] == "10.2.2.2"

    # Test get_route_cache adapter
    res = get_route_cache()
    assert res['total'] >= 2
    entry_ids = [e['id'] for e in res['entries']]
    assert "r-1" in entry_ids
    assert "r-2" in entry_ids

def test_arp_table_sync(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM arp_table")
        conn.execute("DELETE FROM devices")
        conn.execute("INSERT INTO devices (id, hostname, ip_address, status) VALUES ('dev-switch-1', 'switch-1', '10.0.0.1', 'online')")
        conn.commit()
    finally:
        conn.close()

    # Call _set_cached_arp to trigger writing to arp_table
    _set_cached_arp(
        target_ip="192.168.1.50",
        mac="aabbccddeeff",
        arp_source={
            "device_id": "dev-switch-1",
            "interface": "GigabitEthernet0/5"
        }
    )

    conn = get_db_connection()
    try:
        cursor = conn.execute("SELECT * FROM arp_table WHERE ip_address = '192.168.1.50'")
        row = cursor.fetchone()
        assert row is not None
        assert row['device_id'] == "dev-switch-1"
        assert row['mac_address'] == "aabbccddeeff"
        assert row['interface_name'] == "GigabitEthernet0/5"
    finally:
        conn.close()
