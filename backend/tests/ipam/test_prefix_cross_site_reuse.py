from __future__ import annotations

from database import get_db_connection
from services.ipam_service import (
    create_subnet,
    delete_subnet,
    list_subnets,
    update_subnet,
    rebuild_prefixes_hierarchy,
)
from services.prefix_discovery_service import _now, _upsert_candidate


def test_prefix_hierarchy_does_not_cross_site_or_tenant(isolated_db):
    _seed_prefix_scope()
    parent = create_subnet(prefix='10.0.0.0/8', tenant_id='tenant-default', site_id='reuse-site-a')
    local = create_subnet(prefix='10.1.0.0/16', tenant_id='tenant-default', site_id='reuse-site-a')
    remote = create_subnet(prefix='10.2.0.0/16', tenant_id='tenant-default', site_id='reuse-site-b')
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants(id,name) VALUES ('tenant-other','Other') ON CONFLICT DO NOTHING")
        conn.commit()
    other = create_subnet(prefix='10.3.0.0/16', tenant_id='tenant-other', site_id='reuse-site-a')
    rebuild_prefixes_hierarchy()
    with get_db_connection() as conn:
        parents = {r['id']: r['parent_prefix_id'] for r in conn.execute('SELECT id,parent_prefix_id FROM prefixes').fetchall()}
    assert parents[local['id']] == parent['id']
    assert not parents[remote['id']]
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
    assert rows[first['id']]['cross_site_reuse'] is True
    assert rows[second['id']]['cross_site_reuse'] is True
    assert rows[first['id']]['conflict_status'] == ''
    assert rows[second['id']]['conflict_status'] == ''
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 2
    assert list_subnets(classification='conflict', page=1, page_size=10)['total'] == 0

    from services.prefix_discovery_service import get_prefix_classification_summary

    summary = get_prefix_classification_summary()
    assert summary['total'] == 2
    assert summary['reuse_count'] == 2
    assert summary['conflict_count'] == 0
    site_summary = get_prefix_classification_summary(site='reuse-site-a')
    assert site_summary['total'] == 1
    assert site_summary['reuse_count'] == 1
    assert site_summary['conflict_count'] == 0

    # A distinct, non-legacy conflict remains visible and filterable.
    with get_db_connection() as conn:
        conn.execute("UPDATE prefixes SET conflict_status = 'address_overlap' WHERE id = ?", (first['id'],))
        conn.commit()
    assert get_prefix_classification_summary()['conflict_count'] == 1
    assert list_subnets(classification='conflict', page=1, page_size=10)['total'] == 1


def test_cross_site_reuse_updates_dynamically_after_manual_update_and_delete(isolated_db) -> None:
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

    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 2
    assert update_subnet(second['id'], site_id='reuse-site-a', vrf_id='reuse-vrf-c')
    updated = list_subnets(page=1, page_size=10)
    assert updated['total'] == 2
    assert all(item['cross_site_reuse'] is False for item in updated['items'])
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 0

    third = create_subnet(
        prefix='10.254.0.1/32', tenant_id='tenant-default',
        site_id='reuse-site-c', vrf_id='reuse-vrf-a', network_type='loopback',
    )
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 3
    assert delete_subnet(third['id'])
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 0


def test_discovery_upsert_does_not_persist_cross_site_reuse_as_conflict(isolated_db) -> None:
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
        for site_id in ('reuse-site-a', 'reuse-site-b'):
            _upsert_candidate(conn, {**candidate, 'site_id': site_id}, 'test-run', _now())
        conn.commit()
        statuses = conn.execute(
            "SELECT conflict_status FROM prefixes WHERE prefix = ? ORDER BY site_id",
            (candidate['prefix'],),
        ).fetchall()
    assert [row['conflict_status'] for row in statuses] == ['', '']
    assert list_subnets(classification='reuse', page=1, page_size=10)['total'] == 2
