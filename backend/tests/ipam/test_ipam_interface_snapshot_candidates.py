from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from database import get_db_connection
from services import ipam_service
from services.cmdb_snapshot_service import (
    begin_snapshot_attempt,
    complete_snapshot,
    fail_snapshot_attempt,
)
from services.ipam_address_space_service import create_address_space
from services.ipam_service import (
    allocate_next_address,
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


def _publish_snapshot_ip(
    address: str,
    *,
    interface: str = 'Vlan-interface50',
    mask: int = 24,
    context_type: str = 'unknown',
    local_context_key: str = '',
) -> None:
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
        if context_type != 'unknown':
            conn.execute(
                """INSERT INTO cmdb_device_interface_address_observations (
                       device_id, normalized_interface_name, interface_name,
                       context_source, context_type, local_context_key,
                       local_context_name, ip_address, ip_prefix_length,
                       generation, observed_at, run_id, metadata_json
                   ) VALUES ('snapshot-candidate-device', ?, ?, 'cli', ?, ?, ?, ?::inet,
                             ?, ?, CURRENT_TIMESTAMP, ?, '{}'::jsonb)""",
                (
                    interface.lower(), interface, context_type, local_context_key,
                    local_context_key, address, mask, attempt['generation'], attempt['run_id'],
                ),
            )
        assert complete_snapshot(
            conn, attempt, observed_at='2026-10-28T10:00:00+00:00',
            transport='ssh', record_count=1,
        )
        conn.commit()


def test_snapshot_candidates_without_vrf_require_explicit_global_and_are_not_bulk_generated(isolated_db):
    _seed_scope()
    _publish_snapshot_ip('10.88.50.1')

    preview = preview_interface_prefixes(page_size=100)
    assert preview['interface_count'] == 1
    assert preview['scope_pending_count'] == 1
    assert preview['vrf_pending_count'] == 1
    assert preview['vrf_defaulted_count'] == 0
    candidate = preview['candidates'][0]
    assert candidate['prefix'] == '10.88.50.0/24'
    assert candidate['status'] == 'scope_pending'
    assert candidate['vrf_id'] is None
    assert candidate['vrf_scope_pending'] is True
    assert candidate['vrf_scope_defaulted'] is False
    assert candidate['interfaces'][0]['interface_id'] is None
    global_default_preview = preview_interface_prefixes(status='global_default', page_size=100)
    assert global_default_preview['candidates'] == []

    result = generate_interface_prefixes(all_pending=True)
    assert result['created_prefixes'] == 0
    assert result['created_addresses'] == 0
    assert result['defaulted_vrf_scopes'] == []
    with get_db_connection() as conn:
        assert conn.execute("SELECT 1 FROM prefixes WHERE prefix='10.88.50.0/24'").fetchone() is None
        assert conn.execute("SELECT 1 FROM ip_addresses WHERE address='10.88.50.1'").fetchone() is None

    global_space = create_address_space(
        name='Snapshot Candidate Global',
        kind='global',
        vrf_id=None,
        security_tenant_id='tenant-default',
    )
    result = generate_interface_prefixes(
        candidate_ids=[candidate['candidate_id']],
        address_space_overrides={candidate['candidate_id']: global_space['id']},
    )
    assert result['created_prefixes'] == 1
    assert result['created_addresses'] == 1
    assert result['confirmed_vrf_scopes'] == [{
        'prefix': '10.88.50.0/24', 'tenant_id': 'tenant-default',
        'site_id': 'snapshot-candidate-site', 'vrf_id': '',
    }]
    with get_db_connection() as conn:
        prefix = conn.execute(
            "SELECT id, vrf_id, network_type FROM prefixes WHERE prefix='10.88.50.0/24'"
        ).fetchone()
        address = conn.execute(
            "SELECT source_type, source_ref, interface_id, purpose, device_type FROM ip_addresses WHERE address='10.88.50.1'"
        ).fetchone()
    assert prefix['vrf_id'] in ('', None)
    assert prefix['network_type'] == 'unclassified'
    assert address['source_type'] == 'interface_collection'
    assert address['purpose'] == address['device_type'] == 'gateway'
    assert address['source_ref'] == 'cmdb-interface:snapshot-candidate-device:vlan-interface50:cli:unknown::10.88.50.1'
    # The existing IPAM schema uses an empty string to represent an unlinked
    # optional interface reference; the CMDB observation is still identified
    # by source_ref and is not attached to a mutable interfaces row.
    assert address['interface_id'] in ('', None)


def test_snapshot_unknown_vrf_can_be_overridden_to_tenant_vrf(isolated_db):
    _seed_scope()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs(id, vrf_name, tenant_id) VALUES ('snapshot-candidate-vrf-override', 'SNAP-OVERRIDE', 'tenant-default')"
        )
        conn.commit()
    _publish_snapshot_ip('10.88.53.1')

    candidate = preview_interface_prefixes(page_size=100)['candidates'][0]
    assert candidate['status'] == 'scope_pending'
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


