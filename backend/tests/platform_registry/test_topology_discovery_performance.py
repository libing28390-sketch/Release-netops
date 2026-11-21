from __future__ import annotations

import asyncio

import pytest

import services.topology_service as topology_service
from services.topology_service import execute_discovery_run, _should_retry_discovery


def test_topology_retry_policy_only_retries_transient_transport_errors() -> None:
    assert _should_retry_discovery('ssh_unreachable', 1, 2) is True
    assert _should_retry_discovery('ssh_authentication_failed', 1, 2) is False
    assert _should_retry_discovery('neighbor_parse_failed', 1, 2) is False
    assert _should_retry_discovery('ssh_unreachable', 2, 2) is False


@pytest.mark.anyio
async def test_execute_discovery_run_uses_bounded_device_concurrency(monkeypatch) -> None:
    active = 0
    peak_active = 0
    completed_devices: list[str] = []
    run_updates: list[dict] = []
    run_events: list[str] = []

    async def fake_discover(device_id: str, run_id: str, *, rebuild_links: bool) -> dict:
        nonlocal active, peak_active
        assert run_events and run_events[0] == 'history-cleared'
        run_events.append(f'collect:{device_id}')
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        completed_devices.append(device_id)
        return {
            'device_id': device_id,
            'discovery_method': 'test',
            'observations_count': 1,
            'matched_links_count': 1,
        }

    def fake_update_run_device(run_id: str, device_id: str, **fields) -> None:
        if fields.get('status') == 'success':
            completed_devices.append(f'status:{device_id}')

    def fake_update_run(run_id: str, **fields) -> None:
        run_updates.append(fields)

    monkeypatch.setattr(topology_service, 'DISCOVERY_DEVICE_CONCURRENCY', 2)
    monkeypatch.setattr(topology_service, '_claim_discovery_run', lambda run_id, worker_id: True)
    monkeypatch.setattr(
        topology_service,
        '_clear_lldp_observation_history_for_run',
        lambda device_ids: run_events.append('history-cleared'),
    )
    monkeypatch.setattr(topology_service, '_get_discovery_run_settings', lambda run_id: (30, 2))
    monkeypatch.setattr(topology_service, '_renew_discovery_lease', lambda run_id, worker_id: True)
    monkeypatch.setattr(topology_service, '_is_run_cancel_requested', lambda run_id: False)
    monkeypatch.setattr(topology_service, '_update_run_device', fake_update_run_device)
    monkeypatch.setattr(topology_service, '_update_run', fake_update_run)
    monkeypatch.setattr(topology_service, 'discover_device_neighbors', fake_discover)
    def fake_refresh_identities(run_id):
        assert len([item for item in completed_devices if not item.startswith('status:')]) == 4
        run_events.append('identities-refreshed')
        return {'matched': 4, 'hostname_mismatch': 0, 'ambiguous': 0, 'unmatched': 0}

    monkeypatch.setattr(topology_service, '_refresh_run_observation_identities', fake_refresh_identities)
    monkeypatch.setattr(topology_service, 'rebuild_links_from_observations', lambda: 0)

    await execute_discovery_run('run-test', ['dev-a', 'dev-b', 'dev-c', 'dev-d'])

    assert peak_active == 2
    assert {item for item in completed_devices if not item.startswith('status:')} == {
        'dev-a', 'dev-b', 'dev-c', 'dev-d',
    }
    assert run_updates[-1]['status'] == 'completed'
    assert run_updates[-1]['success_devices'] == 4
    assert run_events[0] == 'history-cleared'
    assert run_events[-1] == 'identities-refreshed'


