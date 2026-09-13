from __future__ import annotations

import asyncio

from services import scheduler_service


def _devices(*device_ids: str) -> list[dict[str, str]]:
    return [{'id': device_id} for device_id in device_ids]


def test_topology_batch_counts_empty_complete_snapshot_as_success():
    devices = _devices('neighbors', 'empty')

    async def discover(device_id: str) -> dict:
        if device_id == 'empty':
            return {
                'collection_status': 'no_neighbors',
                'redis_publish_confirmed': True,
                'observations_count': 0,
            }
        return {
            'collection_status': 'success',
            'redis_publish_confirmed': True,
            'observations_count': 3,
        }

    summary = asyncio.run(
        scheduler_service._run_topology_discovery_batch(
            devices,
            [],
            discover,
            lambda: None,
        )
    )

    assert summary['status'] == 'complete'
    assert summary['devices_total'] == 2
    assert summary['devices_complete'] == 2
    assert summary['devices_failed'] == 0
    assert [item['status'] for item in summary['device_results']] == ['success', 'no_neighbors']


def test_topology_batch_aggregates_device_failure_and_exception_without_details():
    devices = _devices('reported-failure', 'raised-exception')

    async def discover(device_id: str) -> dict:
        if device_id == 'reported-failure':
            return {'status': 'failed', 'error_code': 'ssh_unreachable'}
        raise RuntimeError('password=must-not-appear')

    summary = asyncio.run(
        scheduler_service._run_topology_discovery_batch(
            devices,
            [],
            discover,
            lambda: None,
        )
    )

    assert summary['status'] == 'partial'
    assert summary['devices_failed'] == 2
    assert [item['error_code'] for item in summary['device_results']] == [
        'ssh_unreachable',
        'topology_discovery_failed',
    ]
    assert 'must-not-appear' not in repr(summary)


def test_topology_batch_marks_unconfirmed_redis_publish_partial():
    async def discover(_device_id: str) -> dict:
        return {
            'collection_status': 'no_neighbors',
            'redis_publish_confirmed': False,
            'observations_count': 0,
        }

    summary = asyncio.run(
        scheduler_service._run_topology_discovery_batch(
            _devices('redis-unconfirmed'),
            [],
            discover,
            lambda: None,
        )
    )

    assert summary['status'] == 'partial'
    assert summary['devices_complete'] == 0
    assert summary['devices_partial'] == 1
    assert summary['redis_publish_unconfirmed'] == 1
    assert summary['device_results'][0] == {
        'device_id': 'redis-unconfirmed',
        'status': 'partial',
        'collection_status': 'no_neighbors',
        'redis_publish_confirmed': False,
        'error_code': 'redis_publish_unconfirmed',
    }


def test_scheduled_nsot_stores_partial_when_topology_summary_is_incomplete(isolated_db, monkeypatch):
    conn = isolated_db['module'].get_db_connection()
    now = '2026-09-13T00:00:00+00:00'
    try:
        for device_id, site, status in (
            ('nsot-wh-1', 'WH-DC-02', 'online'),
            ('nsot-hq-1', 'HQ', 'online'),
            ('nsot-wh-offline', 'WH-DC-02', 'offline'),
        ):
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, status, role, site) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (device_id, device_id, '192.0.2.10', 'h3c_comware', status, 'switch', site),
            )
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(id, name, job_type, action_type, device_scope, device_filter, enabled, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ('nsot-job', 'NSOT scheduled', 'cron', 'nsot', 'site', 'WH-DC-02', 1, 'approved', now, now),
        )
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(id, name, job_type, action_type, device_scope, device_filter, enabled, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ('nsot-empty-job', 'NSOT empty scope', 'cron', 'nsot', 'site', 'NO-SITE', 1, 'approved', now, now),
        )
        conn.commit()
    finally:
        conn.close()

    observed_scope: list[set[str] | None] = []

    def fake_run_unified_nsot_sync(*, device_ids=None):
        observed_scope.append(device_ids)
        return {'topology': {'status': 'partial', 'redis_publish_unconfirmed': 1}}

    monkeypatch.setattr(
        'services.ip_locator_service.run_unified_nsot_sync',
        fake_run_unified_nsot_sync,
    )

    asyncio.run(scheduler_service.run_scheduled_automation_job('nsot-job'))
    asyncio.run(scheduler_service.run_scheduled_automation_job('nsot-empty-job'))

    assert observed_scope == [{'nsot-wh-1'}]
    conn = isolated_db['module'].get_db_connection()
    try:
        row = conn.execute(
            "SELECT last_run_status, run_count FROM scheduled_jobs WHERE id = ?",
            ('nsot-job',),
        ).fetchone()
        empty_row = conn.execute(
            "SELECT last_run_status, run_count FROM scheduled_jobs WHERE id = ?",
            ('nsot-empty-job',),
        ).fetchone()
    finally:
        conn.close()
    assert row['last_run_status'] == 'partial'
    assert row['run_count'] == 1
    assert empty_row['last_run_status'] == 'skipped'
    assert empty_row['run_count'] == 1
