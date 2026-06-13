import uuid
import pytest
from database import get_db_connection
from services.ip_locator_service import _set_cached_endpoint, get_network_endpoints
from services.topology_service import rebuild_links_from_observations, get_current_links

def test_endpoint_history_drift_detection(isolated_db):
    conn = get_db_connection()
    try:
        # Clear tables
        conn.execute("DELETE FROM endpoint_history")
        conn.execute("DELETE FROM network_endpoints")
        conn.commit()
        
        # 1. Verify endpoint_history table exists
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='endpoint_history'")
        assert cursor.fetchone() is not None, "Table endpoint_history must exist"
        
        # 2. Add an active endpoint
        ip = "192.168.1.100"
        mac = "001122334455"
        _set_cached_endpoint(
            ip=ip, mac=mac, device_id="switch-1", port="GigabitEthernet0/1", vlan="10",
            site="Test Site", confidence="95%", hostname="host-1", vendor="Cisco",
            os_type="Linux", asset_type="host", source_type="arp"
        )
        
        # Verify no drift logged yet
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM endpoint_history")
        assert cursor.fetchone()['cnt'] == 0
        
        # 3. Update location to simulate drift (same IP/MAC, different switch/port)
        _set_cached_endpoint(
            ip=ip, mac=mac, device_id="switch-2", port="GigabitEthernet0/2", vlan="20",
            site="Test Site", confidence="95%", hostname="host-1", vendor="Cisco",
            os_type="Linux", asset_type="host", source_type="arp"
        )
        
        # Verify drift record was created
        cursor = conn.execute("SELECT * FROM endpoint_history")
        drift = cursor.fetchone()
        assert drift is not None
        assert drift['ip'] == ip
        assert drift['mac'] == mac
        assert drift['old_switch_id'] == "switch-1"
        assert drift['old_switch_port'] == "GigabitEthernet0/1"
        assert drift['old_vlan'] == "10"
        assert drift['new_switch_id'] == "switch-2"
        assert drift['new_switch_port'] == "GigabitEthernet0/2"
        assert drift['new_vlan'] == "20"
        assert drift['drift_type'] == "drift"
    finally:
        conn.close()

def test_topology_links_interface_id_resolution(isolated_db):
    conn = get_db_connection()
    try:
        # Clear tables
        conn.execute("DELETE FROM topology_links")
        conn.execute("DELETE FROM topology_observations")
        conn.execute("DELETE FROM interfaces")
        conn.execute("DELETE FROM devices")
        conn.commit()

        # 1. Verify topology_links table exists
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='topology_links'")
        assert cursor.fetchone() is not None, "Table topology_links must exist"

        # 2. Insert devices
        conn.execute("INSERT INTO devices (id, hostname, ip_address, status) VALUES ('dev-1', 'switch-1', '10.0.0.1', 'online')")
        conn.execute("INSERT INTO devices (id, hostname, ip_address, status) VALUES ('dev-2', 'switch-2', '10.0.0.2', 'online')")
        
        # 3. Create interfaces for dev-1 and dev-2
        conn.execute("INSERT INTO interfaces (id, device_id, interface_name) VALUES ('intf-1', 'dev-1', 'GigabitEthernet0/1')")
        conn.execute("INSERT INTO interfaces (id, device_id, interface_name) VALUES ('intf-2', 'dev-2', 'GigabitEthernet0/2')")
        
        # 4. Insert topology observations matching the hostname and port names
        conn.execute(
            '''
            INSERT INTO topology_observations (
                id, source_device_id, source_hostname, source_port_raw, source_port_normalized,
                neighbor_name_raw, neighbor_name_normalized, neighbor_ip_address,
                target_device_id, target_hostname, target_port_raw, target_port_normalized,
                protocol, confidence, status, collected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                "obs-1", "dev-1", "switch-1", "GigabitEthernet0/1", "gi0/1",
                "switch-2", "switch-2", "10.0.0.2", "dev-2", "switch-2", "GigabitEthernet0/2", "gi0/2",
                "lldp", 0.9, "active", "2026-06-13T12:00:00", "2026-06-13T12:00:00"
            )
        )
        conn.commit()
    finally:
        conn.close()

    # Rebuild links
    rebuild_links_from_observations()

    conn = get_db_connection()
    try:
        # Verify topology_links has the resolved interface IDs
        cursor = conn.execute("SELECT * FROM topology_links")
        link = cursor.fetchone()
        assert link is not None
        # Link source/target order is sorted by device_id
        if link['source_device_id'] == 'dev-1':
            assert link['source_interface_id'] == 'intf-1'
            assert link['target_device_id'] == 'dev-2'
            assert link['target_interface_id'] == 'intf-2'
        else:
            assert link['source_device_id'] == 'dev-2'
            assert link['source_interface_id'] == 'intf-2'
            assert link['target_device_id'] == 'dev-1'
            assert link['target_interface_id'] == 'intf-1'
    finally:
        conn.close()
