from __future__ import annotations

import asyncio
import json
from backend.tests.pg_test_utils import postgresql_test_driver
from services.snmp_counter_service import calculate_counter_delta
from services.snmp_metric_profile_service import (
    _collector_status,
    annotate_devices_with_snmp_profile,
    apply_official_model_preset,
    get_model_metric_profile_mapping,
    invalidate_metric_profile_cache,
    normalize_interface_config,
    normalize_metric_config,
    resolve_health_metric_profiles,
)
from services.snmp_service import (
    SnmpTypedValue,
    collect_interface_data,
    collect_interface_health,
    probe_interface_definition,
)


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


def test_interface_profile_normalizes_defaults_and_explicit_width() -> None:
    config = normalize_interface_config({"counter_mode": "counter64"})
    assert config["counter_mode"] == "64"
    assert config["if_name_oid"] == "1.3.6.1.2.1.31.1.1.1.1"
    assert config["if_hc_in_octets_oid"].endswith(".6")
    assert config["if_hc_in_ucast_pkts_oid"].endswith(".7")
    assert config["if_hc_out_broadcast_pkts_oid"].endswith(".13")
    assert config["dot3_hc_fcs_errors_oid"] == "1.3.6.1.2.1.10.7.11.1.2"


def test_interface_probe_requires_paired_counter_width(monkeypatch) -> None:
    async def fake_bulk(_ip, _community, oid, _port):
        if oid == "1.3.6.1.2.1.31.1.1.1.1":
            return [("1", "GigabitEthernet1/0/1")]
        return [("1", "1")]

    async def fake_typed(_ip, _community, oid, _port):
        if oid.endswith(".6") or oid.endswith(".10"):
            return [("1", SnmpTypedValue(100, "counter", 64))]
        return [("1", SnmpTypedValue(100, "counter", 32))]

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fake_bulk)
    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk_typed", fake_typed)
    result = asyncio.run(
        probe_interface_definition(
            "192.0.2.1",
            "public",
            normalize_interface_config({"counter_mode": "64"}),
        )
    )
    assert result["passed"] is True
    assert result["selected_counter_bits"] == 64
    assert result["counter_supported"] == 1


def test_interface_probe_bounds_unresponsive_oid_walks(monkeypatch) -> None:
    async def slow_walk(*_args, **_kwargs):
        await asyncio.sleep(10)
        return []

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", slow_walk)
    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk_typed", slow_walk)
    result = asyncio.run(
        asyncio.wait_for(
            probe_interface_definition(
                "192.0.2.1",
                "public",
                normalize_interface_config({"counter_mode": "64"}),
            ),
            timeout=4,
        )
    )

    assert result["passed"] is False
    assert result["status"] == "missing"


def test_interface_collector_honors_forced_counter_width(monkeypatch) -> None:
    async def fake_bulk(_ip, _community, oid, _port):
        if oid.endswith(".1.1.1.1"):
            return [("1", "GigabitEthernet1/0/1")]
        if oid.endswith(".8"):
            return [("1", "1")]
        if oid.endswith(".15"):
            return [("1", "1000")]
        if oid.endswith(".5"):
            return [("1", "1000000000")]
        return []

    async def fake_typed(_ip, _community, oid, _port):
        bits = 64 if oid.endswith(".31.1.1.1.6") or oid.endswith(".31.1.1.1.10") else 32
        return [("1", SnmpTypedValue(123, "counter", bits))]

    async def fake_get(*_args, **_kwargs):
        return "1000"

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fake_bulk)
    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk_typed", fake_typed)
    monkeypatch.setattr("services.snmp_service._snmp_get", fake_get)
    result32 = asyncio.run(
        collect_interface_data(
            "192.0.2.32",
            "public",
            interface_config=normalize_interface_config({"counter_mode": "32"}),
        )
    )
    result64 = asyncio.run(
        collect_interface_data(
            "192.0.2.64",
            "public",
            interface_config=normalize_interface_config({"counter_mode": "64"}),
        )
    )
    assert result32[0]["counter_width"] == 32
    assert result64[0]["counter_width"] == 64


