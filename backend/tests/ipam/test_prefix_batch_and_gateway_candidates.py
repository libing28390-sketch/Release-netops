from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from core.interface_utils import normalize_interface_name
from database import get_db_connection
from schemas.schemas import BatchPrefixNetworkTypeUpdate
from services.cmdb_snapshot_service import begin_snapshot_attempt, complete_snapshot
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    batch_update_subnet_network_type,
    create_subnet,
    get_prefix_gateway_candidates,
)


def _seed_prefixes() -> tuple[dict, dict]:
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute("INSERT INTO sites (id, site_code, site_name) VALUES ('batch-site-a', 'BATCH-A', 'Batch A')")
        conn.execute("INSERT INTO sites (id, site_code, site_name) VALUES ('batch-site-b', 'BATCH-B', 'Batch B')")
        conn.commit()
    global_space = create_address_space(
        name='Prefix Batch Test Global',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    first = create_subnet(
        prefix='10.90.1.0/24', tenant_id='tenant-default', site_id='batch-site-a',
        address_space_id=global_space['id'],
        name='Batch A', network_type='server',
    )
    second = create_subnet(
        prefix='10.90.2.0/24', tenant_id='tenant-default', site_id='batch-site-b',
        address_space_id=global_space['id'],
        name='Batch B', network_type='server',
    )
    return first, second


def _read_prefixes(ids: list[str]) -> dict[str, dict]:
    placeholders = ', '.join('?' for _ in ids)
    with get_db_connection() as conn:
        rows = conn.execute(
            f'''SELECT id, revision, network_type, manual_override, manual_network_type,
                       classification_status, classification_source
                FROM prefixes WHERE id IN ({placeholders})''',
            tuple(ids),
        ).fetchall()
    return {str(row['id']): dict(row) for row in rows}


def _read_prefix_revisions(ids: list[str]) -> dict[str, int]:
    rows = _read_prefixes(ids)
    return {prefix_id: int(row.get('revision') or 1) for prefix_id, row in rows.items()}


def test_batch_network_type_update_sets_manual_protection_and_checks_each_scope(isolated_db, monkeypatch) -> None:
    del isolated_db
    first, second = _seed_prefixes()
    from api import ipam as ipam_api

    scope_checks: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        ipam_api,
        'enforce_resource_scope',
        lambda user, resource, action, **scope: scope_checks.append(
            (resource, action, str(scope.get('tenant_id')), str(scope.get('site_id')))
        ),
    )
    ids = [first['id'], second['id']]
    body = BatchPrefixNetworkTypeUpdate(
        ids=ids,
        network_type='loopback',
        expected_revisions=_read_prefix_revisions(ids),
    )
    response = ipam_api.api_batch_update_subnet_network_type(
        body,
        user={'username': 'operator', 'role': 'Operator'},
    )

    assert response['updated'] == 2
    assert response['network_type'] == 'loopback'
    assert set(scope_checks) == {
        ('prefix', 'update', 'tenant-default', 'batch-site-a'),
        ('prefix', 'update', 'tenant-default', 'batch-site-b'),
    }
    with get_db_connection() as conn:
        audit = conn.execute(
            "SELECT event_type, target_id FROM audit_events WHERE event_type = 'ipam.prefix.batch_update_network_type' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert audit is not None
    assert audit['target_id'] == 'batch'
    updated = _read_prefixes([first['id'], second['id']])
    for prefix_id in (first['id'], second['id']):
        assert updated[prefix_id]['network_type'] == 'loopback'
        assert updated[prefix_id]['manual_override'] == 1
        assert updated[prefix_id]['manual_network_type'] == 'loopback'
        assert updated[prefix_id]['classification_status'] == 'manual'
        assert updated[prefix_id]['classification_source'] == 'manual'


def test_batch_network_type_update_rolls_back_when_any_id_is_missing(isolated_db) -> None:
    del isolated_db
    first, second = _seed_prefixes()

    with pytest.raises(LookupError, match='not found'):
        batch_update_subnet_network_type([first['id'], 'missing-prefix'], 'loopback')

    unchanged = _read_prefixes([first['id'], second['id']])
    assert unchanged[first['id']]['network_type'] == 'server'
    assert unchanged[first['id']]['manual_override'] == 0
    assert unchanged[second['id']]['network_type'] == 'server'


def test_batch_network_type_scope_error_rolls_back_and_does_not_audit(isolated_db, monkeypatch) -> None:
    del isolated_db
    first, second = _seed_prefixes()
    from api import ipam as ipam_api

    checked_sites: list[str] = []

    def deny_after_first_scope(_user, _resource, _action, **scope):
        site_id = str(scope.get('site_id') or '')
        checked_sites.append(site_id)
        if len(checked_sites) == 2:
            raise HTTPException(status_code=403, detail='out of scope')

    monkeypatch.setattr(ipam_api, 'enforce_resource_scope', deny_after_first_scope)
    with pytest.raises(HTTPException) as denied:
        ids = [first['id'], second['id']]
        ipam_api.api_batch_update_subnet_network_type(
            BatchPrefixNetworkTypeUpdate(
                ids=ids,
                network_type='loopback',
                expected_revisions=_read_prefix_revisions(ids),
            ),
            user={'username': 'operator', 'role': 'Operator'},
        )

    assert denied.value.status_code == 403
    assert len(checked_sites) == 2
    assert set(checked_sites) == {'batch-site-a', 'batch-site-b'}
    with get_db_connection() as conn:
        audit_count = conn.execute(
            "SELECT COUNT(*) AS count FROM audit_events WHERE event_type = 'ipam.prefix.batch_update_network_type'"
        ).fetchone()['count']
    assert int(audit_count) == 0
    unchanged = _read_prefixes([first['id'], second['id']])
    assert unchanged[first['id']]['network_type'] == 'server'
    assert unchanged[second['id']]['network_type'] == 'server'


def test_batch_network_type_schema_rejects_values_outside_prefix_page_types() -> None:
    with pytest.raises(ValidationError):
        BatchPrefixNetworkTypeUpdate(
            ids=['prefix-one'],
            network_type='not-a-prefix-role',
            expected_revisions={'prefix-one': 1},
        )
    with pytest.raises(ValidationError):
        BatchPrefixNetworkTypeUpdate(
            ids=['prefix-one', 'prefix-one'],
            network_type='loopback',
            expected_revisions={'prefix-one': 1},
        )


def _seed_gateway_device(site_id: str, device_id: str, *, tenant_id: str = 'tenant-default') -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, tenant_id, site_id, status) VALUES (?, ?, ?, ?, ?, 'online')",
            (device_id, device_id.upper(), '192.0.2.1', tenant_id, site_id),
        )
        conn.commit()


