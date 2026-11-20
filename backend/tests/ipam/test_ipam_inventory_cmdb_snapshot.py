from __future__ import annotations

from database import get_db_connection
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    create_address,
    create_subnet,
    get_next_available_ip_details,
    list_ip_inventory,
)


def _seed_scope_and_device() -> str:
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute(
            "INSERT INTO sites (id, site_code, site_name) VALUES ('ipam-snapshot-site', 'IPAM-SNAPSHOT', 'IPAM Snapshot Site')"
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, tenant_id, site_id, status) VALUES ('ipam-snapshot-device', 'SW-SNAPSHOT', 'tenant-default', 'ipam-snapshot-site', 'online')"
        )
        conn.commit()
    return str(create_address_space(
        name='CMDB Snapshot Test Global',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )['id'])


def _publish_interface_ip(ip: str, *, interface: str = 'Vlan-interface10', mask: int = 24,
                          observed_at: str = '2026-10-28T10:00:00+00:00',
                          context_type: str = 'unknown', local_context_key: str = '') -> None:
    attempt = begin_snapshot_attempt('ipam-snapshot-device', 'interface_inventory')
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES (?, ?, ?, '', 'up', 'up', ?, ?, 'svi', ?, ?, ?, '{}')""",
            ('ipam-snapshot-device', interface.lower(), interface, ip, mask,
             attempt['generation'], observed_at, attempt['run_id']),
        )
        conn.execute(
            """INSERT INTO cmdb_device_interface_address_observations (
                   device_id, normalized_interface_name, interface_name,
                   context_source, context_type, local_context_key, local_context_name,
                   ip_address, ip_prefix_length, generation, observed_at, run_id,
                   metadata_json
               ) VALUES (?, ?, ?, 'cli', ?, ?, ?, ?::inet, ?, ?, ?::timestamptz, ?, '{}'::jsonb)""",
            (
                'ipam-snapshot-device', interface.lower(), interface,
                context_type, local_context_key, local_context_key, ip, mask,
                attempt['generation'], observed_at, attempt['run_id'],
            ),
        )
        assert complete_snapshot(
            conn,
            attempt,
            observed_at=observed_at,
            transport='ssh',
            record_count=1,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _map_interface_context(address_space_id: str, *, context_type: str = 'global', key: str = '--') -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts (
                   id, device_id, context_source, context_type, local_context_key,
                   local_context_name, address_space_id, status, revision,
                   created_at, updated_at
               ) VALUES (?, 'ipam-snapshot-device', 'cli', ?, ?, ?, ?, 'active', 1,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (f'context-{context_type}-{key}', context_type, key, key, address_space_id),
        )
        conn.commit()


def test_ip_inventory_reads_only_last_successful_interface_snapshot(isolated_db):
    address_space_id = _seed_scope_and_device()
    _map_interface_context(address_space_id)
    _publish_interface_ip('10.20.30.1', context_type='global', local_context_key='--')
    subnet = create_subnet(
        prefix='10.20.30.0/24', tenant_id='tenant-default',
        site_id='ipam-snapshot-site', network_type='server',
        address_space_id=address_space_id,
    )

    attempt = begin_snapshot_attempt('ipam-snapshot-device', 'interface_inventory')
    # A running replacement is not visible until its generation succeeds.

    inventory = list_ip_inventory(site_id='ipam-snapshot-site', page=1, page_size=20)
    row = next(item for item in inventory['items'] if item['source'] == 'interface_cli')
    assert inventory['total'] == 1
    assert row['address'] == '10.20.30.1'
    assert row['interface_admin_status'] == 'up'
    assert row['interface_oper_status'] == 'up'
    assert row['site_name'] == 'IPAM Snapshot Site'
    assert row['observed_prefix'] == '10.20.30.0/24'
    assert row['subnet_id'] == ''
    assert row['prefix_match_status'] == 'matched'
    assert row['scope_status'] == 'resolved'
    assert row['address_space_id'] == address_space_id
    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.20.30.2', 'pending_discovery_count': 0,
    }
    assert row['discovered_last_seen'] == '2026-10-28T10:00:00+00:00'
    assert inventory['summary']['interface_observed'] == 1
    assert inventory['summary']['discovered'] == 0
    assert inventory['summary']['interface_vrf_review'] == 0
    assert inventory['summary']['interface_global_default'] == 0
    formal_inventory = list_ip_inventory(
        site_id='ipam-snapshot-site', page=1, page_size=20, registered_only=True,
    )
    assert formal_inventory['total'] == 0
    assert formal_inventory['summary']['manual'] == 0
    prefix_inventory = list_ip_inventory(prefix_id=subnet['id'])
    assert prefix_inventory['total'] == 1
    assert prefix_inventory['items'][0]['source'] == 'interface_cli'
    assert prefix_inventory['items'][0]['subnet_id'] == ''
    assert attempt['generation'] == 2


def test_ip_inventory_marks_snapshot_networks_without_prefixes_as_unmatched(isolated_db):
    address_space_id = _seed_scope_and_device()
    create_subnet(
        prefix='10.20.30.0/24', tenant_id='tenant-default',
        site_id='ipam-snapshot-site', network_type='server',
        address_space_id=address_space_id,
    )
    _publish_interface_ip('10.30.40.1', mask=30, interface='Vlan-interface40')

    inventory = list_ip_inventory(site_id='ipam-snapshot-site', page=1, page_size=20)
    row = next(item for item in inventory['items'] if item['source'] == 'interface_cli')
    assert row['observed_prefix'] == '10.30.40.0/30'
    assert row['subnet_id'] == ''
    assert row['prefix_match_status'] == 'unmatched'
    assert inventory['summary']['interface_unmatched_prefix'] == 1


def test_interface_role_does_not_replace_inventory_role_filter(isolated_db):
    address_space_id = _seed_scope_and_device()
    subnet = create_subnet(
        prefix='10.20.30.0/24', site_id='ipam-snapshot-site',
        address_space_id=address_space_id,
    )
    create_address(subnet['id'], address='10.20.30.10', device_type='server')
    _publish_interface_ip('10.20.30.1')
    all_rows = list_ip_inventory(site_id='ipam-snapshot-site', page_size=100)
    assert all_rows['total'] == 2
    assert {row['device_type'] for row in all_rows['items']} == {'server', 'vlan'}
    servers = list_ip_inventory(site_id='ipam-snapshot-site', device_type='server')
    assert servers['total'] == 1
    assert servers['items'][0]['address'] == '10.20.30.10'
    interfaces = list_ip_inventory(site_id='ipam-snapshot-site', device_type='vlan')
    assert interfaces['total'] == 1
    assert interfaces['items'][0]['source'] == 'interface_cli'


def test_generated_interface_ledger_and_snapshot_are_one_inventory_row(isolated_db):
    address_space_id = _seed_scope_and_device()
    subnet = create_subnet(
        prefix='10.20.30.0/24', site_id='ipam-snapshot-site',
        address_space_id=address_space_id,
    )
    from schemas.schemas import PrefixCreate
    assert PrefixCreate(prefix='10.20.30.0/24').network_type == 'unclassified'
    address = create_address(subnet['id'], address='10.20.30.1', device_id='ipam-snapshot-device', device_type='device')
    with get_db_connection() as conn:
        assert conn.execute('SELECT network_type FROM prefixes WHERE id=?', (subnet['id'],)).fetchone()['network_type'] == 'unclassified'
        conn.execute("UPDATE ip_addresses SET source_type='interface_collection' WHERE id=?", (address['id'],))
        conn.commit()
    _map_interface_context(address_space_id)
    _publish_interface_ip('10.20.30.1', context_type='global', local_context_key='--')
    inventory = list_ip_inventory(site_id='ipam-snapshot-site')
    assert inventory['total'] == 1
    assert inventory['items'][0]['id'] == address['id']
    assert inventory['items'][0]['has_interface_observation'] is True
    assert inventory['items'][0]['interface_oper_status'] == 'up'
    assert inventory['summary']['manual'] == 1
    assert inventory['summary']['interface_observed'] == 1
    ledger = list_ip_inventory(site_id='ipam-snapshot-site', registered_only=True)
    assert ledger['total'] == 1
    assert not ledger['items'][0].get('has_interface_observation')


def test_unmapped_interface_host_does_not_merge_into_global_ledger(isolated_db):
    address_space_id = _seed_scope_and_device()
    subnet = create_subnet(
        prefix='10.20.30.0/24', site_id='ipam-snapshot-site',
        address_space_id=address_space_id,
    )
    address = create_address(subnet['id'], address='10.20.30.1')
    _publish_interface_ip('10.20.30.1')

    inventory = list_ip_inventory(site_id='ipam-snapshot-site', q='10.20.30.1')
    assert inventory['total'] == 2
    formal = next(item for item in inventory['items'] if item['id'] == address['id'])
    observed = next(item for item in inventory['items'] if item['source'] == 'interface_cli')
    assert formal['source'] == 'manual'
    assert observed['scope_status'] == 'scope_pending'
    assert observed['address_space_id'] == ''
    assert observed['subnet_id'] == ''
    assert get_next_available_ip_details(subnet['id']) == {
        'next_available_ip': '10.20.30.2', 'pending_discovery_count': 0,
    }
