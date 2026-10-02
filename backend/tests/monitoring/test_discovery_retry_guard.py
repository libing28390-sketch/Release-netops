from __future__ import annotations

import asyncio

import pytest

from services import background_monitor_service as monitor


def _device(**overrides):
    device = {
        "id": "device-1",
        "vendor": "Cisco",
        "platform": "cisco_ios",
        "model": "C9300",
        "version": "17.9",
        "role": "core",
        "metric_profile_id": "profile-1",
    }
    device.update(overrides)
    return device


def _signature(device=None, **overrides):
    device = dict(device or _device())
    values = {
        "snmp_ip": "192.0.2.10",
        "snmp_port": 161,
        "snmp_version": "2c",
        "community": "test-community",
        "profile": {"interface": 1, "info": 10, "protocol": 2},
    }
    values.update(overrides)
    return monitor._automatic_discovery_signature(device, **values)


def _reset_guard(monkeypatch, *, now: float = 0.0):
    clock = [now]
    monkeypatch.setattr(monitor, "_automatic_discovery_retry_state", {})
    monkeypatch.setattr(monitor, "_automatic_discovery_now", lambda: clock[0])
    return clock


def _run(coroutine):
    return asyncio.run(coroutine)


def test_failed_discovery_uses_exponential_backoff(monkeypatch):
    clock = _reset_guard(monkeypatch)
    signature = _signature()
    attempts = []

    async def fail():
        attempts.append(clock[0])
        raise RuntimeError("probe failed")

    with pytest.raises(RuntimeError):
        _run(monitor._run_automatic_oid_discovery(signature, fail))
    assert attempts == [0.0]

    assert _run(monitor._run_automatic_oid_discovery(signature, fail)) is monitor._AUTOMATIC_DISCOVERY_SKIPPED
    clock[0] = 119.9
    assert _run(monitor._run_automatic_oid_discovery(signature, fail)) is monitor._AUTOMATIC_DISCOVERY_SKIPPED
    clock[0] = 120.0
    with pytest.raises(RuntimeError):
        _run(monitor._run_automatic_oid_discovery(signature, fail))
    assert attempts == [0.0, 120.0]
    state = monitor._automatic_discovery_retry_state[signature]
    assert state["next_retry_at"] == 360.0


def test_empty_hardware_categories_waits_900_seconds(monkeypatch):
    clock = _reset_guard(monkeypatch)
    signature = _signature()
    calls = []

    async def empty():
        calls.append(clock[0])
        return {"status": "partial", "hardware_category_results": []}

    assert _run(monitor._run_automatic_oid_discovery(signature, empty))["status"] == "partial"
    assert _run(monitor._run_automatic_oid_discovery(signature, empty)) is monitor._AUTOMATIC_DISCOVERY_SKIPPED
    clock[0] = 899.9
    assert _run(monitor._run_automatic_oid_discovery(signature, empty)) is monitor._AUTOMATIC_DISCOVERY_SKIPPED
    clock[0] = 900.0
    _run(monitor._run_automatic_oid_discovery(signature, empty))
    assert calls == [0.0, 900.0]


def test_success_releases_retry_bucket(monkeypatch):
    _reset_guard(monkeypatch)
    signature = _signature()
    calls = []

    async def success():
        calls.append(True)
        return {"status": "matched", "hardware_category_results": [{"component_class": "cpu"}]}

    _run(monitor._run_automatic_oid_discovery(signature, success))
    _run(monitor._run_automatic_oid_discovery(signature, success))
    assert len(calls) == 2
    assert signature not in monitor._automatic_discovery_retry_state


def test_signature_changes_bypass_old_backoff(monkeypatch):
    _reset_guard(monkeypatch)
    first = _signature()
    changed_address = _signature(snmp_ip="192.0.2.11")
    changed_community = _signature(community="other-community")
    changed_profile = _signature(profile={"interface": 10, "info": 10, "protocol": 10})
    assert len({first, changed_address, changed_community, changed_profile}) == 4

    async def fail():
        raise RuntimeError("probe failed")

    with pytest.raises(RuntimeError):
        _run(monitor._run_automatic_oid_discovery(first, fail))
    with pytest.raises(RuntimeError):
        _run(monitor._run_automatic_oid_discovery(changed_address, fail))
    assert monitor._automatic_discovery_retry_state[changed_address]["failure_count"] == 1


def test_same_signature_in_flight_is_not_duplicated(monkeypatch):
    _reset_guard(monkeypatch)
    signature = _signature()
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def slow_success():
        calls.append(True)
        started.set()
        await release.wait()
        return {"hardware_category_results": [{"component_class": "cpu"}]}

    async def run():
        first = asyncio.create_task(monitor._run_automatic_oid_discovery(signature, slow_success))
        await started.wait()
        duplicate = await monitor._run_automatic_oid_discovery(signature, slow_success)
        release.set()
        result = await first
        return result, duplicate

    result, duplicate = _run(run())
    assert result["hardware_category_results"]
    assert duplicate is monitor._AUTOMATIC_DISCOVERY_SKIPPED
    assert len(calls) == 1


def test_cancelled_discovery_releases_in_flight_state(monkeypatch):
    _reset_guard(monkeypatch)
    signature = _signature()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked():
        started.set()
        await release.wait()
        return {"hardware_category_results": []}

    async def run():
        task = asyncio.create_task(monitor._run_automatic_oid_discovery(signature, blocked))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return monitor._begin_automatic_discovery(signature)

    token = _run(run())
    assert token == signature
    monitor._release_automatic_discovery_cancelled(signature)


def test_retry_state_has_bounded_capacity(monkeypatch):
    _reset_guard(monkeypatch)
    monkeypatch.setattr(monitor, "_AUTOMATIC_DISCOVERY_MAX_STATE_ENTRIES", 2)
    first = _signature()
    second = _signature(snmp_ip="192.0.2.11")
    third = _signature(snmp_ip="192.0.2.12")

    assert monitor._begin_automatic_discovery(first) == first
    assert monitor._begin_automatic_discovery(second) == second
    assert monitor._begin_automatic_discovery(third) is None
    monitor._record_automatic_discovery_success(first)
    assert monitor._begin_automatic_discovery(third) == third
    assert len(monitor._automatic_discovery_retry_state) <= 2
