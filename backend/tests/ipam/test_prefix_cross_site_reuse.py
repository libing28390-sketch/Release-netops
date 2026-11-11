from __future__ import annotations

import pytest

from database import get_db_connection
from services.ipam_service import (
    create_subnet,
    list_subnets,
    update_subnet,
    rebuild_prefixes_hierarchy,
)
from services.ipam_address_space_service import create_address_space
from services.prefix_discovery_service import (
    _bind_discovered_gateway, _now, _upsert_candidate,
)


def test_prefix_hierarchy_uses_address_space_across_sites_not_tenant(isolated_db):
    _seed_prefix_scope()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants(id,name) VALUES ('tenant-other','Other') ON CONFLICT DO NOTHING")
        conn.commit()
    enterprise = create_address_space(
        name='Enterprise Global', kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    other_global = create_address_space(
        name='Other Global', kind='global', vrf_id=None,
        security_tenant_id='tenant-other',
    )
    parent = create_subnet(
        prefix='10.0.0.0/8', address_space_id=enterprise['id'],
        tenant_id='tenant-default', site_id='reuse-site-a',
    )
    local = create_subnet(
        prefix='10.1.0.0/16', address_space_id=enterprise['id'],
        tenant_id='tenant-default', site_id='reuse-site-a',
    )
    remote = create_subnet(
        prefix='10.2.0.0/16', address_space_id=enterprise['id'],
        tenant_id='tenant-default', site_id='reuse-site-b',
    )
    other = create_subnet(
        prefix='10.3.0.0/16', address_space_id=other_global['id'],
        tenant_id='tenant-other', site_id='reuse-site-a',
    )
    rebuild_prefixes_hierarchy()
    with get_db_connection() as conn:
        parents = {r['id']: r['parent_prefix_id'] for r in conn.execute('SELECT id,parent_prefix_id FROM prefixes').fetchall()}
    assert parents[local['id']] == parent['id']
    assert parents[remote['id']] == parent['id']
    assert not parents[other['id']]


def _seed_prefix_scope() -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING"
        )
        for site_id in ('reuse-site-a', 'reuse-site-b', 'reuse-site-c'):
            conn.execute(
                "INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (site_id, site_id.upper(), site_id),
            )
        for vrf_id in ('reuse-vrf-a', 'reuse-vrf-b', 'reuse-vrf-c'):
            conn.execute(
                "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES (?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING",
                (vrf_id, vrf_id),
            )
        conn.commit()


def test_cross_site_same_cidr_is_reuse_not_conflict_and_filters_match_summary(isolated_db) -> None:
    del isolated_db
    _seed_prefix_scope()
    first = create_subnet(
        prefix='10.255.0.1/32', name='Loopback A', tenant_id='tenant-default',
        site_id='reuse-site-a', vrf_id='reuse-vrf-a', network_type='loopback',
    )
    second = create_subnet(
        prefix='10.255.0.1/32', name='Loopback B', tenant_id='tenant-default',
        site_id='reuse-site-b', vrf_id='reuse-vrf-b', network_type='loopback',
    )

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE prefixes SET conflict_status = 'cross_site_prefix', conflict_json = '{}' WHERE id IN (?, ?)",
            (first['id'], second['id']),
        )
        conn.commit()

    inventory = list_subnets(page=1, page_size=10)
    rows = {item['id']: item for item in inventory['items']}
    assert inventory['total'] == 2
    assert rows[first['id']]['cross_site_reuse'] is False
    assert rows[second['id']]['cross_site_reuse'] is False
    assert rows[first['id']]['conflict_status'] == ''
    assert rows[second['id']]['conflict_status'] == ''
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 0
    assert list_subnets(classification='conflict', page=1, page_size=10)['total'] == 0

    from services.prefix_discovery_service import get_prefix_classification_summary

    summary = get_prefix_classification_summary()
    assert summary['total'] == 2
    assert summary['reuse_count'] == 0
    assert summary['conflict_count'] == 0
    assert summary['pending_duplicate_group_count'] == 0
    assert summary['pending_duplicate_record_count'] == 0
    site_summary = get_prefix_classification_summary(site='reuse-site-a')
    assert site_summary['total'] == 1
    assert site_summary['reuse_count'] == 0
    assert site_summary['conflict_count'] == 0

    # A distinct, non-legacy conflict remains visible and filterable.
    with get_db_connection() as conn:
        conn.execute("UPDATE prefixes SET conflict_status = 'address_overlap' WHERE id = ?", (first['id'],))
        conn.commit()
    assert get_prefix_classification_summary()['conflict_count'] == 1
    assert list_subnets(classification='conflict', page=1, page_size=10)['total'] == 1


