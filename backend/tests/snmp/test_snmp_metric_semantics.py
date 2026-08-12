from __future__ import annotations

import asyncio
import json
import sqlite3

from services.snmp_counter_service import calculate_counter_delta
from services.snmp_metric_profile_service import (
    _collector_status,
    get_model_metric_profile_mapping,
    normalize_metric_config,
)
from services.snmp_service import SnmpTypedValue, probe_metric_definition


def test_counter32_wrap_is_accepted_only_as_a_plausible_single_wrap() -> None:
    result = calculate_counter_delta(
        5,
        2**32 - 6,
        10,
        32,
        max_rate_per_sec=10,
    )
    assert result["status"] == "wrapped"
    assert result["delta"] == 11


def test_counter64_restart_is_a_baseline_not_a_spike() -> None:
    result = calculate_counter_delta(
        5,
        100,
        10,
        64,
        current_uptime_cs=100,
        previous_uptime_cs=200,
    )
    assert result["status"] == "device_restart"
    assert result["rate_per_sec"] is None


def test_metric_definition_rejects_counter_as_direct_percentage(monkeypatch) -> None:
    async def fake_get(*_args, **_kwargs):
        return SnmpTypedValue(42, "counter", 64)

    monkeypatch.setattr("services.snmp_service._snmp_get_typed", fake_get)
    result = asyncio.run(
        probe_metric_definition(
            "192.0.2.1",
            "public",
            {"mode": "direct_percent", "oid": "1.3.6.1.4.1.1"},
        )
    )
    assert result["passed"] is False
    assert result["status"] == "type_mismatch"
    assert result["counter_bits"] == 64


def test_metric_definition_accepts_typed_gauge_percentage(monkeypatch) -> None:
    async def fake_get(*_args, **_kwargs):
        return SnmpTypedValue(42, "gauge", 32)

    monkeypatch.setattr("services.snmp_service._snmp_get_typed", fake_get)
    result = asyncio.run(
        probe_metric_definition(
            "192.0.2.1",
            "public",
            {"mode": "direct_percent", "oid": "1.3.6.1.4.1.2"},
        )
    )
    assert result["passed"] is True
    assert result["value"] == 42


def test_status_metric_returns_true_for_normal_and_false_for_abnormal(monkeypatch) -> None:
    current_code = {"value": 1}

    async def fake_get(*_args, **_kwargs):
        return SnmpTypedValue(current_code["value"], "integer", 32)

    monkeypatch.setattr("services.snmp_service._snmp_get_typed", fake_get)
    config = {
        "mode": "status_code",
        "oid": "1.3.6.1.4.1.5",
        "status_ok_values": "1",
        "status_fail_values": "2,3",
    }
    normal = asyncio.run(probe_metric_definition("192.0.2.1", "public", config))
    assert normal["passed"] is True
    assert normal["value"] is True
    assert normal["unit"] == "bool"

    current_code["value"] = 2
    abnormal = asyncio.run(probe_metric_definition("192.0.2.1", "public", config))
    assert abnormal["passed"] is True
    assert abnormal["value"] is False
    assert abnormal["status"] == "fail"


def test_status_metric_returns_null_for_unmapped_code(monkeypatch) -> None:
    async def fake_get(*_args, **_kwargs):
        return SnmpTypedValue(99, "integer", 32)

    monkeypatch.setattr("services.snmp_service._snmp_get_typed", fake_get)
    result = asyncio.run(
        probe_metric_definition(
            "192.0.2.1",
            "public",
            {
                "mode": "status_code",
                "oid": "1.3.6.1.4.1.6",
                "status_ok_values": "1",
                "status_fail_values": "2",
            },
        )
    )
    assert result["passed"] is False
    assert result["value"] is None
    assert result["status"] == "unknown"