def test_interface_collector_keeps_device_counter_values(monkeypatch) -> None:
    async def fake_bulk(_ip, _community, oid, _port):
        if oid.endswith(".1.1.1.1"):
            return [("1", "FortyGigE1/0/53")]
        if oid.endswith(".2.2.1.8"):
            return [("1", "1")]
        if oid.endswith(".31.1.1.1.15"):
            return [("1", "40000")]
        if oid.endswith(".2.2.1.5"):
            return [("1", "40000000000")]
        if oid.endswith(".2.2.1.11"):
            return [("1", "203")]
        if oid.endswith(".2.2.1.17"):
            return [("1", "209")]
        if oid.endswith(".2.2.1.14"):
            return [("1", "206")]
        if oid.endswith(".2.2.1.20"):
            return [("1", "212")]
        return []

    async def fake_typed(_ip, _community, oid, _port):
        if oid.endswith(".31.1.1.1.6"):
            return [("1", SnmpTypedValue(100, "counter", 64))]
        if oid.endswith(".31.1.1.1.10"):
            return [("1", SnmpTypedValue(104, "counter", 64))]
        return []

    async def fake_get(*_args, **_kwargs):
        return "1000"

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fake_bulk)
    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk_typed", fake_typed)
    monkeypatch.setattr("services.snmp_service._snmp_get", fake_get)
    result = asyncio.run(collect_interface_data("192.0.2.253", "public"))

    assert result[0]["counter_quality"] == "hc64_typed"
    assert result[0]["counter_width"] == 64
    assert result[0]["counter_source"] == "ifHCInOctets/ifHCOutOctets"
    assert result[0]["in_octets"] == 100
    assert result[0]["out_octets"] == 104
    assert result[0]["in_ucast_pkts"] == 203
    assert result[0]["out_ucast_pkts"] == 209
    assert result[0]["in_errors"] == 206
    assert result[0]["out_errors"] == 212


def test_interface_collector_prefers_counter64_packets_and_exposes_etherlike_errors(monkeypatch) -> None:
    async def fake_bulk(_ip, _community, oid, _port):
        if oid.endswith(".1.1.1.1"):
            return [("1", "FortyGigE1/0/54")]
        if oid.endswith(".2.2.1.8"):
            return [("1", "1")]
        if oid.endswith(".31.1.1.1.15"):
            return [("1", "40000")]
        if oid.endswith(".2.2.1.14"):
            return [("1", "17")]
        if oid.endswith(".2.2.1.20"):
            return [("1", "19")]
        if oid.endswith(".10.7.11.1.2"):
            return [("1", "23")]
        if oid.endswith(".10.7.11.1.4"):
            return [("1", "29")]
        if oid.endswith(".10.7.11.1.5"):
            return [("1", "31")]
        if oid.endswith(".10.7.11.1.6"):
            return [("1", "37")]
        return []

    async def fake_typed(_ip, _community, oid, _port):
        values = {
            ".31.1.1.1.6": 1000,
            ".31.1.1.1.10": 2000,
            ".31.1.1.1.7": 101,
            ".31.1.1.1.8": 102,
            ".31.1.1.1.9": 103,
            ".31.1.1.1.11": 201,
            ".31.1.1.1.12": 202,
            ".31.1.1.1.13": 203,
        }
        for suffix, value in values.items():
            if oid.endswith(suffix):
                return [("1", SnmpTypedValue(value, "counter", 64))]
        return []

    async def fake_get(*_args, **_kwargs):
        return "1000"

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fake_bulk)
    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk_typed", fake_typed)
    monkeypatch.setattr("services.snmp_service._snmp_get", fake_get)
    result = asyncio.run(collect_interface_data("192.0.2.254", "public"))

    assert result[0]["in_packets_total"] == 306
    assert result[0]["out_packets_total"] == 606
    assert result[0]["packet_counter_source"] == "ifHCIn/Out{Ucast,Multicast,Broadcast}Pkts"
    assert result[0]["fcs_errors"] == 23
    assert result[0]["fcs_source"] == "dot3HCStatsFCSErrors"
    assert result[0]["frame_too_long_errors"] == 29
    assert result[0]["mac_rx_errors"] == 31
    assert result[0]["symbol_errors"] == 37


def test_interface_probe_warns_on_uniform_nonzero_physical_counter_values(monkeypatch) -> None:
    async def fake_bulk(_ip, _community, oid, _port):
        if oid.endswith(".1.1.1.1"):
            return [
                ("1", "FortyGigE1/0/53"),
                ("2", "FortyGigE1/0/54"),
                ("3", "Ten-GigabitEthernet1/0/49"),
            ]
        if oid.endswith(".2.2.1.8"):
            return [("1", "1"), ("2", "1"), ("3", "1")]
        return []

    async def fake_typed(_ip, _community, oid, _port):
        if oid.endswith(".31.1.1.1.6"):
            return [(index, SnmpTypedValue(100, "counter", 64)) for index in ("1", "2", "3")]
        if oid.endswith(".31.1.1.1.10"):
            return [(index, SnmpTypedValue(104, "counter", 64)) for index in ("1", "2", "3")]
        return []

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fake_bulk)
    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk_typed", fake_typed)
    result = asyncio.run(
        probe_interface_definition(
            "192.0.2.1",
            "public",
            normalize_interface_config({"counter_mode": "64"}),
        )
    )

    assert result["passed"] is True
    assert result["warnings"][0]["code"] == "uniform_nonzero_counter64"
    assert result["warnings"][0]["physical_interfaces"] == 3
    assert "verify the device SNMP Agent/view" in result["message"]


