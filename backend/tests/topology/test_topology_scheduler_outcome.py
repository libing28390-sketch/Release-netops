from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

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


def test_retired_nsot_skips_topology_collection_for_all_saved_scopes(isolated_db, make_user, monkeypatch):
    from services.scheduled_job_authorization import (
        execution_snapshot,
        manifest_hash,
        normalize_authorization_grant,
    )

    conn = isolated_db['module'].get_db_connection()
    now = '2026-09-13T00:00:00+00:00'
    owner = make_user("topology-nsot-owner", role="Administrator", tenant_id="tenant-topology")
    try:
        for device_id, site, status in (
            ('nsot-wh-1', 'WH-DC-02', 'online'),
            ('nsot-hq-1', 'HQ', 'online'),
            ('nsot-wh-offline', 'WH-DC-02', 'offline'),
        ):
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, status, role, site, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (device_id, device_id, '192.0.2.10', 'h3c_comware', status, 'switch', site, 'tenant-topology'),
            )
        for job_id, scope_filter in (('nsot-job', 'WH-DC-02'), ('nsot-empty-job', 'NO-SITE')):
            grant_id = f'{job_id}-grant'
            job = {
                'id': job_id,
                'name': 'NSOT scheduled',
                'job_type': 'cron',
                'action_type': 'nsot',
                'cron_expr': '0 2 * * *',
                'scheduled_at': '',
                'device_scope': 'site',
                'device_filter': scope_filter,
                'commands': '',
                'script_id': '',
                'is_config': 0,
                'config_reason': '',
                'use_admin_creds': 0,
                'enabled': 1,
                'created_by_id': owner['user_id'],
                'tenant_id': 'tenant-topology',
                'authorization_mode': 'snapshot',
                'current_authorization_grant_id': grant_id,
            }
            grant = normalize_authorization_grant({
                'valid_until': (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace('+00:00', 'Z'),
                'max_runs': 5,
                'max_targets': 10,
                'scope': {'type': 'site', 'filter': scope_filter},
                'ticket_source_type': 'incident',
                'ticket_id': f'{job_id}-incident',
            })
            job['authorization_grant'] = grant
            job_hash = manifest_hash(execution_snapshot(conn, job))
            conn.execute(
                "INSERT INTO scheduled_jobs "
                "(id, name, job_type, action_type, cron_expr, scheduled_at, device_scope, device_filter, "
                "commands, script_id, is_config, config_reason, use_admin_creds, enabled, status, "
                "created_by, created_by_id, tenant_id, authorization_mode, authorization_manifest_hash, "
                "current_authorization_grant_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job['id'], job['name'], job['job_type'], job['action_type'], job['cron_expr'],
                    job['scheduled_at'], job['device_scope'], job['device_filter'], job['commands'],
                    job['script_id'], job['is_config'], job['config_reason'], job['use_admin_creds'],
                    job['enabled'], 'approved', owner['username'], job['created_by_id'],
                    job['tenant_id'], 'snapshot', job_hash, grant_id, now, now,
                ),
            )
            conn.execute(
                """INSERT INTO scheduled_job_authorization_grants (
                       grant_id, job_id, version, status, owner_id, tenant_id,
                       template_version, manifest_hash, grant_json, valid_until,
                       max_runs, used_runs, max_targets, ticket_source_type,
                       ticket_id, ticket_number, ticket_title, change_order_id,
                       change_order_number, created_by_id, approved_by_id
                   ) VALUES (?, ?, 1, 'active', ?, ?, 'nsot-fixture-v1', ?, ?::jsonb,
                             ?::timestamptz, ?, 0, ?, 'incident', ?, 'INC-NSOT-1',
                             'NSOT scope fixture', '', '', ?, ?)""",
                (
                    grant_id, job['id'], owner['user_id'], job['tenant_id'], job_hash,
                    json.dumps(grant, ensure_ascii=False), grant['valid_until'],
                    grant['max_runs'], grant['max_targets'], grant['ticket_id'],
                    owner['user_id'], owner['user_id'],
                ),
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

    assert observed_scope == []
    conn = isolated_db['module'].get_db_connection()
    try:
        row = conn.execute(
            "SELECT last_run_status, run_count, enabled, status FROM scheduled_jobs WHERE id = ?",
            ('nsot-job',),
        ).fetchone()
        empty_row = conn.execute(
            "SELECT last_run_status, run_count, enabled, status FROM scheduled_jobs WHERE id = ?",
            ('nsot-empty-job',),
        ).fetchone()
    finally:
        conn.close()
    assert row['last_run_status'] == 'skipped'
    assert row['run_count'] == 1
    assert empty_row['last_run_status'] == 'skipped'
    assert empty_row['run_count'] == 1

    assert row['enabled'] == 0
    assert row['status'] == 'disabled'
    assert empty_row['enabled'] == 0
    assert empty_row['status'] == 'disabled'