def test_unmapped_cross_site_duplicate_cidr_is_pending_and_respects_visible_prefix_scope(isolated_db) -> None:
    del isolated_db
    _seed_prefix_scope()
    first = create_subnet(
        prefix='198.18.5.0/24', name='Mapped copy', tenant_id='tenant-default',
        site_id='reuse-site-a', vrf_id='reuse-vrf-a', network_type='user_access',
    )
    second = create_subnet(
        prefix='198.18.5.0/24', name='Unmapped copy', tenant_id='tenant-default',
        site_id='reuse-site-b', vrf_id='reuse-vrf-b', network_type='user_access',
    )

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE prefixes SET address_space_id = NULL, vrf_id = NULL WHERE id = ?",
            (second['id'],),
        )
        conn.commit()

    from services.prefix_discovery_service import get_prefix_classification_summary

    summary = get_prefix_classification_summary()
    assert summary['total'] == 2
    assert summary['address_space_pending_count'] == 1
    assert summary['reuse_count'] == 0
    assert summary['pending_duplicate_group_count'] == 1
    assert summary['pending_duplicate_record_count'] == 2

    site_summary = get_prefix_classification_summary(site='reuse-site-a')
    assert site_summary['total'] == 1
    assert site_summary['pending_duplicate_group_count'] == 1
    assert site_summary['pending_duplicate_record_count'] == 1

    # A hidden peer must not leak duplicate-CIDR metadata through the summary.
    visible_first_only = get_prefix_classification_summary(allowed_prefix_ids=[first['id']])
    assert visible_first_only['total'] == 1
    assert visible_first_only['pending_duplicate_group_count'] == 0
    assert visible_first_only['pending_duplicate_record_count'] == 0

    visible_pair = get_prefix_classification_summary(
        allowed_prefix_ids=[first['id'], second['id']],
    )
    assert visible_pair['pending_duplicate_group_count'] == 1
    assert visible_pair['pending_duplicate_record_count'] == 2


def test_prefix_scope_cannot_be_silently_moved_between_vrfs(isolated_db) -> None:
    del isolated_db
    _seed_prefix_scope()
    first = create_subnet(
        prefix='10.254.0.1/32', tenant_id='tenant-default',
        site_id='reuse-site-a', vrf_id='reuse-vrf-a', network_type='loopback',
    )
    second = create_subnet(
        prefix='10.254.0.1/32', tenant_id='tenant-default',
        site_id='reuse-site-b', vrf_id='reuse-vrf-b', network_type='loopback',
    )

    with pytest.raises(ValueError, match='routing domain'):
        update_subnet(second['id'], site_id='reuse-site-a', vrf_id='reuse-vrf-c')
    assert update_subnet(second['id'], site_id='reuse-site-a')
    updated = list_subnets(page=1, page_size=10)
    assert updated['total'] == 2
    assert all(item['cross_site_reuse'] is False for item in updated['items'])
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 0

    with pytest.raises(ValueError, match='already exists'):
        create_subnet(
            prefix='10.254.0.1/32', tenant_id='tenant-default',
            site_id='reuse-site-c', vrf_id='reuse-vrf-a', network_type='loopback',
        )


def test_discovery_upsert_reuses_same_space_prefix_without_rewriting_site(isolated_db) -> None:
    del isolated_db
    _seed_prefix_scope()
    candidate = {
        'prefix': '10.253.0.1/32',
        'tenant_id': 'tenant-default',
        'vrf_id': 'reuse-vrf-a',
        'network_type': 'loopback',
        'confidence': 0.98,
        'mixed_network': 0,
        'address_roles': [],
        'observed_devices': [],
        'observed_interfaces': [],
        'observed_vlans': [],
        'observed_vrfs': [],
        'evidence': [],
    }
    with get_db_connection() as conn:
        first_id, _, _ = _upsert_candidate(
            conn, {**candidate, 'site_id': 'reuse-site-a'}, 'test-run', _now()
        )
        second_id, action, _ = _upsert_candidate(
            conn, {**candidate, 'site_id': 'reuse-site-b'}, 'test-run', _now()
        )
        conn.commit()
        rows = conn.execute(
            "SELECT id, site_id, address_space_id, conflict_status FROM prefixes WHERE prefix = ?",
            (candidate['prefix'],),
        ).fetchall()
    assert first_id == second_id
    assert action == 'updated'
    assert len(rows) == 1
    assert rows[0]['site_id'] == 'reuse-site-a'
    assert rows[0]['address_space_id'] == 'as-vrf:reuse-vrf-a'
    assert rows[0]['conflict_status'] == ''
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 0


def test_pending_discovery_prefix_never_auto_binds_gateway(isolated_db) -> None:
    _seed_prefix_scope()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO devices(id, hostname, role, tenant_id, site_id) VALUES ('pending-gateway', 'Pending GW', 'distribution', 'tenant-default', 'reuse-site-a')"
        )
        conn.execute(
            """INSERT INTO interfaces
                   (id, device_id, interface_name, primary_ip, ip_address,
                    ip_prefix_length, interface_type, is_l3, vrf_id)
               VALUES ('pending-gateway-svi', 'pending-gateway', 'Vlanif30',
                       '10.252.0.1', '10.252.0.1', 24, 'svi', TRUE, '')"""
        )
        candidate = {
            'prefix': '10.252.0.0/24',
            'tenant_id': 'tenant-default',
            'site_id': 'reuse-site-a',
            'vrf_id': None,
            'network_type': 'unclassified',
            'confidence': 0.5,
            'mixed_network': 0,
            'address_roles': [],
            'observed_devices': ['pending-gateway'],
            'observed_interfaces': ['Vlanif30'],
            'observed_vlans': [],
            'observed_vrfs': [],
            'evidence': [],
        }
        prefix_id, _, scope_reason = _upsert_candidate(conn, candidate, 'pending-run', _now())
        assert prefix_id and scope_reason
        assert _bind_discovered_gateway(conn, prefix_id, candidate, _now()) is False
        row = conn.execute(
            "SELECT address_space_id, gateway, gateway_device_id, gateway_interface_id FROM prefixes WHERE id = ?",
            (prefix_id,),
        ).fetchone()
        assert row['address_space_id'] is None
        assert row['gateway'] == ''
        assert row['gateway_device_id'] is None
        assert row['gateway_interface_id'] is None
        conn.commit()
