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


def test_scheduled_nsot_stores_partial_when_topology_summary_is_incomplete(monkeypatch):
    job = {
        'id': 'nsot-job',
        'name': 'NSOT scheduled',
        'enabled': 1,
        'action_type': 'nsot',
    }

    class Connection:
        def __init__(self) -> None:
            self.update_parameters = None

        def execute(self, sql, parameters=()):
            if sql.startswith('SELECT * FROM scheduled_jobs'):
                return self
            if sql.startswith('UPDATE scheduled_jobs'):
                self.update_parameters = parameters
                return self
            raise AssertionError(f'unexpected SQL: {sql}')

        def fetchone(self):
            return job

        def commit(self):
            return None

        def close(self):
            return None

    connection = Connection()
    monkeypatch.setattr(scheduler_service, 'get_db_connection', lambda: connection)
    monkeypatch.setattr(
        'services.ip_locator_service.run_unified_nsot_sync',
        lambda: {'topology': {'status': 'partial', 'redis_publish_unconfirmed': 1}},
    )

    asyncio.run(scheduler_service.run_scheduled_automation_job('nsot-job'))

    assert connection.update_parameters[1] == 'partial'
