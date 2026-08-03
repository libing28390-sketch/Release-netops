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

    async def fake_discover(device_id: str, run_id: str, *, rebuild_links: bool) -> dict:
        nonlocal active, peak_active
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
    monkeypatch.setattr(topology_service, '_get_discovery_run_settings', lambda run_id: (30, 2))
    monkeypatch.setattr(topology_service, '_renew_discovery_lease', lambda run_id, worker_id: True)
    monkeypatch.setattr(topology_service, '_is_run_cancel_requested', lambda run_id: False)
    monkeypatch.setattr(topology_service, '_update_run_device', fake_update_run_device)
    monkeypatch.setattr(topology_service, '_update_run', fake_update_run)
    monkeypatch.setattr(topology_service, 'discover_device_neighbors', fake_discover)
    monkeypatch.setattr(topology_service, 'rebuild_links_from_observations', lambda: 0)

    await execute_discovery_run('run-test', ['dev-a', 'dev-b', 'dev-c', 'dev-d'])

    assert peak_active == 2
    assert {item for item in completed_devices if not item.startswith('status:')} == {
        'dev-a', 'dev-b', 'dev-c', 'dev-d',
    }
    assert run_updates[-1]['status'] == 'completed'
    assert run_updates[-1]['success_devices'] == 4