def _publish_interface_observations(device_id: str, observations: list[dict]) -> None:
    attempt = begin_snapshot_attempt(device_id, 'interface_inventory')
    observed_at = '2026-10-28T10:00:00+00:00'
    with get_db_connection() as conn:
        for item in observations:
            conn.execute(
                """INSERT INTO cmdb_device_interface_observations (
                       device_id, normalized_interface_name, interface_name, description,
                       admin_status, oper_status, ip_address, ip_prefix_length,
                       interface_type, generation, observed_at, run_id, metadata_json
                   ) VALUES (?, ?, ?, '', 'up', 'up', ?, ?, ?, ?, ?, ?, '{}')""",
                (
                    device_id,
                    normalize_interface_name(item['interface_name']).strip().lower(),
                    item['interface_name'],
                    item['address'],
                    item['prefix_length'],
                    item['interface_type'],
                    attempt['generation'],
                    observed_at,
                    attempt['run_id'],
                ),
            )
            context_type = str(item.get('context_type') or 'unknown')
            if context_type != 'unknown':
                conn.execute(
                    """INSERT INTO cmdb_device_interface_address_observations (
                           device_id, normalized_interface_name, interface_name,
                           context_source, context_type, local_context_key,
                           local_context_name, ip_address, ip_prefix_length,
                           generation, observed_at, run_id, metadata_json
                       ) VALUES (?, ?, ?, 'cli', ?, ?, ?, ?::inet, ?, ?, ?::timestamptz, ?, '{}'::jsonb)""",
                    (
                        device_id,
                        normalize_interface_name(item['interface_name']).strip().lower(),
                        item['interface_name'], context_type, item['local_context_key'],
                        item.get('local_context_name') or item['local_context_key'],
                        item['address'], item['prefix_length'], attempt['generation'],
                        observed_at, attempt['run_id'],
                    ),
                )
        assert complete_snapshot(
            conn,
            attempt,
            observed_at=observed_at,
            transport='ssh',
            record_count=len(observations),
        )
        conn.commit()


