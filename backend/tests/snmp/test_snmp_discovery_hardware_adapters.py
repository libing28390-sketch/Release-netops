from __future__ import annotations

from services.snmp_discovery_service import (
    _build_cisco_cpu_sensors,
    _build_cisco_environment_sensors,
    _build_cisco_memory_sensors,
    _pair_rows,
)


def test_cisco_cpu_keeps_both_windows_prefers_rev_columns_and_all_indexes() -> None:
    sensors = _build_cisco_cpu_sensors(
        {
            "cpmCPUTotal5minRev": [("1", 10), ("2", 20)],
            "cpmCPUTotal5min": [("1", 11), ("2", 21)],
            "cpmCPUTotal1minRev": [("1", 30), ("2", 40)],
            "cpmCPUTotal1min": [("1", 31), ("2", 41)],
            # A 5-minute table is already available, so this scalar is not a
            # second source for the same window.
            "avgBusy5": [("0", 50)],
        }
    )

    by_window = {}
    for sensor in sensors:
        by_window.setdefault(sensor["metadata"]["window"], []).append(sensor)

    assert set(by_window) == {"1m", "5m"}
    assert len(by_window["1m"]) == len(by_window["5m"]) == 2
    assert {sensor["source_id"] for sensor in by_window["1m"]} == {"cpmCPUTotal1minRev"}
    assert {sensor["source_id"] for sensor in by_window["5m"]} == {"cpmCPUTotal5minRev"}
    assert {sensor["metadata"]["poll_plan"]["oid"] for sensor in by_window["1m"]} == {
        "1.3.6.1.4.1.9.9.109.1.1.1.1.7",
    }
    assert {sensor["metadata"]["poll_plan"]["oid"] for sensor in by_window["5m"]} == {
        "1.3.6.1.4.1.9.9.109.1.1.1.1.8",
    }
    assert {tuple(sensor["index"]) for sensor in by_window["1m"]} == {(1,), (2,)}
    assert {tuple(sensor["index"]) for sensor in by_window["5m"]} == {(1,), (2,)}
    assert all(sensor["measurement_type"] == "cpu_usage_percent" for sensor in sensors)
    assert all(sensor["metadata"]["window"] in {"1m", "5m"} for sensor in sensors)


def test_cisco_avg_busy5_is_only_the_five_minute_fallback_and_uses_get() -> None:
    fallback = _build_cisco_cpu_sensors(
        {
            "cpmCPUTotal1minRev": [("3", 22), ("4", 34)],
            "avgBusy5": [("0", 45)],
        }
    )

    one_minute = [sensor for sensor in fallback if sensor["metadata"]["window"] == "1m"]
    five_minute = [sensor for sensor in fallback if sensor["metadata"]["window"] == "5m"]
    assert len(one_minute) == 2
    assert len(five_minute) == 1
    assert five_minute[0]["source_id"] == "avgBusy5"
    assert five_minute[0]["index"] == []
    assert five_minute[0]["metadata"]["poll_plan"] == {
        "kind": "get",
        "oid": "1.3.6.1.4.1.9.2.1.58.0",
    }

    with_table = _build_cisco_cpu_sensors(
        {
            "cpmCPUTotal5minRev": [("3", 22)],
            "avgBusy5": [("0", 45)],
        }
    )
    assert {sensor["source_id"] for sensor in with_table} == {"cpmCPUTotal5minRev"}


def test_cisco_memory_creates_one_canonical_sensor_per_paired_index() -> None:
    used_oid = "1.3.6.1.4.1.9.9.48.1.1.1.5"
    free_oid = "1.3.6.1.4.1.9.9.48.1.1.1.6"
    used_rows = [("1.1", 80), ("1.2", 35), ("2", 999)]
    free_rows = [("1.1", 20), ("1.2", 65), ("3", 100)]
    paired_indexes = _pair_rows(used_rows, free_rows)

    sensors = _build_cisco_memory_sensors(
        "ciscoMemoryPool", used_oid, free_oid, paired_indexes,
    )

    assert paired_indexes == ["1.1", "1.2"]
    assert len(sensors) == 6
    expected_measurements = {
        "memory_used_bytes": "bytes",
        "memory_total_bytes": "bytes",
        "memory_usage_percent": "percent",
    }
    assert {sensor["measurement_type"] for sensor in sensors} == set(expected_measurements)
    assert all(sensor["component_class"] == "memory_pool" for sensor in sensors)
    assert all(sensor["metadata"]["family"] == "ciscoMemoryPool" for sensor in sensors)
    by_index_measurement = {
        (tuple(sensor["index"]), sensor["measurement_type"]): sensor
        for sensor in sensors
    }
    assert set(by_index_measurement) == {
        ((1, 1), measurement_type) for measurement_type in expected_measurements
    } | {
        ((1, 2), measurement_type) for measurement_type in expected_measurements
    }

    for suffix, index in (("1.1", (1, 1)), ("1.2", (1, 2))):
        used = {"oid": used_oid, "index": suffix, "factor": 1.0, "offset": 0.0}
        free = {"oid": free_oid, "index": suffix, "factor": 1.0, "offset": 0.0}
        expected_plans = {
            "memory_used_bytes": {"kind": "memory_component", "used": used},
            "memory_total_bytes": {"kind": "memory_sum", "used": used, "free": free},
            "memory_usage_percent": {"kind": "memory_ratio", "used": used, "free": free},
        }
        for measurement_type, unit in expected_measurements.items():
            sensor = by_index_measurement[(index, measurement_type)]
            assert sensor["unit"] == unit
            assert sensor["index"] == list(index)
            assert sensor["index_labels"] == {"index": suffix}
            assert sensor["metadata"]["pool_index"] == suffix
            assert sensor["metadata"]["poll_plan"] == expected_plans[measurement_type]
        assert len({by_index_measurement[(index, kind)]["sensor_name"] for kind in expected_measurements}) == 1


def test_cisco_environment_fan_and_power_state_codes_are_explicit() -> None:
    fan = _build_cisco_environment_sensors(
        "fan", "1.3.6.1.4.1.9.9.13.1.4.1.3", [("2", 1), ("5", 3)],
    )
    power = _build_cisco_environment_sensors(
        "power_supply", "1.3.6.1.4.1.9.9.13.1.5.1.3", [("1", 1), ("4", 6)],
    )
    expected_states = {
        "1": "normal",
        "2": "warning",
        "3": "critical",
        "4": "critical",
        "5": "unknown",
        "6": "critical",
    }

    assert {sensor["component_class"] for sensor in fan} == {"fan_state"}
    assert {sensor["component_class"] for sensor in power} == {"power_supply_state"}
    assert all(sensor["measurement_type"] == "component_state" for sensor in fan + power)
    assert all(sensor["states"] == expected_states for sensor in fan + power)
    assert {sensor["oid"] for sensor in fan} == {".1.3.6.1.4.1.9.9.13.1.4.1.3"}
    assert {sensor["oid"] for sensor in power} == {".1.3.6.1.4.1.9.9.13.1.5.1.3"}
    assert {tuple(sensor["index"]) for sensor in fan} == {(2,), (5,)}
    assert {tuple(sensor["index"]) for sensor in power} == {(1,), (4,)}
