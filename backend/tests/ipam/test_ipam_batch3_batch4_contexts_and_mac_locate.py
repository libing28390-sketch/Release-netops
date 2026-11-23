from __future__ import annotations

import pytest

from database import get_db_connection
from services import ip_locator_service
from services.cmdb_service import create_vrf
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
)
from services.ipam_current_fdb_observation_service import (
    begin_current_fdb_collection,
    finish_current_fdb_collection,
)
from services.ipam_routing_context_service import (
    create_device_routing_context,
    list_device_routing_context_candidates,
)


def test_routing_context_candidates_discover_and_track_confirmation(isolated_db) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, status, role, tenant_id) VALUES (?, ?, ?, 'online', 'core', 'tenant-default')",
            ('dev-ctx-1', 'CORE-SW-01', '10.10.0.1'),
        )
        vrf = create_vrf(conn, vrf_name='VRF-PROD', rd='65001:10', tenant_id='tenant-default')
        conn.commit()

        # Seed VRF ARP observation and unknown-context ARP observation
        ts1 = '2026-11-19T10:00:00Z'
        gen1 = begin_current_endpoint_collection(
            conn,
            device_id='dev-ctx-1',
            observation_source='arp',
            context_source='snmp',
            context_type='vrf',
            local_context_key='VRF-PROD',
            attempted_at=ts1,
            run_id='run-ctx-1',
        )
        finish_current_endpoint_collection(
            conn,
            device_id='dev-ctx-1',
            observation_source='arp',
            context_source='snmp',
            context_type='vrf',
            local_context_key='VRF-PROD',
            generation=gen1,
            status='complete',
            attempted_at=ts1,
            completed_at=ts1,
            run_id='run-ctx-1',
            observations=[{
                'context_source': 'snmp',
                'context_type': 'vrf',
                'local_context_key': 'VRF-PROD',
                'ip_address': '10.10.10.5',
                'mac_address': 'aa:bb:cc:00:00:05',
                'interface_name': 'Vlan-interface10',
                'normalized_interface_name': 'vlan-interface10',
                'vlan_key': 10,
                'local_context_name': 'VRF-PROD',
                'observed_at': ts1,
            }],
        )
        ts2 = '2026-11-19T10:05:00Z'
        gen2 = begin_current_endpoint_collection(
            conn,
            device_id='dev-ctx-1',
            observation_source='arp',
            context_source='snmp',
            context_type='unknown',
            local_context_key='',
            attempted_at=ts2,
            run_id='run-ctx-2',
        )
        finish_current_endpoint_collection(
            conn,
            device_id='dev-ctx-1',
            observation_source='arp',
            context_source='snmp',
            context_type='unknown',
            local_context_key='',
            generation=gen2,
            status='scope_unknown',
            attempted_at=ts2,
            completed_at=ts2,
            run_id='run-ctx-2',
            observations=[{
                'context_source': 'snmp',
                'context_type': 'unknown',
                'local_context_key': '',
                'ip_address': '10.10.20.6',
                'mac_address': 'aa:bb:cc:00:00:06',
                'interface_name': 'Vlan-interface20',
                'normalized_interface_name': 'vlan-interface20',
                'vlan_key': 20,
                'local_context_name': '',
                'observed_at': ts2,
            }],
        )
        conn.commit()

    candidates = list_device_routing_context_candidates(device_id='dev-ctx-1', security_tenant_id='tenant-default')
    by_type = {item['context_type']: item for item in candidates}
    assert set(by_type) == {'vrf', 'unknown'}
    assert by_type['vrf']['can_confirm'] is True
    assert by_type['vrf']['mapping_status'] == 'pending'
    assert by_type['vrf']['observation_count'] == 1
    assert by_type['unknown']['can_confirm'] is False
    assert by_type['unknown']['mapping_status'] == 'unknown_context'

    from services.ipam_address_space_service import ensure_vrf_address_space
    with get_db_connection() as conn:
        vrf_space = ensure_vrf_address_space(conn, vrf_id=vrf['id'], security_tenant_id='tenant-default')
        conn.commit()
    create_device_routing_context(
        device_id='dev-ctx-1',
        context_source='snmp',
        context_type='vrf',
        local_context_key='VRF-PROD',
        local_context_name='VRF-PROD',
        address_space_id=vrf_space['id'],
        security_tenant_id='tenant-default',
    )

    refreshed = list_device_routing_context_candidates(device_id='dev-ctx-1', security_tenant_id='tenant-default')
    refreshed_vrf = next(item for item in refreshed if item['context_type'] == 'vrf')
    assert refreshed_vrf['mapping_status'] == 'mapped'
    assert refreshed_vrf['address_space_id'] == vrf_space['id']


def test_arp_sweep_includes_prefix_gateways_and_explicit_opt_ins(monkeypatch) -> None:
    devices = [
        {'id': 'access-1', 'role': 'access'},
        {'id': 'core-gw', 'role': 'core'},
        {'id': 'core-plain', 'role': 'core'},
        {'id': 'router-opt-in', 'role': 'router', 'collection_policy_json': '{"collectors":{"arp":true}}'},
        {'id': 'gw-opt-out', 'role': 'core', 'collection_policy_json': '{"collectors":{"arp":false}}'},
    ]
    monkeypatch.setattr(ip_locator_service, '_load_eligible_devices', lambda **_kwargs: devices)
    monkeypatch.setattr(ip_locator_service, '_load_prefix_gateway_device_ids', lambda: {'core-gw', 'gw-opt-out'})
    monkeypatch.setattr(ip_locator_service, '_load_terminal_gateway_device_ids', lambda: {})
    monkeypatch.setattr(ip_locator_service, '_load_arp_collection_state', lambda: {})
    monkeypatch.setattr(
        ip_locator_service,
        'reserve_collector_sweep_batch',
        lambda *_args, **_kwargs: {'start_cursor': 0, 'selected_count': 10},
    )

    selected, total, skipped = ip_locator_service._load_arp_sweep_devices('run-gw')
    assert [d['id'] for d in selected] == ['access-1', 'core-gw', 'router-opt-in']
    assert total == 3
    assert skipped == 0