def _seed_gateway_scope() -> None:
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-other', 'Other') ON CONFLICT(id) DO NOTHING")
        for site_id in ('gateway-site-a', 'gateway-site-b', 'gateway-site-p2p'):
            conn.execute(
                "INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (site_id, site_id.upper(), site_id),
            )
        conn.commit()


def test_vrfless_gateway_evidence_is_review_only_even_for_unique_svi(isolated_db) -> None:
    del isolated_db
    _seed_gateway_scope()
    _seed_gateway_device('gateway-site-a', 'gateway-device-svi')
    _publish_interface_observations('gateway-device-svi', [{
        'interface_name': 'Vlan-interface10',
        'address': '10.10.10.1',
        'prefix_length': 24,
        'interface_type': 'svi',
    }])
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO interfaces (id, device_id, interface_name, interface_type) VALUES (?, ?, ?, 'svi')",
            ('mapped-svi-id', 'gateway-device-svi', 'Vlan-interface10'),
        )
        conn.commit()

    configured = get_prefix_gateway_candidates(
        prefix='10.10.10.0/24', site_id='gateway-site-a', tenant_id='tenant-default', gateway_ip='10.10.10.1',
    )
    assert configured['status'] == 'scope_pending'
    assert configured['selected'] is None
    assert configured['endpoints'] == [{
        'device_id': 'gateway-device-svi',
        'device_name': 'GATEWAY-DEVICE-SVI',
        'interface_name': 'Vlan-interface10',
        'interface_id': 'mapped-svi-id',
        'address': '10.10.10.1',
        'interface_type': 'svi',
        'address_space_id': None,
        'context_source': 'cli',
        'context_type': 'unknown',
        'local_context_key': '',
        'scope_status': 'scope_pending',
    }]

    automatic = get_prefix_gateway_candidates(
        prefix='10.10.10.0/24', site_id='gateway-site-a', tenant_id='tenant-default',
    )
    assert automatic['status'] == 'scope_pending'


