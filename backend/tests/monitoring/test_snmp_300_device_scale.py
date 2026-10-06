"""Isolated PostgreSQL scale check for the SNMP hardware sample polling path.

This runs the real telemetry B-loop and hardware inventory poller against a
disposable PostgreSQL database. Device rows and hardware sensors are synthetic;
the SNMP walker is injected and never opens a socket. The benchmark covers
inventory loading and sample polling, not automatic MIB discovery or a full
``process_device_slow`` pass.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import math
import sys
import time
from collections import Counter, defaultdict

import pytest


_DEVICE_COUNT = 300
_SNMP_BOUND_DEVICE_COUNT = 264
_UNBOUND_DEVICE_COUNT = _DEVICE_COUNT - _SNMP_BOUND_DEVICE_COUNT
_SENSORS_PER_BOUND_DEVICE = 353
_ACTIVE_SENSOR_COUNT = _SNMP_BOUND_DEVICE_COUNT * _SENSORS_PER_BOUND_DEVICE
_SENSOR_OID = "1.3.6.1.4.1.99999.1.1.1.1"
_FAKE_COMMUNITY = "synthetic-read-only-community"
_FAKE_WALK_DELAY_SECONDS = 0.001


class _StopAfterCycle(Exception):
    """Stop the orchestrator after its first completed cycle."""


class _CountingConnection:
    """Count SQL issued by the measured poll path without changing its driver."""

    def __init__(self, connection, metrics: dict) -> None:
        self._connection = connection
        self._metrics = metrics

    def execute(self, statement, params=None):
        started = time.perf_counter()
        try:
            return self._connection.execute(statement, params)
        finally:
            self._record(statement, time.perf_counter() - started)

    def executemany(self, statement, params_list):
        started = time.perf_counter()
        try:
            return self._connection.executemany(statement, params_list)
        finally:
            self._record(statement, time.perf_counter() - started)

    def _record(self, statement, elapsed_seconds: float) -> None:
        normalized = " ".join(str(statement).lower().split())
        if normalized.startswith("select * from devices where status"):
            category = "device_snapshot"
        elif "from snmp_hardware_sensors" in normalized and "for update" in normalized:
            category = "sample_lock_select"
        elif normalized.startswith("update snmp_hardware_sensors as sensor"):
            category = "sample_batch_update"
        elif normalized.startswith("update snmp_hardware_sensors"):
            category = "sample_update"
        elif "from snmp_hardware_sensors" in normalized:
            category = "sensor_list"
        else:
            category = "other"

        owner = _current_device.get()
        self._metrics["sql_count"] += 1
        self._metrics["sql_by_category"][category] += 1
        self._metrics["sql_ms_by_category"][category] += elapsed_seconds * 1000
        self._metrics["sql_by_device"][owner][category] += 1
        self._metrics["sql_ms_by_device"][owner][category] += elapsed_seconds * 1000

    def __getattr__(self, name):
        return getattr(self._connection, name)


_current_device: contextvars.ContextVar[str] = contextvars.ContextVar(
    "snmp_scale_current_device", default="orchestrator"
)


def _synthetic_ip(device_number: int) -> str:
    """Return a TEST-NET address; the injected walker prevents any network use."""
    if device_number < 254:
        return f"198.51.100.{device_number + 1}"
    return f"203.0.113.{device_number - 253}"


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def test_telemetry_b_loop_polls_300_synthetic_devices_in_isolated_postgres(
    isolated_db, monkeypatch, record_property
) -> None:
    import database
    import database.core as database_core
    from engine.orchestrator import TelemetryOrchestrator
    from services import background_monitor_service as monitor
    from services.snmp_hardware_inventory_service import list_hardware_sensors
    from services.snmp_hardware_probe_service import poll_hardware_inventory

    # The shared fixture guarantees a disposable nexora_pytest_* target. Keep
    # this assertion local to the scale test because it writes more than 90k rows.
    assert database_core._USE_PG is True
    assert database_core._DATABASE_URL.rsplit("/", 1)[-1].startswith("nexora_pytest_case_")

    seed_connection = database.get_db_connection()
    try:
        seed_connection.execute(
            """
            INSERT INTO devices (
                id, hostname, ip_address, platform, status, snmp_community
            )
            SELECT
                'scale-snmp-device-' || LPAD(device_number::text, 3, '0'),
                'scale-edge-' || LPAD(device_number::text, 3, '0'),
                CASE
                    WHEN device_number < 254
                    THEN '198.51.100.' || (device_number + 1)::text
                    ELSE '203.0.113.' || (device_number - 253)::text
                END,
                'synthetic_platform',
                'online',
                CASE WHEN device_number < ? THEN ? ELSE '' END
            FROM generate_series(0, ? - 1) AS devices(device_number)
            """,
            (_SNMP_BOUND_DEVICE_COUNT, _FAKE_COMMUNITY, _DEVICE_COUNT),
        )
        seed_connection.execute(
            """
            INSERT INTO snmp_hardware_sensors (
                sensor_id, device_id, sensor_key, source_type, source_id,
                component_class, measurement_type, index_json, index_labels_json,
                oid, unit, metadata_json, last_value, last_raw_value, last_quality,
                first_seen, last_seen, last_success
            )
            SELECT
                'scale-sensor-id-' || LPAD(devices.device_number::text, 3, '0')
                    || '-' || LPAD(sensors.sensor_number::text, 3, '0'),
                'scale-snmp-device-' || LPAD(devices.device_number::text, 3, '0'),
                'scale-temperature-' || LPAD(devices.device_number::text, 3, '0')
                    || '-' || LPAD(sensors.sensor_number::text, 3, '0'),
                'entity_sensor',
                'synthetic-scale-fixture',
                'temperature',
                'temperature_celsius',
                jsonb_build_array(sensors.sensor_number),
                jsonb_build_object('sensor_index', sensors.sensor_number::text),
                ?,
                'celsius',
                jsonb_build_object(
                    'poll_plan', jsonb_build_object(
                        'kind', 'direct', 'oid', ?,
                        'index', sensors.sensor_number::text,
                        'factor', 1, 'offset', 0
                    )
                ),
                21.0,
                (21 + sensors.sensor_number % 4)::text,
                'good',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM generate_series(0, ? - 1) AS devices(device_number)
            CROSS JOIN generate_series(1, ?) AS sensors(sensor_number)
            """,
            (_SENSOR_OID, _SENSOR_OID, _SNMP_BOUND_DEVICE_COUNT, _SENSORS_PER_BOUND_DEVICE),
        )
        seed_connection.commit()
    finally:
        seed_connection.close()

    metrics = {
        "sql_count": 0,
        "sql_by_category": Counter(),
        "sql_ms_by_category": defaultdict(float),
        "sql_by_device": defaultdict(Counter),
        "sql_ms_by_device": defaultdict(lambda: defaultdict(float)),
    }
    original_get_connection = database.get_db_connection

    def counted_get_connection():
        return _CountingConnection(original_get_connection(), metrics)

    # _db_quick captured the database function at module import time, while the
    # hardware poller imports it when called. Patch both seams for one complete
    # measured cycle. The underlying connection still belongs to isolated_db.
    monkeypatch.setattr(database, "get_db_connection", counted_get_connection)
    monkeypatch.setattr(monitor, "get_db_connection", counted_get_connection)

    walk_calls = 0
    walk_inflight = 0
    max_walk_inflight = 0
    collection_inflight = 0
    max_collection_inflight = 0
    walk_ms_by_device: dict[str, float] = defaultdict(float)
    completed_cycle: list[bool] = []
    per_device: dict[str, dict[str, float | int]] = {}
    real_sleep = asyncio.sleep
    device_ids_by_ip = {
        _synthetic_ip(index): f"scale-snmp-device-{index:03d}"
        for index in range(_SNMP_BOUND_DEVICE_COUNT)
    }
    completed_device_count = 0

    async def fake_walk(ip, community, oid, port, version):
        nonlocal walk_calls, walk_inflight, max_walk_inflight
        device_id = device_ids_by_ip[ip]
        assert community == _FAKE_COMMUNITY
        assert oid == _SENSOR_OID
        assert port == 161
        assert version == "2c"
        walk_calls += 1
        walk_inflight += 1
        max_walk_inflight = max(max_walk_inflight, walk_inflight)
        started = time.perf_counter()
        try:
            await real_sleep(_FAKE_WALK_DELAY_SECONDS)
            return [
                (str(sensor_number), str(19 + sensor_number % 5))
                for sensor_number in range(1, _SENSORS_PER_BOUND_DEVICE + 1)
            ]
        finally:
            walk_ms_by_device[device_id] += (time.perf_counter() - started) * 1000
            walk_inflight -= 1

    async def collect_hardware_for_device(device, *, cycle_tick: int) -> None:
        nonlocal collection_inflight, max_collection_inflight, completed_device_count
        device_id = str(device["id"])
        context_token = _current_device.set(device_id)
        collection_inflight += 1
        max_collection_inflight = max(max_collection_inflight, collection_inflight)
        try:
            if str(device.get("snmp_community") or "") != _FAKE_COMMUNITY:
                per_device[device_id] = {
                    "sensors": 0,
                    "sensor_load_ms": 0.0,
                    "poll_ms": 0.0,
                    "good": 0,
                    "missing": 0,
                    "invalid": 0,
                    "unsupported": 0,
                }
                return

            load_started = time.perf_counter()
            sensor_connection = counted_get_connection()
            try:
                sensors = list_hardware_sensors(
                    sensor_connection, device_id, include_retired=False
                )
            finally:
                sensor_connection.close()
            sensor_load_ms = (time.perf_counter() - load_started) * 1000

            poll_started = time.perf_counter()
            result = await poll_hardware_inventory(
                str(device["ip_address"]),
                str(device["snmp_community"]),
                161,
                "2c",
                sensors,
                walk_func=fake_walk,
            )
            poll_ms = (time.perf_counter() - poll_started) * 1000
            per_device[device_id] = {
                "sensors": len(sensors),
                "sensor_load_ms": sensor_load_ms,
                "poll_ms": poll_ms,
                "good": result["good"],
                "missing": result["missing"],
                "invalid": result["invalid"],
                "unsupported": result["unsupported_mapping"],
            }
        finally:
            completed_device_count += 1
            if completed_device_count % 60 == 0:
                completed_samples = sum(int(item["good"]) for item in per_device.values())
                print(
                    "SNMP_300_SCALE_PROGRESS "
                    f"devices_done={completed_device_count}/{_DEVICE_COUNT} "
                    f"samples_done={completed_samples}/{_ACTIVE_SENSOR_COUNT} "
                    f"elapsed_s={time.perf_counter() - cycle_started:.1f}"
                )
            collection_inflight -= 1
            _current_device.reset(context_token)

    def mark_cycle_complete() -> None:
        completed_cycle.append(True)

    async def stop_at_scheduler_delay(seconds: float, *args, **kwargs):
        if seconds >= 60:
            if not completed_cycle:
                raise AssertionError("orchestrator reached its next delay before completing a cycle")
            raise _StopAfterCycle
        return await real_sleep(seconds, *args, **kwargs)

    monkeypatch.setattr(monitor, "process_device_slow", collect_hardware_for_device)
    monkeypatch.setattr(monitor, "sync_lldp_neighbor_alerts", mark_cycle_complete)
    monkeypatch.setattr(asyncio, "sleep", stop_at_scheduler_delay)

    cycle_started = time.perf_counter()

    async def run_one_cycle() -> None:
        with pytest.raises(_StopAfterCycle):
            await TelemetryOrchestrator().b_loop()

    asyncio.run(run_one_cycle())
    cycle_ms = (time.perf_counter() - cycle_started) * 1000

    assert completed_cycle == [True]
    assert len(per_device) == _DEVICE_COUNT
    assert sum(item["sensors"] for item in per_device.values()) == _ACTIVE_SENSOR_COUNT
    assert sum(item["sensors"] == 0 for item in per_device.values()) == _UNBOUND_DEVICE_COUNT
    assert sum(item["good"] for item in per_device.values()) == _ACTIVE_SENSOR_COUNT
    assert sum(item["missing"] + item["invalid"] + item["unsupported"] for item in per_device.values()) == 0
    assert walk_calls == _SNMP_BOUND_DEVICE_COUNT
    expected_scheduler_limit = 2 if sys.platform == "win32" else 20
    assert max_collection_inflight == expected_scheduler_limit
    assert 1 <= max_walk_inflight <= expected_scheduler_limit
    assert metrics["sql_by_category"] == {
        "device_snapshot": 1,
        "sensor_list": _SNMP_BOUND_DEVICE_COUNT,
        "sample_batch_update": _SNMP_BOUND_DEVICE_COUNT,
    }
    assert metrics["sql_count"] == 1 + 2 * _SNMP_BOUND_DEVICE_COUNT

    verification_connection = original_get_connection()
    try:
        persisted = verification_connection.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE last_quality = 'good'),
                   COUNT(DISTINCT device_id)
              FROM snmp_hardware_sensors
             WHERE device_id LIKE 'scale-snmp-device-%'
            """
        ).fetchone()
        device_count = verification_connection.execute(
            "SELECT COUNT(*) FROM devices WHERE id LIKE 'scale-snmp-device-%'"
        ).fetchone()[0]
    finally:
        verification_connection.close()

    assert tuple(persisted) == (
        _ACTIVE_SENSOR_COUNT,
        _ACTIVE_SENSOR_COUNT,
        _SNMP_BOUND_DEVICE_COUNT,
    )
    assert device_count == _DEVICE_COUNT

    sensor_load_samples = [float(item["sensor_load_ms"]) for item in per_device.values()]
    poll_samples = [float(item["poll_ms"]) for item in per_device.values()]
    walk_samples = list(walk_ms_by_device.values())
    category_ms = metrics["sql_ms_by_category"]
    component_totals = {
        "fake_snmp_walk": sum(walk_samples),
        "sensor_list_sql": category_ms["sensor_list"],
        "sample_sql": category_ms["sample_batch_update"],
    }
    slowest_measured_component = max(component_totals, key=component_totals.get)
    summary = {
        "scope": "isolated_postgresql_hardware_inventory_poll_with_fake_snmp",
        "devices": _DEVICE_COUNT,
        "snmp_bound_devices": _SNMP_BOUND_DEVICE_COUNT,
        "unbound_devices": _UNBOUND_DEVICE_COUNT,
        "sensors_per_bound_device": _SENSORS_PER_BOUND_DEVICE,
        "active_sensors": _ACTIVE_SENSOR_COUNT,
        "cycle_ms": round(cycle_ms, 2),
        "scheduler_limit": expected_scheduler_limit,
        "max_concurrent_device_collections": max_collection_inflight,
        "max_concurrent_fake_walks": max_walk_inflight,
        "fake_walk_calls": walk_calls,
        "sql_calls": metrics["sql_count"],
        "sql_calls_by_category": dict(metrics["sql_by_category"]),
        "sql_execute_ms_by_category": {
            name: round(value, 2) for name, value in category_ms.items()
        },
        "sensor_load_ms_p95": round(_percentile(sensor_load_samples, 0.95), 2),
        "hardware_poll_ms_p95": round(_percentile(poll_samples, 0.95), 2),
        "fake_walk_ms_p95": round(_percentile(walk_samples, 0.95), 2),
        "cumulative_components_ms": {
            name: round(value, 2) for name, value in component_totals.items()
        },
        "slowest_measured_component": slowest_measured_component,
    }
    print(f"SNMP_300_SCALE {json.dumps(summary, sort_keys=True)}")

    # Preserve a compact benchmark record in pytest's JUnit output as well as
    # the one-line -s output used when the parent task captures evidence.
    record_property("snmp_300_scale", json.dumps(summary, sort_keys=True))
