from __future__ import annotations

from database import get_db_connection
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.ipam_service import create_subnet, list_ip_inventory


def _seed_scope_and_device():
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute(
            "INSERT INTO sites (id, site_code, site_name) VALUES ('ipam-snapshot-site', 'IPAM-SNAPSHOT', 'IPAM Snapshot Site')"
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, tenant_id, site_id, status) VALUES ('ipam-snapshot-device', 'SW-SNAPSHOT', 'tenant-default', 'ipam-snapshot-site', 'online')"
        )
        conn.commit()


def _publish_interface_ip(ip: str, *, interface: str = 'Vlan-interface10', mask: int = 24,
                          observed_at: str = '2026-10-28T10:00:00+00:00') -> None:
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


def test_ip_inventory_reads_only_last_successful_interface_snapshot(isolated_db):
    _seed_scope_and_device()
    _publish_interface_ip('10.20.30.1')
    subnet = create_subnet(
        prefix='10.20.30.0/24', tenant_id='tenant-default',
        site_id='ipam-snapshot-site', network_type='server',
    )

    attempt = begin_snapshot_attempt('ipam-snapshot-device', 'interface_inventory')
    # A running replacement is not visible until its generation succeeds.

    inventory = list_ip_inventory(site_id='ipam-snapshot-site', page=1, page_size=20)
    row = next(item for item in inventory['items'] if item['source'] == 'interface_cli')
    assert inventory['total'] == 1
    assert row['address'] == '10.20.30.1'
    assert row['site_name'] == 'IPAM Snapshot Site'
    assert row['observed_prefix'] == '10.20.30.0/24'
    assert row['subnet_id'] == ''
    assert row['prefix_match_status'] == 'global_default'
    assert row['discovered_last_seen'] == '2026-10-28T10:00:00+00:00'
    assert inventory['summary']['interface_observed'] == 1
    assert inventory['summary']['discovered'] == 0
    assert inventory['summary']['interface_vrf_review'] == 0
    assert inventory['summary']['interface_global_default'] == 1
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
    _seed_scope_and_device()
    create_subnet(
        prefix='10.20.30.0/24', tenant_id='tenant-default',
        site_id='ipam-snapshot-site', network_type='server',
    )
    _publish_interface_ip('10.30.40.1', mask=30, interface='Vlan-interface40')

    inventory = list_ip_inventory(site_id='ipam-snapshot-site', page=1, page_size=20)
    row = next(item for item in inventory['items'] if item['source'] == 'interface_cli')
    assert row['observed_prefix'] == '10.30.40.0/30'
    assert row['subnet_id'] == ''
    assert row['prefix_match_status'] == 'unmatched'
    assert inventory['summary']['interface_unmatched_prefix'] == 1