def test_explicit_device_context_mapping_allows_only_same_space_gateway_binding(isolated_db) -> None:
    del isolated_db
    _seed_gateway_scope()
    _seed_gateway_device('gateway-site-a', 'gateway-device-mapped')
    address_space = create_address_space(
        name='Gateway Explicit Global', kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    create_subnet(
        prefix='10.11.10.0/24', tenant_id='tenant-default',
        site_id='gateway-site-a', address_space_id=address_space['id'],
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts (
                   id, device_id, context_source, context_type, local_context_key,
                   local_context_name, address_space_id, status, revision,
                   created_at, updated_at
               ) VALUES ('gateway-global-context', 'gateway-device-mapped', 'cli',
                         'global', '--', '--', ?, 'active', 1,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (address_space['id'],),
        )
        conn.commit()
    _publish_interface_observations('gateway-device-mapped', [{
        'interface_name': 'Vlan-interface11',
        'address': '10.11.10.1',
        'prefix_length': 24,
        'interface_type': 'svi',
        'context_type': 'global',
        'local_context_key': '--',
    }])

    result = get_prefix_gateway_candidates(
        prefix='10.11.10.0/24', site_id='gateway-site-a',
        tenant_id='tenant-default', gateway_ip='10.11.10.1',
        address_space_id=address_space['id'],
    )
    assert result['status'] == 'matched'
    assert result['address_space_id'] == address_space['id']
    assert result['selected']['device_id'] == 'gateway-device-mapped'
    assert result['selected']['scope_status'] == 'resolved'


def test_same_site_gateway_ip_is_isolated_between_explicit_address_spaces(isolated_db) -> None:
    del isolated_db
    _seed_gateway_scope()
    _seed_gateway_device('gateway-site-a', 'gateway-device-space-a')
    _seed_gateway_device('gateway-site-a', 'gateway-device-space-b')
    space_a = create_address_space(
        name='Gateway Same Site Space A', kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    space_b = create_address_space(
        name='Gateway Same Site Space B', kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    for prefix_space, device_id, context_id in (
        (space_a, 'gateway-device-space-a', 'gateway-context-space-a'),
        (space_b, 'gateway-device-space-b', 'gateway-context-space-b'),
    ):
        create_subnet(
            prefix='10.20.30.0/24', tenant_id='tenant-default',
            site_id='gateway-site-a', address_space_id=prefix_space['id'],
        )
        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO ipam_device_routing_contexts (
                       id, device_id, context_source, context_type, local_context_key,
                       local_context_name, address_space_id, status, revision,
                       created_at, updated_at
                   ) VALUES (?, ?, 'cli', 'global', '--', '--', ?, 'active', 1,
                             CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (context_id, device_id, prefix_space['id']),
            )
            conn.commit()
        _publish_interface_observations(device_id, [{
            'interface_name': 'Vlan-interface30',
            'address': '10.20.30.1',
            'prefix_length': 24,
            'interface_type': 'svi',
            'context_type': 'global',
            'local_context_key': '--',
        }])

    result_a = get_prefix_gateway_candidates(
        prefix='10.20.30.0/24', site_id='gateway-site-a', tenant_id='tenant-default',
        gateway_ip='10.20.30.1', address_space_id=space_a['id'],
    )
    result_b = get_prefix_gateway_candidates(
        prefix='10.20.30.0/24', site_id='gateway-site-a', tenant_id='tenant-default',
        gateway_ip='10.20.30.1', address_space_id=space_b['id'],
    )

    assert result_a['status'] == 'matched'
    assert result_a['selected']['device_id'] == 'gateway-device-space-a'
    assert result_b['status'] == 'matched'
    assert result_b['selected']['device_id'] == 'gateway-device-space-b'


def test_physical_point_to_point_endpoints_are_returned_without_gateway_guess(isolated_db) -> None:
    del isolated_db
    _seed_gateway_scope()
    _seed_gateway_device('gateway-site-p2p', 'gateway-r2')
    _seed_gateway_device('gateway-site-p2p', 'gateway-r4')
    _publish_interface_observations('gateway-r2', [{
        'interface_name': 'GigabitEthernet1/0/1',
        'address': '10.0.30.1',
        'prefix_length': 30,
        'interface_type': 'physical',
    }])
    _publish_interface_observations('gateway-r4', [{
        'interface_name': 'GigabitEthernet1/0/1',
        'address': '10.0.30.2',
        'prefix_length': 30,
        'interface_type': 'physical',
    }])

    result = get_prefix_gateway_candidates(
        prefix='10.0.30.0/30', site_id='gateway-site-p2p', tenant_id='tenant-default',
    )
    assert result['status'] == 'scope_pending'
    assert result['selected'] is None
    assert [item['address'] for item in result['endpoints']] == ['10.0.30.1', '10.0.30.2']
    assert {item['device_name'] for item in result['endpoints']} == {'GATEWAY-R2', 'GATEWAY-R4'}


def test_gateway_candidates_respect_site_and_tenant_and_require_site(isolated_db) -> None:
    del isolated_db
    _seed_gateway_scope()
    _seed_gateway_device('gateway-site-a', 'gateway-device-a')
    _seed_gateway_device('gateway-site-b', 'gateway-device-b')
    _seed_gateway_device('gateway-site-a', 'gateway-device-other-tenant', tenant_id='tenant-other')
    for device_id in ('gateway-device-a', 'gateway-device-b', 'gateway-device-other-tenant'):
        _publish_interface_observations(device_id, [{
            'interface_name': 'Vlan-interface20',
            'address': '10.20.20.1',
            'prefix_length': 24,
            'interface_type': 'svi',
        }])

    scoped = get_prefix_gateway_candidates(
        prefix='10.20.20.0/24', site_id='gateway-site-a', tenant_id='tenant-default',
    )
    assert scoped['status'] == 'scope_pending'
    assert [item['device_id'] for item in scoped['endpoints']] == ['gateway-device-a']
    assert scoped['selected'] is None

    missing_site = get_prefix_gateway_candidates(
        prefix='10.20.20.0/24', site_id=None, tenant_id='tenant-default',
    )
    assert missing_site['status'] == 'needs_site'
    assert missing_site['endpoints'] == []