def test_unique_existing_prefix_does_not_resolve_unmapped_snapshot_context(isolated_db):
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
    assert candidate['status'] == 'scope_pending'
    assert candidate['address_space_id'] is None
    assert candidate['vrf_id'] is None
    with get_db_connection() as conn:
        existing_space_id = conn.execute(
            "SELECT id FROM ipam_address_spaces WHERE vrf_id = ?",
            ('snapshot-candidate-vrf',),
        ).fetchone()['id']
    result = generate_interface_prefixes(
        candidate_ids=[candidate['candidate_id']],
        address_space_overrides={
            candidate['candidate_id']: existing_space_id,
        },
    )
    assert result['created_prefixes'] == 0
    assert result['existing_prefixes'] == 1
    assert result['created_addresses'] == 1
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT subnet_id, source_ref FROM ip_addresses WHERE address='10.88.51.1'"
        ).fetchone()
    assert row['subnet_id'] == prefix['id']
    assert row['source_ref'] == 'cmdb-interface:snapshot-candidate-device:vlan-interface50:cli:unknown::10.88.51.1'


def test_explicitly_mapped_context_generates_in_its_address_space(isolated_db):
    _seed_scope()
    global_space = create_address_space(
        name='Mapped Snapshot Global', kind='global', vrf_id=None,
        security_tenant_id='tenant-default',
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts (
                   id, device_id, context_source, context_type, local_context_key,
                   local_context_name, address_space_id, status, revision,
                   created_at, updated_at
               ) VALUES ('snapshot-global-context', 'snapshot-candidate-device',
                         'cli', 'global', '--', '--', ?, 'active', 1,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (global_space['id'],),
        )
        conn.commit()
    _publish_snapshot_ip('10.88.55.1', context_type='global', local_context_key='--')

    candidate = preview_interface_prefixes(page_size=100)['candidates'][0]
    assert candidate['status'] == 'to_create'
    assert candidate['address_space_id'] == global_space['id']
    result = generate_interface_prefixes(candidate_ids=[candidate['candidate_id']])
    assert result['created_prefixes'] == 1
    assert result['created_addresses'] == 1
    with get_db_connection() as conn:
        prefix = conn.execute(
            "SELECT address_space_id FROM prefixes WHERE prefix='10.88.55.0/24'"
        ).fetchone()
    assert prefix['address_space_id'] == global_space['id']


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


def test_first_failed_snapshot_attempt_keeps_legacy_interface_fallback(isolated_db):
    _seed_scope()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO interfaces(
                   id, device_id, interface_name, primary_ip,
                   ip_prefix_length, vrf_id, is_l3
               ) VALUES (
                   'legacy-before-first-success', 'snapshot-candidate-device',
                   'Vlan-interface54', '10.88.54.1', 24, '', TRUE
               )"""
        )
        conn.commit()

    attempt = begin_snapshot_attempt('snapshot-candidate-device', 'interface_inventory')
    fail_snapshot_attempt(attempt, error_code='connection_failed')

    preview = preview_interface_prefixes(page_size=100)
    assert preview['interface_count'] == 1
    assert preview['candidates'][0]['prefix'] == '10.88.54.0/24'
    assert preview['candidates'][0]['interfaces'][0]['interface_id'] == 'legacy-before-first-success'


def test_interface_generation_and_manual_allocation_cannot_claim_same_address_concurrently(
    isolated_db, monkeypatch,
):
    del isolated_db
    site_id = f"generation-race-site-{uuid4().hex[:8]}"
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, 'tenant-default')""",
            (site_id, site_id.upper(), site_id),
        )
        conn.commit()
    space = create_address_space(
        name=f"Generation race {uuid4().hex}",
        kind='global', vrf_id=None, security_tenant_id='tenant-default',
    )
    parent = create_subnet(
        prefix='198.18.40.0/24', address_space_id=space['id'],
        site_id=site_id, gateway='198.18.40.1', name='Concurrent generation parent',
    )

    candidate_id = 'concurrent-interface-candidate'
    candidate = {
        'candidate_id': candidate_id,
        'prefix': '198.18.40.0/25',
        'tenant_id': 'tenant-default',
        'site_id': site_id,
        'address_space_id': space['id'],
        'vrf_id': None,
        'status': 'to_create',
        'vrf_scope_pending': False,
        'vrf_scope_defaulted': False,
        'interfaces': [{
            'interface_id': None,
            'source_ref': 'synthetic-current-interface',
            'device_id': '',
            'device_name': 'SW-GENERATION-RACE',
            'interface_name': 'Vlan40',
            'address': '198.18.40.2',
        }],
    }

    def candidate_preview(_conn, **_kwargs):
        # Return a fresh row on each call because generation normalizes selected
        # scope fields before the transaction writes.
        return {
            'source': 'cmdb_interface_snapshot',
            'source_label': 'current snapshot fixture',
            'candidate_count': 1,
            'existing_count': 0,
            'to_create_count': 1,
            'interface_count': 1,
            'scope_pending_count': 0,
            'vrf_pending_count': 0,
            'vrf_defaulted_count': 0,
            'skipped_count': 0,
            'candidates': [{**candidate, 'interfaces': [dict(candidate['interfaces'][0])]}],
            'skipped': [],
            'skipped_truncated_count': 0,
        }

    original_get_connection = ipam_service.get_db_connection

    def bounded_connection():
        conn = original_get_connection()
        conn.execute("SET lock_timeout = '4s'")
        conn.execute("SET statement_timeout = '8s'")
        return conn

    monkeypatch.setattr(ipam_service, '_load_interface_prefix_candidates', candidate_preview)
    monkeypatch.setattr(ipam_service, 'get_db_connection', bounded_connection)
    start_together = Barrier(2)

    def generate_from_interface():
        start_together.wait(timeout=5)
        return ipam_service.generate_interface_prefixes(candidate_ids=[candidate_id])

    def allocate_manually():
        start_together.wait(timeout=5)
        return allocate_next_address(parent['id'], purpose='management')

    with ThreadPoolExecutor(max_workers=2) as executor:
        generate_future = executor.submit(generate_from_interface)
        allocate_future = executor.submit(allocate_manually)
        generation_result = generate_future.result(timeout=20)
        allocation_result = allocate_future.result(timeout=20)

    assert generation_result['ok'] is True
    assert allocation_result['address'] in {'198.18.40.2', '198.18.40.3'}
    with get_db_connection() as conn:
        same_host_rows = conn.execute(
            """SELECT id, subnet_id FROM ip_addresses
                 WHERE address_space_id = ? AND address = '198.18.40.2'""",
            (space['id'],),
        ).fetchall()
        allocated_rows = conn.execute(
            "SELECT address FROM ip_addresses WHERE address_space_id = ? ORDER BY address",
            (space['id'],),
        ).fetchall()
    assert len(same_host_rows) == 1
    assert {str(row['address']) for row in allocated_rows} in (
        {'198.18.40.2'}, {'198.18.40.2', '198.18.40.3'},
    )


