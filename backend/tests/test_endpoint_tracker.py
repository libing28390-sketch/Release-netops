import pytest
import uuid
from database import get_db_connection
from services.endpoint_tracker_service import locate_mac_address, track_and_locate_endpoints

def test_locate_mac_address_access_port():
    # Mock MAC entries
    mac_entries = [
        {'device_id': 'sw-core', 'mac_address': '001122334455', 'interface_name': 'GigabitEthernet0/1', 'vlan_id': 10},
        {'device_id': 'sw-access', 'mac_address': '001122334455', 'interface_name': 'GigabitEthernet0/24', 'vlan_id': 10},
    ]
    # Mock topology links: sw-core Gi0/1 is connected to sw-access Gi0/1
    topology_links = [
        {
            'source_device_id': 'sw-core',
            'source_port': 'GigabitEthernet0/1',
            'source_port_normalized': 'gi0/1',
            'target_device_id': 'sw-access',
            'target_port': 'GigabitEthernet0/1',
            'target_port_normalized': 'gi0/1',
        }
    ]
    
    # Run localization
    result = locate_mac_address('0011.2233.4455', mac_entries, topology_links)
    
    # Assert it resolved to the access switch and access port (gi0/24 is not an uplink)
    assert result is not None
    assert result['switch_id'] == 'sw-access'
    assert result['port'] == 'GigabitEthernet0/24'
    assert result['vlan'] == '10'
    assert 'Access Port' in result['confidence']

def test_locate_mac_address_trunk_fallback():
    # Mock MAC entries: learned only on uplinks (e.g. because leaf is unmanaged or not polled)
    mac_entries = [
        {'device_id': 'sw-core', 'mac_address': '001122334455', 'interface_name': 'GigabitEthernet0/1', 'vlan_id': 10},
        {'device_id': 'sw-dist', 'mac_address': '001122334455', 'interface_name': 'GigabitEthernet0/2', 'vlan_id': 10},
    ]
    # sw-core Gi0/1 <-> sw-dist Gi0/1, and sw-dist Gi0/2 <-> sw-access Gi0/1
    topology_links = [
        {
            'source_device_id': 'sw-core',
            'source_port': 'GigabitEthernet0/1',
            'source_port_normalized': 'gi0/1',
            'target_device_id': 'sw-dist',
            'target_port': 'GigabitEthernet0/1',
            'target_port_normalized': 'gi0/1',
        },
        {
            'source_device_id': 'sw-dist',
            'source_port': 'GigabitEthernet0/2',
            'source_port_normalized': 'gi0/2',
            'target_device_id': 'sw-access',
            'target_port': 'GigabitEthernet0/1',
            'target_port_normalized': 'gi0/1',
        }
    ]
    
    # Run localization: should trace sw-core Gi0/1 -> sw-dist Gi0/2 (which is also a trunk but further down)
    result = locate_mac_address('001122334455', mac_entries, topology_links)
    
    assert result is not None
    assert result['switch_id'] == 'sw-dist'
    assert result['port'] == 'GigabitEthernet0/2'
    assert 'Trunk Port' in result['confidence']

