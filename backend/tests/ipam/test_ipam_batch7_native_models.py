from __future__ import annotations

import pytest

from database import get_db_connection
from services.cmdb_service import create_vlan, create_vrf
from services.ipam_address_space_service import create_address_space
from services.ipam_native_models_service import (
    assign_vlan_to_group,
    create_aggregate,
    create_asn,
    create_rir,
    create_route_target,
    create_vlan_group,
    delete_aggregate,
    delete_asn,
    delete_rir,
    delete_route_target,
    delete_vlan_group,
    get_vrf_route_targets,
    list_aggregates,
    list_asns,
    list_rirs,
    list_route_targets,
    list_vlan_groups,
    set_vrf_route_targets,
)
from services.ipam_service import create_subnet


def test_vlan_group_scope_vid_bounds_and_uniqueness(isolated_db) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO sites (id, site_code, site_name, tenant_id) VALUES ('site-vlg-1', 'S1', 'Site 1', 'tenant-default')"
        )
        conn.execute(
            "INSERT INTO sites (id, site_code, site_name, tenant_id) VALUES ('site-vlg-2', 'S2', 'Site 2', 'tenant-default')"
        )
        v100 = create_vlan(conn, vlan_id=100, name='VLAN-100', site_id='site-vlg-1', tenant_id='tenant-default')
        v100_dup = create_vlan(conn, vlan_id=100, name='VLAN-100-B', site_id=None, tenant_id='tenant-default')
        v500 = create_vlan(conn, vlan_id=500, name='VLAN-500', site_id='site-vlg-1', tenant_id='tenant-default')
        v_other_site = create_vlan(conn, vlan_id=120, name='VLAN-120', site_id='site-vlg-2', tenant_id='tenant-default')
        conn.commit()

    group = create_vlan_group(
        name='DC1-Access-VLANs',
        scope_type='site',
        scope_id='site-vlg-1',
        min_vid=100,
        max_vid=200,
        tenant_id='tenant-default',
    )
    assigned = assign_vlan_to_group(v100['id'], group['id'], tenant_id='tenant-default')
    assert assigned['vlan_group_id'] == group['id']

    # Out of VID range rejected
    with pytest.raises(ValueError, match='outside VLAN Group'):
        assign_vlan_to_group(v500['id'], group['id'], tenant_id='tenant-default')

    # Cross-site VLAN rejected
    with pytest.raises(ValueError, match='does not match the VLAN Group site scope'):
        assign_vlan_to_group(v_other_site['id'], group['id'], tenant_id='tenant-default')

    # Duplicate VID inside same VLAN Group rejected
    with pytest.raises(ValueError, match='already exists in VLAN Group'):
        assign_vlan_to_group(v100_dup['id'], group['id'], tenant_id='tenant-default')

    groups = list_vlan_groups(tenant_id='tenant-default')
    assert len(groups) == 1
    assert groups[0]['vlan_count'] == 1
    assert delete_vlan_group(group['id'], tenant_id='tenant-default') is True


def test_route_targets_and_vrf_import_export_relationships(isolated_db) -> None:
    with get_db_connection() as conn:
        vrf = create_vrf(conn, vrf_name='VRF-EVPN', rd='65010:1', tenant_id='tenant-default')
        conn.commit()

    with pytest.raises(ValueError, match='ASN:nn or IP:nn'):
        create_route_target(name='invalid-rt', tenant_id='tenant-default')

    rt_imp = create_route_target(name='65010:100', description='Shared import', tenant_id='tenant-default')
    rt_exp = create_route_target(name='65010:200', description='Service export', tenant_id='tenant-default')
    assert len(list_route_targets(tenant_id='tenant-default')) == 2

    bound = set_vrf_route_targets(
        vrf['id'],
        import_target_ids=[rt_imp['id']],
        export_target_ids=[rt_imp['id'], rt_exp['id']],
        tenant_id='tenant-default',
    )
    assert [t['name'] for t in bound['import_targets']] == ['65010:100']
    assert [t['name'] for t in bound['export_targets']] == ['65010:100', '65010:200']

    fetched = get_vrf_route_targets(vrf['id'], tenant_id='tenant-default')
    assert fetched == bound
    assert delete_route_target(rt_exp['id'], tenant_id='tenant-default') is True


def test_rirs_aggregates_and_asns_crud_and_integrity(isolated_db) -> None:
    rir = create_rir(name='RFC 1918', is_private=True, description='Private IPv4', tenant_id='tenant-default')
    agg = create_aggregate(prefix='10.0.0.0/8', rir_id=rir['id'], date_added='2026-11-20', tenant_id='tenant-default')
    asn = create_asn(asn=65010, rir_id=rir['id'], description='Core BGP AS', tenant_id='tenant-default')

    # Overlapping aggregate rejected
    with pytest.raises(ValueError, match='overlaps existing Aggregate'):
        create_aggregate(prefix='10.10.0.0/16', rir_id=rir['id'], tenant_id='tenant-default')

    # Duplicate ASN rejected
    with pytest.raises(ValueError, match='already exists'):
        create_asn(asn=65010, rir_id=rir['id'], tenant_id='tenant-default')

    # Child prefix count reflected on Aggregate
    space = create_address_space(name='Agg-Space', kind='global', vrf_id=None, security_tenant_id='tenant-default')
    create_subnet(prefix='10.88.1.0/24', address_space_id=space['id'], tenant_id='tenant-default')
    aggs = list_aggregates(tenant_id='tenant-default', rir_id=rir['id'])
    assert len(aggs) == 1
    assert aggs[0]['child_prefix_count'] == 1
    assert len(list_asns(tenant_id='tenant-default')) == 1

    # RIR cannot be deleted while referenced by Aggregate or ASN
    with pytest.raises(ValueError, match='Aggregates reference it'):
        delete_rir(rir['id'], tenant_id='tenant-default')
    assert delete_aggregate(agg['id'], tenant_id='tenant-default') is True
    with pytest.raises(ValueError, match='ASNs reference it'):
        delete_rir(rir['id'], tenant_id='tenant-default')
    assert delete_asn(asn['id'], tenant_id='tenant-default') is True
    assert delete_rir(rir['id'], tenant_id='tenant-default') is True
    assert list_rirs(tenant_id='tenant-default') == []