def test_locate_mac_path_normalizes_formats_traces_uplinks_and_enforces_scope(isolated_db) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, status, role, tenant_id) VALUES (?, ?, ?, 'online', 'core', 'tenant-default')",
            ('sw-core', 'CORE-1', '10.20.0.1'),
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, status, role, tenant_id) VALUES (?, ?, ?, 'online', 'access', 'tenant-default')",
            ('sw-acc', 'ACC-1', '10.20.0.2'),
        )
        conn.execute(
            """INSERT INTO topology_links
               (id, source_device_id, source_port, target_device_id, target_port)
               VALUES ('link-1', 'sw-core', 'Bridge-Aggregation1', 'sw-acc', 'Bridge-Aggregation1')""",
        )
        # Seed ARP on sw-core
        ts_arp = '2026-11-19T12:00:00Z'
        gen_arp = begin_current_endpoint_collection(
            conn, device_id='sw-core', observation_source='arp', context_source='snmp',
            context_type='global', local_context_key='--', attempted_at=ts_arp, run_id='run-arp-mac',
        )
        finish_current_endpoint_collection(
            conn, device_id='sw-core', observation_source='arp', context_source='snmp',
            context_type='global', local_context_key='--', generation=gen_arp, status='complete',
            attempted_at=ts_arp, completed_at=ts_arp, run_id='run-arp-mac',
            observations=[{
                'context_source': 'snmp',
                'context_type': 'global',
                'local_context_key': '--',
                'ip_address': '10.20.7.55',
                'mac_address': '00:1a:2b:3c:4d:5e',
                'interface_name': 'Vlan-interface7',
                'normalized_interface_name': 'vlan-interface7',
                'vlan_key': 7,
                'observed_at': ts_arp,
            }],
        )
        # Seed FDB on sw-core (uplink) and sw-acc (access port)
        gen_fdb1 = begin_current_fdb_collection(
            conn, device_id='sw-core', context_source='snmp',
            context_type='global', local_context_key='--', attempted_at=ts_arp, run_id='run-fdb-1',
        )
        finish_current_fdb_collection(
            conn, device_id='sw-core', context_source='snmp',
            context_type='global', local_context_key='--', generation=gen_fdb1, status='complete',
            attempted_at=ts_arp, completed_at=ts_arp, run_id='run-fdb-1',
            observations=[{
                'context_source': 'snmp',
                'context_type': 'global',
                'local_context_key': '--',
                'mac_address': '00:1a:2b:3c:4d:5e',
                'interface_name': 'Bridge-Aggregation1',
                'normalized_interface_name': 'bridge-aggregation1',
                'vlan_key': 7,
                'entry_type': 'dynamic',
                'observed_at': ts_arp,
            }],
        )
        ts_fdb2 = '2026-11-19T12:01:00Z'
        gen_fdb2 = begin_current_fdb_collection(
            conn, device_id='sw-acc', context_source='snmp',
            context_type='global', local_context_key='--', attempted_at=ts_fdb2, run_id='run-fdb-2',
        )
        finish_current_fdb_collection(
            conn, device_id='sw-acc', context_source='snmp',
            context_type='global', local_context_key='--', generation=gen_fdb2, status='complete',
            attempted_at=ts_fdb2, completed_at=ts_fdb2, run_id='run-fdb-2',
            observations=[{
                'context_source': 'snmp',
                'context_type': 'global',
                'local_context_key': '--',
                'mac_address': '00:1a:2b:3c:4d:5e',
                'interface_name': 'GigabitEthernet1/0/12',
                'normalized_interface_name': 'gigabitethernet1/0/12',
                'vlan_key': 7,
                'entry_type': 'dynamic',
                'observed_at': ts_fdb2,
            }],
        )
        conn.commit()

    # Cisco dotted format input
    result = ip_locator_service.locate_mac_path(
        '001a.2b3c.4d5e',
        authorized_device_ids=['sw-core', 'sw-acc'],
    )
    assert result['found'] is True
    assert result['mac'] == '00:1a:2b:3c:4d:5e'
    assert result['ip'] == '10.20.7.55'
    assert result['arp_source']['device'] == 'CORE-1'
    assert result['arp_source']['interface'] == 'Vlan-interface7'
    assert len(result['locations']) == 2
    # Confirmed access port is sorted first, uplink second
    assert result['locations'][0]['switch_id'] == 'sw-acc'
    assert result['locations'][0]['port'] == 'GigabitEthernet1/0/12'
    assert result['locations'][0]['is_uplink'] is False
    assert result['locations'][1]['switch_id'] == 'sw-core'
    assert result['locations'][1]['is_uplink'] is True
    assert result['locations'][1]['stop_reason'] == 'traced_to_downstream_switch'

    # Restricted scope (only sw-core authorized): sw-acc is hidden and stop_reason explains missing downstream
    scoped = ip_locator_service.locate_mac_path(
        '00-1A-2B-3C-4D-5E',
        authorized_device_ids=['sw-core'],
    )
    assert [loc['switch_id'] for loc in scoped['locations']] == ['sw-core']
    assert scoped['locations'][0]['stop_reason'] == 'missing_downstream_fdb_snapshot'

    # Invalid MAC rejected
    with pytest.raises(ValueError, match='Invalid MAC address'):
        ip_locator_service.locate_mac_path('not-a-mac')