def test_interface_collector_filters_virtual_interfaces(monkeypatch) -> None:
    async def fake_bulk(_ip, _community, oid, _port):
        if oid.endswith(".1.1.1.1"):
            return [
                ("1", "GigabitEthernet1/0/1"),
                ("2", "InLoopBack0"),
                ("3", "Register-Tunnel0"),
            ]
        if oid.endswith(".2.2.1.8"):
            return [("1", "1"), ("2", "1"), ("3", "1")]
        return []

    async def fake_typed(*_args, **_kwargs):
        return []

    async def fake_get(*_args, **_kwargs):
        return "1000"

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fake_bulk)
    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk_typed", fake_typed)
    monkeypatch.setattr("services.snmp_service._snmp_get", fake_get)
    result = asyncio.run(collect_interface_data("192.0.2.88", "public"))

    assert [row["name"] for row in result] == ["GigabitEthernet1/0/1"]


def test_interface_health_collector_only_walks_identity_and_oper_status(monkeypatch) -> None:
    requested: list[str] = []

    async def fake_bulk(_ip, _community, oid, _port):
        requested.append(oid)
        if oid.endswith(".31.1.1.1.1"):
            return [("1", "GigabitEthernet1/0/1"), ("2", "Vlan-interface1")]
        if oid.endswith(".2.2.1.8"):
            return [("1", "1"), ("2", "2")]
        return []

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fake_bulk)
    result = asyncio.run(collect_interface_health("192.0.2.77", "public"))

    assert requested == [
        "1.3.6.1.2.1.31.1.1.1.1",
        "1.3.6.1.2.1.2.2.1.8",
    ]
    assert [row["name"] for row in result] == ["GigabitEthernet1/0/1"]
    assert result[0]["status"] == "up"
    assert result[0]["counter_width"] is None
    assert result[0]["collection_mode"] == "health_only"


def test_health_profile_resolution_filters_non_health_metrics_and_keeps_template_status(monkeypatch) -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
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
        INSERT INTO snmp_metric_profiles
            (id, vendor_key, vendor_name, model_key, model_name,
             cpu_oid, memory_oid, cpu_config_json, memory_config_json,
             metric_definitions_json, verification_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "profile-health-1",
            "cisco",
            "Cisco",
            "c9300",
            "C9300",
            "",
            "",
            "{}",
            "{}",
            json.dumps({
                "cpu": {"mode": "direct_percent", "oid": "1.3.6.1.4.1.1"},
                "temperature": {"mode": "direct_value", "oid": "1.3.6.1.4.1.2"},
                "storage": {"mode": "direct_percent", "oid": "1.3.6.1.4.1.3"},
            }),
            "verified",
        ),
    )
    monkeypatch.setattr("services.snmp_metric_profile_service.get_db_connection", lambda: conn)
    invalidate_metric_profile_cache()
    try:
        resolved = resolve_health_metric_profiles(
            {"vendor": "Cisco", "platform": "cisco_ios", "model": "C9300"}
        )
        association = annotate_devices_with_snmp_profile(
            [{"id": "device-1", "vendor": "Cisco", "platform": "cisco_ios", "model": "C9300"}]
        )[0]["snmp_metric_profile"]
    finally:
        invalidate_metric_profile_cache()
        conn.close()

    assert resolved["profile_id"] == "profile-health-1"
    assert resolved["profile_status"] == "verified"
    assert resolved["profile_source"] == "snmp_template"
    assert resolved["metric_keys"] == ["cpu", "temperature"]
    assert "storage" not in resolved["metrics"]
    assert resolved["metric_sources"]["memory"] == "template_not_applied"

    assert association["id"] == "profile-health-1"
    assert association["source"] == "snmp_template"
    assert association["collection_mode"] == "health_only"


