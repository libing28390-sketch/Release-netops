from __future__ import annotations

from database import get_db_connection
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.ipam_service import (
    create_subnet,
    generate_interface_prefixes,
    preview_interface_prefixes,
)


def _seed_scope() -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants(id, name) VALUES ('tenant-default', 'Default') ON CONFLICT DO NOTHING"
        )
        conn.execute(
            "INSERT INTO sites(id, site_code, site_name) VALUES ('snapshot-candidate-site', 'SNAP-CAND', 'Snapshot Candidate Site')"
        )
        conn.execute(
            "INSERT INTO devices(id, hostname, tenant_id, site_id, status) VALUES ('snapshot-candidate-device', 'SW-SNAPSHOT-CAND', 'tenant-default', 'snapshot-candidate-site', 'online')"
        )
        conn.commit()


def _publish_snapshot_ip(address: str, *, interface: str = 'Vlan-interface50', mask: int = 24) -> None:
    attempt = begin_snapshot_attempt('snapshot-candidate-device', 'interface_inventory')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations (
                   device_id, normalized_interface_name, interface_name, description,
                   admin_status, oper_status, ip_address, ip_prefix_length,
                   interface_type, generation, observed_at, run_id, metadata_json
               ) VALUES ('snapshot-candidate-device', ?, ?, '', 'up', 'up', ?, ?, 'svi', ?, ?, ?, '{}')""",
            (interface.lower(), interface, address, mask, attempt['generation'],
             '2026-10-28T10:00:00+00:00', attempt['run_id']),
        )
        assert complete_snapshot(
            conn, attempt, observed_at='2026-10-28T10:00:00+00:00',
            transport='ssh', record_count=1,
        )
        conn.commit()


def test_snapshot_candidates_default_to_global_and_are_bulk_generatable(isolated_db):
    _seed_scope()
    _publish_snapshot_ip('10.88.50.1')

    preview = preview_interface_prefixes(page_size=100)
    assert preview['interface_count'] == 1
    assert preview['scope_pending_count'] == 0
    assert preview['vrf_defaulted_count'] == 1
    candidate = preview['candidates'][0]
    assert candidate['prefix'] == '10.88.50.0/24'
    assert candidate['status'] == 'to_create'
    assert candidate['vrf_id'] is None
    assert candidate['vrf_scope_defaulted'] is True
    assert candidate['interfaces'][0]['interface_id'] is None
    global_default_preview = preview_interface_prefixes(status='global_default', page_size=100)
    assert global_default_preview['candidate_count'] == 1
    assert global_default_preview['candidates'][0]['candidate_id'] == candidate['candidate_id']

    result = generate_interface_prefixes(all_pending=True)
    assert result['created_prefixes'] == 1
    assert result['created_addresses'] == 1
    assert result['defaulted_vrf_scopes'] == [{
        'prefix': '10.88.50.0/24', 'tenant_id': 'tenant-default',
        'site_id': 'snapshot-candidate-site', 'vrf_id': '',
        'source': 'snapshot_missing_vrf_defaulted_global',
    }]
    with get_db_connection() as conn:
        prefix = conn.execute(
            "SELECT id, vrf_id, network_type FROM prefixes WHERE prefix='10.88.50.0/24'"
        ).fetchone()
        address = conn.execute(
            "SELECT source_type, source_ref, interface_id FROM ip_addresses WHERE address='10.88.50.1'"
        ).fetchone()
    assert prefix['vrf_id'] in ('', None)
    assert prefix['network_type'] == 'unclassified'
    assert address['source_type'] == 'interface_collection'
    assert address['source_ref'] == 'cmdb-interface:snapshot-candidate-device:vlan-interface50'
    # The existing IPAM schema uses an empty string to represent an unlinked
    # optional interface reference; the CMDB observation is still identified
    # by source_ref and is not attached to a mutable interfaces row.
    assert address['interface_id'] in ('', None)


def test_snapshot_global_default_can_be_overridden_to_tenant_vrf(isolated_db):
    _seed_scope()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('snapshot-candidate-vrf-override', 'SNAP-OVERRIDE', 'tenant-default')"
        )
        conn.commit()
    _publish_snapshot_ip('10.88.53.1')

    candidate = preview_interface_prefixes(page_size=100)['candidates'][0]
    result = generate_interface_prefixes(
        candidate_ids=[candidate['candidate_id']],
        vrf_overrides={candidate['candidate_id']: 'snapshot-candidate-vrf-override'},
    )
    assert result['created_prefixes'] == 1
    assert result['confirmed_vrf_scopes'] == [{
        'prefix': '10.88.53.0/24', 'tenant_id': 'tenant-default',
        'site_id': 'snapshot-candidate-site', 'vrf_id': 'snapshot-candidate-vrf-override',
    }]
    with get_db_connection() as conn:
        prefix = conn.execute(
            "SELECT vrf_id FROM prefixes WHERE prefix='10.88.53.0/24'"
        ).fetchone()
    assert prefix['vrf_id'] == 'snapshot-candidate-vrf-override'


def test_unique_existing_prefix_resolves_snapshot_vrf_and_can_register_ip(isolated_db):
    _seed_scope()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('snapshot-candidate-vrf', 'SNAPSHOT-VRF', 'tenant-default')"
        )
        conn.commit()
    prefix = create_subnet(
        prefix='10.88.51.0/24', tenant_id='tenant-default',
        site_id='snapshot-candidate-site', vrf_id='snapshot-candidate-vrf',
        network_type='server',
    )
    _publish_snapshot_ip('10.88.51.1')

    candidate = preview_interface_prefixes(page_size=100)['candidates'][0]
    assert candidate['status'] == 'existing'
    assert candidate['vrf_id'] == 'snapshot-candidate-vrf'
    result = generate_interface_prefixes(candidate_ids=[candidate['candidate_id']])
    assert result['created_prefixes'] == 0
    assert result['existing_prefixes'] == 1
    assert result['created_addresses'] == 1
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT subnet_id, source_ref FROM ip_addresses WHERE address='10.88.51.1'"
        ).fetchone()
    assert row['subnet_id'] == prefix['id']
    assert row['source_ref'] == 'cmdb-interface:snapshot-candidate-device:vlan-interface50'


def test_snapshot_backed_devices_do_not_duplicate_legacy_interfaces(isolated_db):
    _seed_scope()
    _publish_snapshot_ip('10.88.52.1')
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO interfaces(id, device_id, interface_name, primary_ip, ip_prefix_length, vrf_id, is_l3)
               VALUES ('legacy-duplicate-interface', 'snapshot-candidate-device', 'Vlan-interface50', '10.88.99.1', 24, '', TRUE)"""
        )
        conn.commit()

    preview = preview_interface_prefixes(page_size=100)
    assert preview['interface_count'] == 1
    assert [item['address'] for candidate in preview['candidates'] for item in candidate['interfaces']] == ['10.88.52.1']
