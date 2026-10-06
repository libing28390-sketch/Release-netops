from __future__ import annotations

import asyncio

from services import snmp_hardware_inventory_service as inventory
from services import snmp_hardware_probe_service as probe
from services import snmp_service
from services.snmp_hardware_normalization import (
    normalize_percentage,
    normalize_scaled_value,
    normalize_temperature_celsius,
)


def test_shared_normalizer_applies_scale_and_canonical_ranges() -> None:
    assert normalize_scaled_value("35", 2, 1) == 71
    assert normalize_scaled_value("not-a-number", 1, 0) is None
    assert normalize_scaled_value(35, 0, 0) is None

    assert normalize_percentage(0) == 0
    assert normalize_percentage(100) == 100
    assert normalize_percentage(49, 2, 1) == 99
    assert normalize_percentage(50, 2, 1) is None

    assert normalize_temperature_celsius(-80) == -80
    assert normalize_temperature_celsius(200) == 200
    assert normalize_temperature_celsius(65535) is None
    assert normalize_temperature_celsius(425, 0.1) == 42.5


def test_profile_and_inventory_poll_share_percent_and_temperature_normalization(monkeypatch) -> None:
    import database

    current = {"raw": "35"}
    written_samples = []

    async def profile_points(*_args, **_kwargs):
        return [("1", snmp_service.SnmpTypedValue(float(current["raw"]), "gauge", 32))]

    async def inventory_walk(_ip, _community, oid, _port, _version):
        return [("1", current["raw"])]

    async def inventory_get(_ip, _community, _oid, _port, _version):
        return current["raw"]

    class Connection:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(snmp_service, "_read_typed_points", profile_points)
    monkeypatch.setattr(snmp_service, "_snmp_get_versioned", inventory_get)
    monkeypatch.setattr(database, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        inventory,
        "record_sensor_samples_batch",
        lambda _conn, samples: written_samples.extend(
            (sample["device_id"], sample["sensor_key"], sample["value"],
             sample["raw_value"], sample["quality"])
            for sample in samples
        ),
    )

    cases = [
        {
            "measurement_type": "cpu_usage_percent",
            "metric_name": "cpu",
            "mode": "direct_percent",
            "oid": "1.3.6.1.4.1.55555.1",
            "raw": "35",
            "poll_kind": "direct",
            "scale": 2,
            "offset": 1,
            "expected_value": 71,
            "expected_quality": "good",
            "expected_profile_status": "ok",
        },
        {
            "measurement_type": "cpu_usage_percent",
            "metric_name": "cpu",
            "mode": "direct_percent",
            "oid": "1.3.6.1.4.1.55555.1",
            "raw": "50",
            "poll_kind": "get",
            "scale": 2,
            "offset": 1,
            "expected_value": None,
            "expected_quality": "invalid",
            "expected_profile_status": "out_of_range",
        },
        {
            "measurement_type": "temperature_celsius",
            "metric_name": "temperature",
            "mode": "direct_value",
            "oid": "1.3.6.1.4.1.55555.2",
            "raw": "425",
            "poll_kind": "direct",
            "scale": 0.1,
            "offset": 0,
            "expected_value": 42.5,
            "expected_quality": "good",
            "expected_profile_status": "ok",
        },
        {
            "measurement_type": "temperature_celsius",
            "metric_name": "temperature",
            "mode": "direct_value",
            "oid": "1.3.6.1.4.1.55555.2",
            "raw": "65535",
            "poll_kind": "get",
            "scale": 1,
            "offset": 0,
            "expected_value": None,
            "expected_quality": "invalid",
            "expected_profile_status": "invalid_value",
        },
    ]

    for index, case in enumerate(cases, start=1):
        current["raw"] = case["raw"]
        config = {
            "mode": case["mode"],
            "oid": case["oid"],
            "scale": case["scale"],
            "offset": case["offset"],
        }
        profile_result = asyncio.run(
            snmp_service._collect_metric_definition(
                "192.0.2.1",
                "community",
                config,
                161,
                metric_name=case["metric_name"],
            )
        )
        sensor_key = f"sensor-{index}"
        sensor = {
            "device_id": "device-1",
            "sensor_key": sensor_key,
            "measurement_type": case["measurement_type"],
            "index": [1],
            "metadata": {
                "poll_plan": {
                    "kind": case["poll_kind"],
                    "oid": case["oid"],
                    "index": "1",
                    "factor": case["scale"],
                    "offset": case["offset"],
                },
            },
        }
        poll_result = asyncio.run(
            probe.poll_hardware_inventory(
                "192.0.2.1",
                "community",
                161,
                "2c",
                [sensor],
                walk_func=inventory_walk,
            )
        )
        sample = written_samples[-1]

        assert profile_result["value"] == case["expected_value"]
        assert profile_result["status"] == case["expected_profile_status"]
        assert sample[2] == profile_result["value"]
        assert sample[3] == case["raw"]
        assert sample[4] == case["expected_quality"]
        assert poll_result["good"] == int(case["expected_quality"] == "good")
        assert poll_result["invalid"] == int(case["expected_quality"] == "invalid")
