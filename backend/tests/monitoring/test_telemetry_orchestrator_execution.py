import asyncio
import threading
from contextlib import asynccontextmanager

import pytest

from engine.orchestrator import TelemetryOrchestrator
from engine import pool as engine_pool
from services import background_monitor_service


async def _wait_for_thread_event(event: threading.Event, *, timeout: float, sleep) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not event.is_set():
        if loop.time() >= deadline:
            pytest.fail("worker thread did not reach the expected gate")
        await sleep(0.005)


async def _assert_loop_can_tick(*, main_thread_id: int, gate: threading.Event, sleep) -> None:
    tick_thread_ids: list[int] = []

    async def ticker() -> None:
        tick_thread_ids.append(threading.get_ident())
        await sleep(0)

    await asyncio.wait_for(ticker(), timeout=0.5)
    assert not gate.is_set(), "the blocking worker gate must still be closed"
    assert tick_thread_ids == [main_thread_id]


def test_fast_loop_collection_status_write_runs_off_event_loop(monkeypatch):
    loop_thread_id = threading.get_ident()
    persistence_thread_ids: list[int] = []

    class Limiter:
        @asynccontextmanager
        async def async_probe(self):
            yield

    async def reachable(_ip: str, _port: int):
        return True, "tcp"

    monkeypatch.setattr(background_monitor_service, "get_network_access_limiter", lambda: Limiter())
    monkeypatch.setattr(background_monitor_service, "_probe_device_reachability", reachable)
    monkeypatch.setattr(
        background_monitor_service,
        "record_collection_result",
        lambda *_args, **_kwargs: persistence_thread_ids.append(threading.get_ident()),
    )

    asyncio.run(background_monitor_service.process_device_fast({
        "id": "fast-loop-thread-test",
        "ip_address": "192.0.2.1",
        "status": "online",
    }))

    assert persistence_thread_ids
    assert persistence_thread_ids[0] != loop_thread_id


