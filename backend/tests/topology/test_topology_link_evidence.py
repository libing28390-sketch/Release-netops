import json
from datetime import datetime, timedelta, timezone
import uuid

from database import get_db_connection
from services.topology_service import (
    TOPOLOGY_LINK_TTL_SECONDS,
    _build_topology_evidence_directions,
    _classify_topology_link_evidence,
    decorate_topology_link_evidence,
    _mark_observation_collection_source,
    _topology_collection_evidence,
)


def _active_lldp_link(**overrides):
    now = datetime.now(timezone.utc)
    return {
        'source_device_id': 'device-a',
        'target_device_id': 'device-b',
        'discovery_source': 'lldp',
        'status': 'up',
        'evidence_count': 1,
        'last_seen': now.isoformat(),
        'metadata_json': json.dumps({'reverse_seen': False, 'protocols': ['lldp']}),
        **overrides,
    }


def _complete_evidence():
    return {'state': 'complete', 'protocol_results': {'snmp': {'status': 'success'}}}


def test_link_evidence_distinguishes_bidirectional_and_neighbor_mismatch():
    both_complete = (_complete_evidence(), _complete_evidence())

    assert _classify_topology_link_evidence(
        _active_lldp_link(metadata_json=json.dumps({'reverse_seen': True, 'protocols': ['lldp']})),
        *both_complete,
    ) == 'bidirectional_confirmed'
    assert _classify_topology_link_evidence(
        _active_lldp_link(),
        *both_complete,
    ) == 'neighbor_mismatch'


def test_failed_peer_collection_keeps_link_as_single_sided_evidence():
    assert _classify_topology_link_evidence(
        _active_lldp_link(metadata_json=json.dumps({'reverse_seen': True, 'protocols': ['lldp']})),
        _complete_evidence(),
        {'state': 'failed'},
    ) == 'single_sided_evidence'


def test_unmanaged_peer_is_single_sided_and_stale_evidence_is_separate():
    now = datetime.now(timezone.utc)
    unmanaged = _active_lldp_link(
        target_device_id='unmanaged::site::10.0.0.2',
        is_unmanaged=True,
        metadata_json='{}',
    )
    assert _classify_topology_link_evidence(unmanaged, _complete_evidence(), _complete_evidence(), now=now) == 'single_sided_evidence'

    stale = _active_lldp_link(
        last_seen=(now - timedelta(seconds=TOPOLOGY_LINK_TTL_SECONDS + 1)).isoformat(),
    )
    assert _classify_topology_link_evidence(stale, _complete_evidence(), _complete_evidence(), now=now) == 'stale'


def test_collection_evidence_requires_a_recent_complete_snapshot():
    now = datetime.now(timezone.utc)
    recent = _topology_collection_evidence({
        'snapshot_state': 'complete',
        'snapshot_complete': True,
        'snapshot_completed_at': now - timedelta(seconds=30),
        'collection_metadata': json.dumps({
            'protocol_results': {
                'snmp': {'status': 'failed', 'detail': 'timeout'},
                'ssh': {'status': 'success', 'detail': ''},
            },
        }),
    }, now)
    expired = _topology_collection_evidence({
        'snapshot_state': 'complete',
        'snapshot_complete': True,
        'snapshot_completed_at': now - timedelta(seconds=TOPOLOGY_LINK_TTL_SECONDS + 1),
        'collection_metadata': '{}',
    }, now)

    assert recent['state'] == 'complete'
    assert recent['protocol_results']['snmp']['status'] == 'failed'
    assert recent['protocol_results']['ssh']['status'] == 'success'
    assert expired['state'] == 'expired'
    assert _topology_collection_evidence({
        'collector_status': 'failed',
        'collection_metadata': json.dumps({'protocol_results': {'snmp': {'status': 'failed'}}}),
    }, now)['state'] == 'failed'


def test_direction_projection_preserves_snmp_cli_provenance():
    observation = {
        'source_device_id': 'device-a',
        'target_device_id': 'device-b',
        'source_port_raw': 'GE1/0/1',
        'target_port_raw': 'GE1/0/2',
        'raw_payload_json': json.dumps({'_collection_sources': ['snmp']}),
    }
    merged = _mark_observation_collection_source(observation, 'ssh')

    directions = _build_topology_evidence_directions([merged, observation])

    assert len(directions) == 1
    assert directions[0]['collection_sources'] == ['snmp', 'ssh']
    assert json.loads(merged['raw_payload_json'])['_collection_sources'] == ['snmp', 'ssh']


def test_link_evidence_decoration_reads_postgresql_snapshot_and_protocol_state(isolated_db):
    device_ids = {name: f'evidence-{name}-{uuid.uuid4().hex}' for name in ('a', 'b', 'c')}
    now = datetime.now(timezone.utc)
    conn = get_db_connection()
    try:
        for name, device_id in device_ids.items():
            conn.execute(
                'INSERT INTO devices (id, hostname, platform, tenant_id) VALUES (?, ?, ?, ?)',
                (device_id, f'evidence-{name}', 'h3c_comware', 'tenant-evidence-test'),
            )
        for name, state, complete, protocol_results in (
            ('a', 'complete', True, {'snmp': {'status': 'success'}}),
            ('b', 'complete', True, {'ssh': {'status': 'success'}}),
            ('c', 'failed', False, {'snmp': {'status': 'failed'}, 'ssh': {'status': 'success'}}),
        ):
            device_id = device_ids[name]
            conn.execute(
                '''INSERT INTO topology_device_lldp_snapshots (
                       device_id, generation, state, snapshot_complete,
                       observation_count, completed_at, updated_at
                   ) VALUES (?, 1, ?, ?, 0, ?, ?)''',
                (device_id, state, complete, now, now),
            )
            conn.execute(
                '''INSERT INTO device_collection_status (
                       device_id, collector, status, metadata_json, updated_at
                   ) VALUES (?, 'topology_lldp', ?, ?, ?)''',
                (
                    device_id,
                    'failed' if state == 'failed' else 'success',
                    json.dumps({'protocol_results': protocol_results}),
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    links = decorate_topology_link_evidence([
        {
            **_active_lldp_link(source_device_id=device_ids['a'], target_device_id=device_ids['b']),
            'evidence_directions': [{
                'source_device_id': device_ids['a'],
                'target_device_id': device_ids['b'],
                'source_port': 'GE1/0/1',
                'target_port': 'GE1/0/2',
                'collection_sources': ['snmp'],
            }],
        },
        _active_lldp_link(source_device_id=device_ids['a'], target_device_id=device_ids['c']),
        _active_lldp_link(
            source_device_id=device_ids['a'],
            target_device_id='unmanaged::site::10.0.0.4',
            is_unmanaged=True,
        ),
    ])

    assert [link['evidence_status'] for link in links] == [
        'neighbor_mismatch', 'single_sided_evidence', 'single_sided_evidence',
    ]
    assert links[0]['evidence_directions'][0]['collection_sources'] == ['snmp']
    assert links[1]['target_collection_evidence']['state'] == 'failed'
    assert links[1]['target_collection_evidence']['protocol_results']['ssh']['status'] == 'success'