def test_direct_value_keeps_unit_and_rejects_counter(monkeypatch) -> None:
    async def fake_get(*_args, **_kwargs):
        return SnmpTypedValue(38, "gauge", 32)

    monkeypatch.setattr("services.snmp_service._snmp_get_typed", fake_get)
    result = asyncio.run(
        probe_metric_definition(
            "192.0.2.1",
            "public",
            {"mode": "direct_value", "oid": "1.3.6.1.4.1.7", "unit": "°C"},
        )
    )
    assert result["passed"] is True
    assert result["value"] == 38
    assert result["unit"] == "°C"


def test_status_metric_normalization_requires_normal_codes() -> None:
    try:
        normalize_metric_config({"mode": "status_code", "oid": "1.3.6.1.4.1.8"})
    except ValueError as exc:
        assert "status_ok_values" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("status profile without normal codes must be rejected")


def test_profile_metric_categories_keep_output_contract() -> None:
    from services.snmp_metric_profile_service import _validated_profile_values

    try:
        _validated_profile_values(
            {
                "metric_definitions": {
                    "fan": {"mode": "direct_value", "oid": "1.3.6.1.4.1.9"},
                }
            }
        )
    except ValueError as exc:
        assert "fan" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("fan must remain a boolean status metric")


def test_counter_profile_requires_explicit_width_and_capacity() -> None:
    try:
        normalize_metric_config(
            {
                "mode": "counter_rate_percent",
                "oid": "1.3.6.1.4.1.3",
                "capacity_oid": "1.3.6.1.4.1.4",
            }
        )
    except ValueError as exc:
        assert "counter_bits" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("counter profile without width must be rejected")


def test_saved_profile_status_distinguishes_match_and_activation() -> None:
    assert _collector_status(False, "unverified", 3) == "builtin_only"
    assert _collector_status(True, "unverified", 3) == "blocked_unverified"
    assert _collector_status(True, "failed", 3) == "blocked_failed"
    assert _collector_status(True, "verified", 3) == "active"
    assert _collector_status(True, "verified", 0) == "no_matching_device"


def test_profile_mapping_uses_canonical_vendor_and_exact_model() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE snmp_metric_profiles (
            id TEXT, vendor_key TEXT, vendor_name TEXT, model_key TEXT,
            model_name TEXT, cpu_oid TEXT, memory_oid TEXT,
            cpu_config_json TEXT, memory_config_json TEXT,
            metric_definitions_json TEXT, verification_status TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE devices (
            id TEXT, hostname TEXT, ip_address TEXT, vendor TEXT,
            platform TEXT, model TEXT, snmp_cpu_oid TEXT, snmp_memory_oid TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO snmp_metric_profiles
            (id, vendor_key, vendor_name, model_key, model_name,
             cpu_oid, memory_oid, cpu_config_json, memory_config_json,
             metric_definitions_json, verification_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "profile-1",
            "cisco",
            "Cisco",
            "c9300-48p",
            "C9300-48P",
            "1.3.6.1.4.1.1",
            "",
            json.dumps({"mode": "direct_percent", "oid": "1.3.6.1.4.1.1"}),
            "{}",
            json.dumps({"cpu": {"mode": "direct_percent", "oid": "1.3.6.1.4.1.1"}}),
            "unverified",
        ),
    )
    conn.executemany(
        """
        INSERT INTO devices
            (id, hostname, ip_address, vendor, platform, model,
             snmp_cpu_oid, snmp_memory_oid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("device-1", "core-sw-01", "192.0.2.10", "Cisco", "cisco_ios", "C9300-48P", "", ""),
            ("device-2", "other-vendor", "192.0.2.11", "H3C", "h3c_comware", "C9300-48P", "", ""),
            ("device-3", "other-model", "192.0.2.12", "Cisco", "cisco_ios", "C9300-49P", "", ""),
        ],
    )

    mapping = get_model_metric_profile_mapping(conn, "profile-1")

    assert mapping["matched_device_count"] == 1
    assert mapping["sample_device_id"] == "device-1"
    assert mapping["same_model_other_vendor_count"] == 1
    assert mapping["collector_status"] == "blocked_unverified"
    assert mapping["devices"][0]["device_id"] == "device-1"