def test_offline_reachability_does_not_replace_native_hardware_values_with_zero(monkeypatch):
    db_updates: list[tuple[str, tuple]] = []

    class Limiter:
        @asynccontextmanager
        async def async_probe(self):
            yield

    async def unreachable(_ip: str, _port: int):
        return False, "test"

    monkeypatch.setattr(background_monitor_service, "get_network_access_limiter", lambda: Limiter())
    monkeypatch.setattr(background_monitor_service, "_probe_device_reachability", unreachable)
    monkeypatch.setattr(background_monitor_service, "_db_quick", lambda sql, params=(), **_kwargs: db_updates.append((sql, params)))
    monkeypatch.setattr(background_monitor_service, "_sync_device_status_tag", lambda *_args: None)
    monkeypatch.setattr(background_monitor_service, "_set_protocol_alerts_for_device_offline", lambda *_args: None)
    monkeypatch.setattr(background_monitor_service, "_set_device_reachability_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(background_monitor_service, "_schedule_monitoring_target_sync", lambda: None)
    monkeypatch.setattr(background_monitor_service, "record_collection_result", lambda *_args, **_kwargs: None)

    asyncio.run(background_monitor_service.process_device_fast({
        "id": "offline-native-values",
        "ip_address": "192.0.2.7",
        "status": "online",
    }))

    offline_update = next(sql for sql, _params in db_updates if "UPDATE devices" in sql)
    assert "cpu_usage" not in offline_update
    assert "memory_usage" not in offline_update


def test_a_loop_offloads_device_snapshot_and_keeps_loop_responsive(monkeypatch):
    loop_thread_id = threading.get_ident()
    entered = threading.Event()
    release = threading.Event()
    worker_finished = threading.Event()
    worker_thread_ids: list[int] = []
    query_calls: list[tuple[str, dict]] = []

    def slow_db(sql, **kwargs):
        worker_thread_ids.append(threading.get_ident())
        query_calls.append((sql, kwargs))
        entered.set()
        try:
            release.wait(timeout=2)
            return []
        finally:
            worker_finished.set()

    monkeypatch.setattr(background_monitor_service, "_db_quick", slow_db)

    async def scenario():
        sleep = asyncio.sleep
        task = asyncio.create_task(TelemetryOrchestrator().a_loop())
        try:
            await _wait_for_thread_event(entered, timeout=1, sleep=sleep)
            await _assert_loop_can_tick(
                main_thread_id=loop_thread_id,
                gate=release,
                sleep=sleep,
            )
            assert query_calls == [(
                "SELECT * FROM devices WHERE ip_address IS NOT NULL AND ip_address != ''",
                {"fetchall": True},
            )]
            assert worker_thread_ids[0] != loop_thread_id
        finally:
            release.set()
            if entered.is_set():
                await _wait_for_thread_event(worker_finished, timeout=1, sleep=sleep)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_b_loop_offloads_snapshot_and_maintenance_after_twelve_successful_cycles(monkeypatch):
    loop_thread_id = threading.get_ident()
    db_entered = threading.Event()
    db_release = threading.Event()
    first_db_finished = threading.Event()
    maintenance_entered = threading.Event()
    maintenance_release = threading.Event()
    maintenance_finished = threading.Event()
    successful_loop_reached_12 = threading.Event()
    db_calls: list[tuple[str, dict, int]] = []
    slow_cycle_ticks: list[int] = []
    sync_lldp_thread_ids: list[int] = []
    cleanup_thread_ids: list[int] = []
    maintenance_calls: list[tuple[int, int]] = []
    maintenance_thread_ids: list[int] = []
    successful_sync_count = 0

    def slow_db(sql, **kwargs):
        call_index = len(db_calls)
        db_calls.append((sql, kwargs, threading.get_ident()))
        if call_index == 0:
            db_entered.set()
            try:
                db_release.wait(timeout=2)
            finally:
                first_db_finished.set()
        return [{"id": "device-1"}]

    async def slow_device(_device, *, cycle_tick):
        slow_cycle_ticks.append(cycle_tick)
        if cycle_tick == 0:
            raise RuntimeError("controlled failed collection cycle")

    def slow_maintenance():
        maintenance_thread_ids.append(threading.get_ident())
        maintenance_calls.append((successful_sync_count, len(slow_cycle_ticks)))
        maintenance_entered.set()
        try:
            maintenance_release.wait(timeout=2)
        finally:
            maintenance_finished.set()

    def sync_lldp():
        nonlocal successful_sync_count
        sync_lldp_thread_ids.append(threading.get_ident())
        successful_sync_count += 1
        if successful_sync_count >= 12:
            successful_loop_reached_12.set()

    async def scenario():
        nonlocal successful_sync_count
        real_sleep = asyncio.sleep

        async def fast_loop_sleep(_seconds):
            await real_sleep(0.01)

        monkeypatch.setattr(asyncio, "sleep", fast_loop_sleep)
        monkeypatch.setattr(background_monitor_service, "_db_quick", slow_db)
        monkeypatch.setattr(background_monitor_service, "_run_telemetry_maintenance", slow_maintenance)
        monkeypatch.setattr(background_monitor_service, "process_device_slow", slow_device)
        monkeypatch.setattr(background_monitor_service, "sync_lldp_neighbor_alerts", sync_lldp)
        monkeypatch.setattr(
            engine_pool.ConnectionPool,
            "cleanup",
            lambda _self: cleanup_thread_ids.append(threading.get_ident()),
        )

        task = asyncio.create_task(TelemetryOrchestrator().b_loop())
        try:
            await _wait_for_thread_event(db_entered, timeout=1, sleep=real_sleep)
            await _assert_loop_can_tick(
                main_thread_id=loop_thread_id,
                gate=db_release,
                sleep=real_sleep,
            )
            assert db_calls[0][0:2] == (
                "SELECT * FROM devices WHERE status = 'online'",
                {"fetchall": True},
            )
            assert db_calls[0][2] != loop_thread_id
            db_release.set()

            await _wait_for_thread_event(maintenance_entered, timeout=2, sleep=real_sleep)
            assert maintenance_calls == [(11, 13)]
            assert len(db_calls) == 13
            assert [tick for tick in slow_cycle_ticks] == list(range(13))
            assert maintenance_thread_ids[0] != loop_thread_id
            assert not cleanup_thread_ids
            assert len(sync_lldp_thread_ids) == 11
            assert all(thread_id == loop_thread_id for thread_id in sync_lldp_thread_ids)
            assert all(call[2] != loop_thread_id for call in db_calls)
            assert successful_sync_count == 11

            await _assert_loop_can_tick(
                main_thread_id=loop_thread_id,
                gate=maintenance_release,
                sleep=real_sleep,
            )
            assert successful_sync_count == 11
            maintenance_release.set()
            await _wait_for_thread_event(
                successful_loop_reached_12,
                timeout=1,
                sleep=real_sleep,
            )
            assert len(maintenance_calls) == 1
            assert cleanup_thread_ids == [loop_thread_id]
            assert len(sync_lldp_thread_ids) == 12
            assert all(thread_id == loop_thread_id for thread_id in sync_lldp_thread_ids)
        finally:
            db_release.set()
            maintenance_release.set()
            if db_entered.is_set():
                await _wait_for_thread_event(first_db_finished, timeout=1, sleep=real_sleep)
            if maintenance_entered.is_set():
                await _wait_for_thread_event(maintenance_finished, timeout=1, sleep=real_sleep)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_native_hardware_loop_syncs_only_enabled_bindings_and_is_cancellable(monkeypatch):
    query_calls: list[tuple[str, dict]] = []
    synced_devices: list[str] = []

    def fetch_bindings(sql, **kwargs):
        query_calls.append((sql, kwargs))
        return [{"device_id": "device-1"}, {"device_id": "device-2"}]

    async def sync_device(device_id: str):
        synced_devices.append(device_id)
        return {"status": "synced"}

    async def stop_after_one_cycle(_seconds: float):
        raise asyncio.CancelledError

    monkeypatch.setattr(background_monitor_service, "_db_quick", fetch_bindings)
    monkeypatch.setattr(
        "services.librenms_native_sync_service.sync_bound_device_hardware",
        sync_device,
    )
    monkeypatch.setattr(asyncio, "sleep", stop_after_one_cycle)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(TelemetryOrchestrator().native_hardware_loop())

    assert len(query_calls) == 1
    query, kwargs = query_calls[0]
    assert "FROM librenms_device_bindings" in query
    assert "b.desired_state = 'enabled'" in query
    assert "i.enabled = TRUE" in query
    assert kwargs == {"fetchall": True}
    assert sorted(synced_devices) == ["device-1", "device-2"]