def test_interface_prefix_generation_replays_same_idempotency_request(isolated_db) -> None:
    _seed_scope()
    global_space = create_address_space(
        name="Snapshot idempotency Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO ipam_device_routing_contexts (
                   id, device_id, context_source, context_type, local_context_key,
                   local_context_name, address_space_id, status, revision,
                   created_at, updated_at
               ) VALUES ('snapshot-idempotency-global', 'snapshot-candidate-device',
                         'cli', 'global', '--', '--', ?, 'active', 1,
                         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (global_space["id"],),
        )
        conn.commit()
    _publish_snapshot_ip("10.88.70.1", context_type="global", local_context_key="--")
    candidate = preview_interface_prefixes(page_size=100)["candidates"][0]
    assert candidate["status"] == "to_create"

    request = {
        "candidate_ids": [candidate["candidate_id"]],
        "idempotency_key": "interface-prefix-generation-replay",
        "idempotency_tenant_id": "tenant-default",
    }
    first = generate_interface_prefixes(**request)
    replay = generate_interface_prefixes(**request)

    assert replay == first
    assert first["created_prefixes"] == 1
    assert first["created_addresses"] == 1
    with get_db_connection() as conn:
        prefix_count = conn.execute(
            "SELECT COUNT(*) FROM prefixes WHERE prefix = '10.88.70.0/24'"
        ).fetchone()[0]
        address_count = conn.execute(
            "SELECT COUNT(*) FROM ip_addresses WHERE address = '10.88.70.1'"
        ).fetchone()[0]
    assert prefix_count == 1
    assert address_count == 1

def test_interface_generation_preserves_different_configured_gateway(isolated_db):
    _seed_scope()
    space = create_address_space(
        name="Existing gateway scope", kind="global", vrf_id=None,
        security_tenant_id="tenant-default",
    )
    prefix = create_subnet(
        prefix="10.88.80.0/24", address_space_id=space["id"],
        tenant_id="tenant-default", site_id="snapshot-candidate-site",
        gateway="10.88.80.254",
    )
    _publish_snapshot_ip("10.88.80.1")
    candidate = preview_interface_prefixes(page_size=100)["candidates"][0]
    result = generate_interface_prefixes(
        candidate_ids=[candidate["candidate_id"]],
        address_space_overrides={candidate["candidate_id"]: space["id"]},
    )
    assert result["created_addresses"] == 1, result["skipped_addresses"]
    with get_db_connection() as conn:
        stored = conn.execute(
            "SELECT gateway, gateway_device_id FROM prefixes WHERE id=?", (prefix["id"],)
        ).fetchone()
        address = conn.execute(
            "SELECT device_type, purpose FROM ip_addresses WHERE subnet_id=? AND address='10.88.80.1'",
            (prefix["id"],),
        ).fetchone()
    assert stored["gateway"] == "10.88.80.254"
    assert not stored["gateway_device_id"]
    assert address["device_type"] == "interface"
    assert address["purpose"] != "gateway"