def test_track_and_locate_endpoints_integration(isolated_db):
    conn = get_db_connection()
    try:
        # Clear tables
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM arp_table")
        conn.execute("DELETE FROM mac_table")
        conn.execute("DELETE FROM topology_links")
        conn.execute("DELETE FROM network_endpoints")
        conn.execute("DELETE FROM endpoint_history")
        
        # Insert switches
        conn.execute("INSERT INTO devices (id, hostname, ip_address, status, role) VALUES ('dev-core', 'core-sw', '10.0.0.1', 'online', 'core')")
        conn.execute("INSERT INTO devices (id, hostname, ip_address, status, role) VALUES ('dev-access', 'access-sw', '10.0.0.2', 'online', 'switch')")
        
        # Insert ARP entry (L3 router learned IP 192.168.1.100 has MAC 001122334455)
        conn.execute(
            '''INSERT INTO arp_table (id, device_id, ip_address, mac_address, interface_name, vlan_id, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            ("arp-1", "dev-core", "192.168.1.100", "001122334455", "Vlan10", 10, "2026-06-14 11:30:00")
        )
        
        # Insert MAC entries
        conn.execute(
            '''INSERT INTO mac_table (id, device_id, mac_address, interface_name, vlan_id, entry_type, last_updated)
               VALUES (?, ?, ?, ?, ?, 'dynamic', ?)''',
            ("mac-1", "dev-core", "001122334455", "GigabitEthernet0/1", 10, "2026-06-14 11:30:00")
        )
        conn.execute(
            '''INSERT INTO mac_table (id, device_id, mac_address, interface_name, vlan_id, entry_type, last_updated)
               VALUES (?, ?, ?, ?, ?, 'dynamic', ?)''',
            ("mac-2", "dev-access", "001122334455", "GigabitEthernet0/24", 10, "2026-06-14 11:30:00")
        )
        
        # Insert topology links
        conn.execute(
            '''INSERT INTO topology_links (
                id, link_key, source_device_id, source_port, source_port_normalized,
                target_device_id, target_port, target_port_normalized, status
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'up')''',
            ("link-1", "core::gi0/1--access::gi0/1", "dev-core", "GigabitEthernet0/1", "gi0/1", "dev-access", "GigabitEthernet0/1", "gi0/1")
        )
        conn.commit()
    finally:
        conn.close()
        
    # Execute Endpoint Tracking
    track_and_locate_endpoints()
    
    conn = get_db_connection()
    try:
        # Verify endpoint resolved to access-sw port gi0/24
        cursor = conn.execute("SELECT * FROM network_endpoints WHERE ip = '192.168.1.100'")
        ep = cursor.fetchone()
        assert ep is not None
        assert ep['switch_id'] == 'dev-access'
        assert ep['switch_port'] == 'GigabitEthernet0/24'
        assert ep['is_active'] == 1
        
        # Assert no drift logged yet
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM endpoint_history")
        assert cursor.fetchone()['cnt'] == 0
        
        # Simulating drift: host moved to access-sw port gi0/15
        conn.execute("DELETE FROM mac_table")
        conn.execute(
            '''INSERT INTO mac_table (id, device_id, mac_address, interface_name, vlan_id, entry_type, last_updated)
               VALUES (?, ?, ?, ?, ?, 'dynamic', ?)''',
            ("mac-1", "dev-core", "001122334455", "GigabitEthernet0/1", 10, "2026-06-14 11:35:00")
        )
        conn.execute(
            '''INSERT INTO mac_table (id, device_id, mac_address, interface_name, vlan_id, entry_type, last_updated)
               VALUES (?, ?, ?, ?, ?, 'dynamic', ?)''',
            ("mac-2", "dev-access", "001122334455", "GigabitEthernet0/15", 10, "2026-06-14 11:35:00")
        )
        conn.commit()
    finally:
        conn.close()
        
    # Run again to detect drift
    track_and_locate_endpoints()
    
    conn = get_db_connection()
    try:
        # Verify new location
        cursor = conn.execute("SELECT * FROM network_endpoints WHERE ip = '192.168.1.100'")
        ep = cursor.fetchone()
        assert ep['switch_port'] == 'GigabitEthernet0/15'
        
        # Verify drift logged to endpoint_history
        cursor = conn.execute("SELECT * FROM endpoint_history")
        drift = cursor.fetchone()
        assert drift is not None
        assert drift['ip'] == '192.168.1.100'
        assert drift['mac'] == '001122334455'
        assert drift['old_switch_id'] == 'dev-access'
        assert drift['old_switch_port'] == 'GigabitEthernet0/24'
        assert drift['new_switch_id'] == 'dev-access'
        assert drift['new_switch_port'] == 'GigabitEthernet0/15'
        assert drift['drift_type'] == 'drift'
    finally:
        conn.close()
