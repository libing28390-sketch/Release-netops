from __future__ import annotations

import ipaddress
from datetime import datetime, timezone

from database import get_db_connection
from services.ipam_address_space_service import create_address_space
from services.ipam_current_endpoint_observation_service import (
    begin_current_endpoint_collection,
    finish_current_endpoint_collection,
)
from services.ipam_service import (
    _discovered_address_reservations,
    create_address,
    create_subnet,
    list_ip_inventory,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_device(device_id: str, site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, 'tenant-default') ON CONFLICT (id) DO NOTHING""",
            (site_id, site_id.upper(), site_id),
        )
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, status, site_id, tenant_id)
               VALUES (?, ?, '192.0.2.44', 'cisco_ios', 'online', ?, 'tenant-default')""",
            (device_id, device_id, site_id),
        )
        conn.commit()


def _space(name: str) -> str:
    return str(create_address_space(
        name=name, kind='global', vrf_id=None, security_tenant_id='tenant-default',
    )['id'])


def _map_global(device_id: str, key: str, address_space_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts
                   (id, device_id, context_source, context_type, local_context_key,
                    local_context_name, address_space_id, status)
               VALUES (?, ?, 'snmp', 'global', ?, ?, ?, 'active')""",
            (f'mapping-{device_id}-{key}', device_id, key, key, address_space_id),
        )
        conn.commit()


def _observe(
    device_id: str,
    context_type: str,
    key: str,
    *,
    ip: str,
    mac: str,
    status: str | None = None,
) -> None:
    attempted_at = _now()
    context = {
        'context_source': 'snmp',
        'context_type': context_type,
        'local_context_key': key,
    }
    with get_db_connection() as conn:
        generation = begin_current_endpoint_collection(
            conn, device_id=device_id, **context,
            attempted_at=attempted_at, run_id=f'run-{device_id}-{key}',
        )
        conn.commit()
    observed_status = status or ('scope_unknown' if context_type == 'unknown' else 'complete')
    with get_db_connection() as conn:
        finish_current_endpoint_collection(
            conn,
            device_id=device_id,
            **context,
            generation=generation,
            status=observed_status,
            attempted_at=attempted_at,
            completed_at=_now(),
            observations=[{
                'ip': ip, 'mac': mac, 'interface': 'Vlan10', 'vlan_id': 10,
                **context,
            }],
            run_id=f'run-{device_id}-{key}',
        )
        conn.commit()


def test_mapped_current_arp_observations_reserve_the_same_host_only_in_each_space(isolated_db):
    site_id = 'site-current-arp-allocation'
    first_device = 'arp-allocation-device-a'
    second_device = 'arp-allocation-device-b'
    _seed_device(first_device, site_id)
    _seed_device(second_device, site_id)
    first_space = _space('ARP Allocation Space A')
    second_space = _space('ARP Allocation Space B')
    _map_global(first_device, 'context-a', first_space)
    _map_global(second_device, 'context-b', second_space)
    _observe(
        first_device, 'global', 'context-a', ip='10.254.110.2', mac='0011223344aa',
    )
    _observe(
        second_device, 'global', 'context-b', ip='10.254.110.2', mac='0011223344bb',
    )
    first_prefix = create_subnet(
        prefix='10.254.110.0/29', address_space_id=first_space, site_id=site_id,
        network_type='management', name='ARP Allocation Prefix A',
    )
    second_prefix = create_subnet(
        prefix='10.254.110.0/29', address_space_id=second_space, site_id=site_id,
        network_type='management', name='ARP Allocation Prefix B',
    )

    results = []
    with get_db_connection() as conn:
        for prefix in (first_prefix, second_prefix):
            results.append(_discovered_address_reservations(
                conn,
                ipaddress.ip_network(prefix['prefix']),
                tenant_id='tenant-default',
                vrf_id='',
                site_id=site_id,
                address_space_id=prefix['address_space_id'],
            ))

    assert results == [({'10.254.110.2'}, set()), ({'10.254.110.2'}, set())]


def test_unknown_raw_global_alias_remains_pending_until_explicit_mapping(isolated_db):
    site_id = 'site-current-arp-unknown'
    device_id = 'arp-allocation-unknown-device'
    _seed_device(device_id, site_id)
    address_space_id = _space('ARP Unknown Context Space')
    _observe(
        device_id, 'unknown', 'global', ip='10.254.111.2', mac='0011223344cc',
    )
    prefix = create_subnet(
        prefix='10.254.111.0/29', address_space_id=address_space_id, site_id=site_id,
        network_type='management', name='ARP Unknown Context Prefix',
    )

    with get_db_connection() as conn:
        resolved, pending = _discovered_address_reservations(
            conn,
            ipaddress.ip_network(prefix['prefix']),
            tenant_id='tenant-default',
            vrf_id='',
            site_id=site_id,
            address_space_id=address_space_id,
        )

    assert resolved == set()
    assert pending == {'10.254.111.2'}
    inventory = list_ip_inventory(site_id=site_id, page=1, page_size=100)
    item = next(row for row in inventory['items'] if row['address'] == '10.254.111.2')
    assert item['scope_status'] == 'scope_pending'
    assert item['address_space_id'] == ''
    assert item['device_id'] == ''
    assert item['interface_name'] == ''
    assert item['observed_source_device_id'] == device_id
    assert item['observed_context_key'] == 'global'


def test_current_arp_inventory_keeps_formal_owner_separate_from_source_device(isolated_db):
    site_id = 'site-current-arp-inventory'
    device_id = 'arp-inventory-source-device'
    _seed_device(device_id, site_id)
    address_space_id = _space('ARP Inventory Global Space')
    _map_global(device_id, 'Global', address_space_id)
    prefix = create_subnet(
        prefix='10.254.112.0/29', address_space_id=address_space_id, site_id=site_id,
        network_type='server', name='ARP Inventory Prefix',
    )
    formal_address = create_address(
        prefix['id'], address='10.254.112.2', hostname='formal-host',
        mac_address='00:11:22:33:44:22', status='active',
    )
    _observe(
        device_id, 'global', 'Global', ip='10.254.112.2', mac='001122334455',
    )

    inventory = list_ip_inventory(site_id=site_id, page=1, page_size=100)
    item = next(row for row in inventory['items'] if row['id'] == formal_address['id'])

    assert item['source'] == 'manual+discovered'
    assert item['device_id'] in ('', None)
    assert item['interface_name'] in ('', None)
    assert item['mac_address'] == '00:11:22:33:44:22'
    assert item['observed_mac_address'] == '001122334455'
    assert item['observed_source_device_id'] == device_id
    assert item['address_space_id'] == address_space_id


def test_current_fhrp_virtual_ip_reserves_only_its_explicit_address_space(isolated_db, monkeypatch):
    del isolated_db
    site_id = 'site-current-fhrp-allocation'
    _seed_device('fhrp-allocation-device', site_id)
    first_space = _space('FHRP Allocation Space A')
    second_space = _space('FHRP Allocation Space B')
    first_prefix = create_subnet(
        prefix='10.254.113.0/29', address_space_id=first_space, site_id=site_id,
        network_type='management', name='FHRP Allocation Prefix A',
    )
    second_prefix = create_subnet(
        prefix='10.254.113.0/29', address_space_id=second_space, site_id=site_id,
        network_type='management', name='FHRP Allocation Prefix B',
    )
    monkeypatch.setattr(
        'services.ipam_current_fhrp_projection_service.list_current_fhrp_observation_projection',
        lambda _conn: [{
            'virtual_ip': '10.254.113.2',
            'tenant_id': 'tenant-default',
            'site_id': site_id,
            'source_device_id': 'fhrp-allocation-device',
            'address_space_id': first_space,
            'scope_status': 'resolved',
        }],
    )

    results = []
    with get_db_connection() as conn:
        for prefix in (first_prefix, second_prefix):
            results.append(_discovered_address_reservations(
                conn,
                ipaddress.ip_network(prefix['prefix']),
                tenant_id='tenant-default',
                vrf_id='',
                site_id=site_id,
                address_space_id=prefix['address_space_id'],
            ))

    assert results == [({'10.254.113.2'}, set()), (set(), set())]


def test_current_fhrp_virtual_ip_with_unknown_scope_remains_site_pending(isolated_db, monkeypatch):
    del isolated_db
    site_id = 'site-current-fhrp-pending'
    _seed_device('fhrp-pending-device', site_id)
    address_space_id = _space('FHRP Pending Space')
    prefix = create_subnet(
        prefix='10.254.114.0/29', address_space_id=address_space_id, site_id=site_id,
        network_type='management', name='FHRP Pending Prefix',
    )
    monkeypatch.setattr(
        'services.ipam_current_fhrp_projection_service.list_current_fhrp_observation_projection',
        lambda _conn: [{
            'virtual_ip': '10.254.114.2',
            'tenant_id': 'tenant-default',
            'site_id': site_id,
            'source_device_id': 'fhrp-pending-device',
            'address_space_id': '',
            'scope_status': 'scope_pending',
        }],
    )

    with get_db_connection() as conn:
        resolved, pending = _discovered_address_reservations(
            conn,
            ipaddress.ip_network(prefix['prefix']),
            tenant_id='tenant-default',
            vrf_id='',
            site_id=site_id,
            address_space_id=address_space_id,
        )

    assert resolved == set()
    assert pending == {'10.254.114.2'}