def test_apply_official_preset_materializes_the_profile_used_by_device_resolution(monkeypatch) -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.execute(
        """
        CREATE TABLE snmp_metric_profiles (
            id TEXT PRIMARY KEY,
            vendor_key TEXT NOT NULL,
            vendor_name TEXT NOT NULL DEFAULT '',
            model_key TEXT NOT NULL,
            model_name TEXT NOT NULL DEFAULT '',
            cpu_oid TEXT NOT NULL DEFAULT '',
            memory_oid TEXT NOT NULL DEFAULT '',
            cpu_config_json TEXT NOT NULL DEFAULT '{}',
            memory_config_json TEXT NOT NULL DEFAULT '{}',
            metric_definitions_json TEXT NOT NULL DEFAULT '{}',
            interface_config_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL DEFAULT '',
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            last_test_at TEXT,
            last_test_device_id TEXT NOT NULL DEFAULT '',
            last_test_message TEXT NOT NULL DEFAULT '',
            interface_verification_status TEXT NOT NULL DEFAULT 'unverified',
            interface_last_test_at TEXT,
            interface_last_test_device_id TEXT NOT NULL DEFAULT '',
            interface_last_test_message TEXT NOT NULL DEFAULT ''
        )
        """
    )
    preset = {
        "id": "md-h3c-s6800-v7",
        "family_id": "md-h3c-comware-v7",
        "vendor": "H3C",
        "model": "S6800",
        "metric_definitions": {
            "cpu": {"mode": "direct_percent", "oid": "1.3.6.1.4.1.25506.1"},
        },
        "interface_config": {},
        "testable": True,
    }
    monkeypatch.setattr("services.snmp_preset_service.list_preset_profiles", lambda: [preset])
    try:
        created = apply_official_model_preset(conn, preset["id"], updated_by="operator")
        assert created["applied_mode"] == "created"
        assert created["source"] == "official_preset"

        updated = apply_official_model_preset(conn, preset["id"], updated_by="operator")
        assert updated["applied_mode"] == "updated"
        assert updated["id"] == created["id"]

        monkeypatch.setattr("services.snmp_metric_profile_service.get_db_connection", lambda: conn)
        invalidate_metric_profile_cache()
        resolved = resolve_health_metric_profiles({"vendor": "H3C", "platform": "h3c_comware", "model": "S6800"})
        association = annotate_devices_with_snmp_profile(
            [{"id": "device-1", "vendor": "H3C", "platform": "h3c_comware", "model": "S6800"}]
        )[0]["snmp_metric_profile"]
        assert resolved["profile_id"] == created["id"]
        assert association["id"] == created["id"]
        assert association["status"] == "unverified"
    finally:
        invalidate_metric_profile_cache()
        conn.close()


def test_template_resolution_ignores_legacy_device_oids_without_an_applied_profile(monkeypatch) -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
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
    monkeypatch.setattr("services.snmp_metric_profile_service.get_db_connection", lambda: conn)
    invalidate_metric_profile_cache()
    try:
        resolved = resolve_health_metric_profiles(
            {
                "vendor": "H3C",
                "platform": "h3c_comware",
                "model": "S6800",
                "snmp_cpu_oid": "1.3.6.1.4.1.25506.99.1",
                "snmp_memory_oid": "1.3.6.1.4.1.25506.99.2",
            }
        )
    finally:
        invalidate_metric_profile_cache()
        conn.close()

    assert resolved["profile_source"] == "template_not_applied"
    assert resolved["metrics"] == {}
    assert resolved["metric_sources"]["cpu"] == "template_not_applied"
    assert resolved["metric_sources"]["memory"] == "template_not_applied"


def test_template_only_interface_collection_never_reads_default_if_mib(monkeypatch) -> None:
    requested: list[str] = []

    async def fail_bulk(*_args, **_kwargs):
        requested.append("bulk")
        raise AssertionError("template-only interface collection must not read default IF-MIB OIDs")

    monkeypatch.setattr("services.snmp_service._snmp_bulk_walk", fail_bulk)
    result = asyncio.run(
        collect_interface_data(
            "192.0.2.198",
            "public",
            161,
            None,
            template_only=True,
        )
    )

    assert requested == []
    assert result == []


def test_saved_profile_status_distinguishes_match_and_activation() -> None:
    assert _collector_status(False, "unverified", 3) == "template_required"
    assert _collector_status(True, "unverified", 3) == "active"
    assert _collector_status(True, "failed", 3) == "blocked_failed"
    assert _collector_status(True, "verified", 3) == "active"
    assert _collector_status(True, "verified", 0) == "no_matching_device"


def test_profile_mapping_uses_canonical_vendor_and_exact_model() -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
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
            platform TEXT, model TEXT, status TEXT,
            snmp_cpu_oid TEXT, snmp_memory_oid TEXT
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
             status, snmp_cpu_oid, snmp_memory_oid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("device-1", "core-sw-01", "192.0.2.10", "Cisco", "cisco_ios", "C9300-48P", "offline", "", ""),
            ("device-2", "other-vendor", "192.0.2.11", "H3C", "h3c_comware", "C9300-48P", "online", "", ""),
            ("device-3", "other-model", "192.0.2.12", "Cisco", "cisco_ios", "C9300-49P", "online", "", ""),
            ("device-4", "core-sw-04", "192.0.2.14", "Cisco", "cisco_ios", "C9300-48P", "online", "", ""),
        ],
    )

    mapping = get_model_metric_profile_mapping(conn, "profile-1")

    assert mapping["matched_device_count"] == 2
    assert mapping["sample_device_id"] == "device-4"
    assert mapping["sample_device_status"] == "online"
    assert mapping["same_model_other_vendor_count"] == 1
    assert mapping["collector_status"] == "active"
    assert mapping["devices"][0]["device_id"] == "device-4"