def _stub_discovery_run(monkeypatch, *, cancelled=None):
    updates = []
    device_updates = []
    monkeypatch.setattr(topology_service, 'DISCOVERY_DEVICE_CONCURRENCY', 2)
    monkeypatch.setattr(topology_service, '_claim_discovery_run', lambda *_: True)
    monkeypatch.setattr(topology_service, '_clear_lldp_observation_history_for_run', lambda *_: None)
    monkeypatch.setattr(topology_service, '_get_discovery_run_settings', lambda *_: (30, 1))
    monkeypatch.setattr(topology_service, '_renew_discovery_lease', lambda *_: True)
    monkeypatch.setattr(topology_service, '_is_run_cancel_requested', lambda *_: bool(cancelled and cancelled[0]))
    monkeypatch.setattr(topology_service, '_update_run', lambda _run_id, **fields: updates.append(fields))
    monkeypatch.setattr(topology_service, '_update_run_device', lambda _run_id, device_id, **fields: device_updates.append((device_id, fields)))
    monkeypatch.setattr(topology_service, '_refresh_run_observation_identities', lambda *_: {})
    monkeypatch.setattr(topology_service, 'rebuild_links_from_observations', lambda: 0)
    return updates, device_updates


@pytest.mark.anyio
async def test_fast_lane_starts_next_device_before_slow_device_finishes(monkeypatch):
    updates, _ = _stub_discovery_run(monkeypatch)
    next_started = asyncio.Event()
    started = []

    async def collect(_run_id, device_id, *_):
        started.append(device_id)
        if device_id == 'slow':
            # A fixed two-device batch deadlocks here: the third device must
            # start before this slow device is allowed to finish.
            await next_started.wait()
        elif device_id == 'next':
            next_started.set()
        return {'success': True, 'observations_count': 1}

    monkeypatch.setattr(topology_service, '_execute_discovery_device', collect)
    await asyncio.wait_for(execute_discovery_run('run-test', ['slow', 'fast', 'next']), 2)
    assert started == ['slow', 'fast', 'next']
    assert updates[-1]['success_devices'] == 3
    assert updates[-1]['status'] == 'completed'


@pytest.mark.anyio
async def test_cancel_stops_pending_devices_while_inflight_devices_finish(monkeypatch):
    cancelled = [False]
    updates, device_updates = _stub_discovery_run(monkeypatch, cancelled=cancelled)
    release = asyncio.Event()
    started = []

    async def collect(_run_id, device_id, *_):
        started.append(device_id)
        if device_id == 'a':
            await release.wait()
        else:
            cancelled[0] = True
            release.set()
        return {'success': True, 'observations_count': 1}

    monkeypatch.setattr(topology_service, '_execute_discovery_device', collect)
    await execute_discovery_run('run-test', ['a', 'b', 'c', 'd'])
    assert started == ['a', 'b']
    assert {device_id for device_id, fields in device_updates if fields['status'] == 'cancelled'} == {'c', 'd'}
    assert updates[-1]['status'] == 'cancelled'
    assert updates[-1]['success_devices'] == 2


@pytest.mark.anyio
async def test_lost_lease_does_not_start_queued_devices(monkeypatch):
    updates, _ = _stub_discovery_run(monkeypatch)
    both_started = asyncio.Event()
    release = asyncio.Event()
    started = []

    async def heartbeat(_run, _worker, stop, lost):
        await both_started.wait()
        lost.set()
        release.set()

    async def collect(_run_id, device_id, *_):
        started.append(device_id)
        if len(started) == 2:
            both_started.set()
        await release.wait()
        return {'success': True, 'observations_count': 1}

    monkeypatch.setattr(topology_service, '_discovery_lease_heartbeat', heartbeat)
    monkeypatch.setattr(topology_service, '_execute_discovery_device', collect)
    await execute_discovery_run('run-test', ['a', 'b', 'c', 'd'])
    assert started == ['a', 'b']
    assert updates[-1]['status'] == 'failed'
    assert updates[-1]['last_error_code'] == 'discovery_lease_lost'


@pytest.mark.anyio
async def test_worker_failure_is_counted_and_lane_continues(monkeypatch):
    updates, device_updates = _stub_discovery_run(monkeypatch)

    async def collect(_run_id, device_id, *_):
        if device_id == 'bad':
            raise RuntimeError('fixture-worker-failed')
        return {'success': True, 'observations_count': 1}

    monkeypatch.setattr(topology_service, '_execute_discovery_device', collect)
    await execute_discovery_run('run-test', ['bad', 'good-a', 'good-b'])
    assert updates[-1]['status'] == 'partial'
    assert updates[-1]['success_devices'] == 2
    assert updates[-1]['failed_devices'] == 1
    assert [device_id for device_id, fields in device_updates if fields['status'] == 'failed'] == ['bad']
