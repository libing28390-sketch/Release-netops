from __future__ import annotations

import asyncio
from pathlib import Path

from services import librenms_rule_service as rules
from services import snmp_hardware_inventory_service as inventory
from services import snmp_hardware_probe_service as probe
from services.snmp_discovery_service import _merge_hardware_discovery


def _walk_from(mapping):
    async def walk(_ip, _community, oid, _port, _version):
        return list(mapping.get(oid, []))
    return walk


def test_discovery_merge_keeps_cpu_windows_separate_and_deduplicates_replays():
    cpu_1m = {
        "source_type": "librenms", "component_class": "processor",
        "measurement_type": "cpu_usage_percent", "index": [1],
        "metadata": {"window": "1m"},
    }
    cpu_5m = {
        "source_type": "librenms", "component_class": "processor",
        "measurement_type": "cpu_usage_percent", "index": [1],
        "metadata": {"window": "5m"},
    }

    merged = _merge_hardware_discovery(
        {"status": "no_supported_oid", "hardware_sensors": []},
        {"hardware_sensors": [cpu_1m]},
        {"hardware_sensors": [cpu_5m, dict(cpu_5m)]},
    )

    assert len(merged["hardware_sensors"]) == 2
    assert {sensor["metadata"]["window"] for sensor in merged["hardware_sensors"]} == {"1m", "5m"}


def test_standard_hardware_keeps_every_cpu_and_only_ram_storage_rows():
    oids = probe
    rows = {
        oids._HR_PROCESSOR_LOAD_OID: [("1", "21"), ("2", "47")],
        oids._HR_STORAGE_TYPE_OID: [
            ("6", oids._HR_STORAGE_RAM_TYPE),
            ("7", "1.3.6.1.2.1.25.2.1.3"),
        ],
        oids._HR_STORAGE_DESCR_OID: [("6", "Physical Memory"), ("7", "Swap Space")],
        oids._HR_STORAGE_UNITS_OID: [("6", "1024"), ("7", "1024")],
        oids._HR_STORAGE_SIZE_OID: [("6", "1048576"), ("7", "2048")],
        oids._HR_STORAGE_USED_OID: [("6", "524288"), ("7", "512")],
        oids._ENTITY_NAME_OID: [("1", "CPU 1"), ("2", "CPU 2"), ("6", "RAM"), ("10", "Chassis Temperature")],
        oids._ENTITY_CLASS_OID: [("10", "8")],
        oids._ENTITY_SENSOR_SCALE_OID: [("10", "9"), ("11", "9"), ("12", "9")],
        oids._ENTITY_SENSOR_PRECISION_OID: [("10", "1"), ("11", "1"), ("12", "0")],
        oids._ENTITY_SENSOR_VALUE_OID: [("10", "255"), ("11", "180"), ("12", "500")],
        oids._ENTITY_SENSOR_STATUS_OID: [("10", "1"), ("11", "3"), ("12", "1")],
        oids._ENTITY_SENSOR_TYPE_OID: [("10", "8"), ("11", "8"), ("12", "9")],
    }

    result = asyncio.run(probe.probe_standard_hardware(
        "192.0.2.1", "public", 161, walk_func=_walk_from(rows),
    ))

    cpu = [item for item in result["sensors"] if item["measurement_type"] == "cpu_usage_percent"]
    assert [item["index"] for item in cpu] == [[1], [2]]
    assert [item["value"] for item in cpu] == [21.0, 47.0]

    memory = [item for item in result["sensors"] if item["component_class"] == "memory_pool"]
    assert len(memory) == 3
    assert {item["measurement_type"] for item in memory} == {
        "memory_used_bytes", "memory_total_bytes", "memory_usage_percent",
    }
    assert all(item["index"] == [6] for item in memory)
    assert next(item for item in memory if item["measurement_type"] == "memory_usage_percent")["value"] == 50.0

    temperature = next(
        item for item in result["sensors"]
        if item["measurement_type"] == "temperature_celsius" and item["index"] == [10]
    )
    assert temperature["value"] == 25.5
    assert temperature["sensor_name"] == "Chassis Temperature"
    unavailable_temperature = next(
        item for item in result["sensors"]
        if item["measurement_type"] == "temperature_celsius" and item["index"] == [11]
    )
    assert unavailable_temperature["quality"] == "missing"
    assert unavailable_temperature["value"] is None
    assert not any(item["index"] == [12] for item in result["sensors"])
    environmental = next(
        item for item in result["category_results"]
        if item["component_class"] == "environmental_sensor"
    )
    assert environmental["status"] == "partial"


def test_entity_sensor_poll_uses_rfc_scale_and_precision_and_checks_sensor_type(monkeypatch):
    import database

    writes = []

    class Connection:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    connection = Connection()
    monkeypatch.setattr(database, "get_db_connection", lambda: connection)
    monkeypatch.setattr(
        inventory,
        "record_sensor_sample",
        lambda _conn, device_id, sensor_key, value, raw_value, quality, observed_at:
            writes.append((device_id, sensor_key, value, raw_value, quality)),
    )
    oids = probe
    rows = {
        oids._ENTITY_SENSOR_VALUE_OID: [("10", "425"), ("11", "500")],
        oids._ENTITY_SENSOR_TYPE_OID: [("10", "8"), ("11", "9")],
        oids._ENTITY_SENSOR_SCALE_OID: [("10", "9"), ("11", "9")],
        oids._ENTITY_SENSOR_PRECISION_OID: [("10", "1"), ("11", "0")],
        oids._ENTITY_SENSOR_STATUS_OID: [("10", "1"), ("11", "1")],
    }
    sensors = [
        {
            "device_id": "device-1", "sensor_key": "temperature-10",
            "component_class": "temperature", "measurement_type": "temperature_celsius",
            "index": [10], "states": {}, "metadata": {"poll_plan": {
                "kind": "entity_sensor", "index": "10", "expected_type": 8,
                "value_oid": oids._ENTITY_SENSOR_VALUE_OID,
                "type_oid": oids._ENTITY_SENSOR_TYPE_OID,
                "scale_oid": oids._ENTITY_SENSOR_SCALE_OID,
                "precision_oid": oids._ENTITY_SENSOR_PRECISION_OID,
                "status_oid": oids._ENTITY_SENSOR_STATUS_OID,
            }},
        },
        {
            "device_id": "device-1", "sensor_key": "temperature-11",
            "component_class": "temperature", "measurement_type": "temperature_celsius",
            "index": [11], "states": {}, "metadata": {"poll_plan": {
                "kind": "entity_sensor", "index": "11", "expected_type": 8,
                "value_oid": oids._ENTITY_SENSOR_VALUE_OID,
                "type_oid": oids._ENTITY_SENSOR_TYPE_OID,
                "scale_oid": oids._ENTITY_SENSOR_SCALE_OID,
                "precision_oid": oids._ENTITY_SENSOR_PRECISION_OID,
                "status_oid": oids._ENTITY_SENSOR_STATUS_OID,
            }},
        },
    ]

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.3", "public", 161, "2c", sensors, walk_func=_walk_from(rows),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 1}
    assert writes[0][2:] == (42.5, "425", "good")
    assert writes[1][2:] == (None, "500", "unsupported_mapping")


def test_librenms_state_generic_integer_codes_are_normalized():
    states = [
        {"value": 1, "descr": "active", "generic": 0},
        {"value": 2, "descr": "deactive", "generic": 2},
        {"value": 3, "descr": "not-install", "generic": 3},
    ]

    normal = probe._mapped_state("1", states)
    failed = probe._mapped_state("2", states)
    absent = probe._mapped_state("3", states)
    unsupported = probe._mapped_state("4", states)

    assert normal == (0.0, {"1": 0, "2": 2, "3": 3}, "good")
    assert failed == (2.0, {"1": 0, "2": 2, "3": 3}, "good")
    assert absent == (3.0, {"1": 0, "2": 2, "3": 3}, "good")
    assert unsupported == (None, {"1": 0, "2": 2, "3": 3}, "unsupported_mapping")


def test_librenms_probe_retains_all_rows_and_marks_unknown_cpu_window(monkeypatch):
    monkeypatch.setattr(probe, "get_db_connection", lambda: None)
    cpu_oid = "1.3.6.1.4.1.55555.1.1"
    temp_oid = "1.3.6.1.4.1.55555.2.1"
    rows = {
        cpu_oid: [("1", "10"), ("2", "35"), ("3", "60")],
        temp_oid: [("101", "42"), ("102", "43")],
        probe._ENTITY_NAME_OID: [("1", "CPU 1"), ("2", "CPU 2"), ("3", "CPU 3"), ("101", "Board 1"), ("102", "Board 2")],
    }
    rule = {
        "id": "librenms-example-test",
        "os_key": "example",
        "vendor": "Example",
        "source_commit": "abc123",
        "discovery_source_path": "resources/definitions/os_discovery/example.yaml",
        "hardware_definitions": {
            "processors": [{
                "source_module": "processors", "source_class": "processors",
                "component_class": "processor", "measurement_type": "cpu_usage",
                "numeric_oid_prefix": cpu_oid, "num_oid": cpu_oid,
                "raw": {"num_oid": cpu_oid, "window": "5 minutes"},
            }],
            "mempools": [],
            "sensors": [{
                "source_module": "sensors", "source_class": "temperature",
                "component_class": "temperature", "measurement_type": "temperature",
                "numeric_oid_prefix": temp_oid, "num_oid": temp_oid,
                "unit": "celsius", "raw": {"num_oid": temp_oid, "unit": "celsius"},
                "limits": {},
            }],
        },
    }

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.2", "public", 161, rule=rule,
        identity={"vendor": "Example"}, walk_func=_walk_from(rows),
    ))

    cpu = [item for item in result["sensors"] if item["measurement_type"] == "cpu_usage_percent"]
    assert len(cpu) == 3
    assert {item["metadata"]["window"] for item in cpu} == {"5m"}
    assert {item["value"] for item in cpu} == {10.0, 35.0, 60.0}
    temp = [item for item in result["sensors"] if item["measurement_type"] == "temperature_celsius"]
    assert len(temp) == 2
    assert {tuple(item["index"]) for item in temp} == {(101,), (102,)}
    assert all(item["quality"] == "good" for item in temp)
    assert all(item["coverage_complete"] for item in result["category_results"])


def test_vrp_fixture_executes_external_and_self_oid_skip_conditions(monkeypatch):
    import database

    fixture_root = Path(__file__).parent / "fixtures" / "librenms_rule_service"
    rule = next(item for item in rules.parse_rules(fixture_root) if item["os_key"] == "vrp")
    cpu_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5"
    status_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.99.1"
    threshold_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.99.2"
    used_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.6"
    free_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7"
    total_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.8"
    temperature_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.3.1.5"
    mode_oid = "1.3.6.1.4.1.2011.5.25.31.1.1.3.1.99"
    symbol_oids = {
        "hwEntityOperStatus": status_oid,
        "hwEntityCpuUsageThreshold": threshold_oid,
        "hwEntityMemoryUsage": used_oid,
        "hwEntityMemoryFree": free_oid,
        "hwEntityMemorySize": total_oid,
        "hwEntityOpticalTemperature": temperature_oid,
        "hwEntityOpticalMode": mode_oid,
    }
    walked = []
    rows = {
        cpu_oid: [("1", "34"), ("2", "50")],
        status_oid: [("1", "3"), ("2", "2")],
        threshold_oid: [("1", "10"), ("2", "10")],
        used_oid: [("1", "100")],
        free_oid: [("1", "900")],
        total_oid: [("1", "1000")],
        temperature_oid: [("1", "35"), ("2", "2147483646")],
        mode_oid: [("1", "2"), ("2", "1")],
    }

    class Connection:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(probe, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        probe, "_resolve_mib_symbol",
        lambda _conn, token, vendor="": symbol_oids.get(str(token).rsplit("::", 1)[-1], ""),
    )

    async def walk(_ip, _community, oid, _port, _version):
        walked.append(oid)
        return rows.get(oid, [])

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.10", "public", 161, rule=rule,
        identity={"vendor": "Huawei"}, walk_func=walk,
    ))

    cpu = [item for item in result["sensors"] if item["measurement_type"] == "cpu_usage_percent"]
    assert [(item["index"], item["value"]) for item in cpu] == [([1], 34.0)]
    temperature = [item for item in result["sensors"] if item["measurement_type"] == "temperature_celsius"]
    assert [(item["index"], item["value"]) for item in temperature] == [([1], 35.0)]
    assert {status_oid, threshold_oid, mode_oid}.issubset(set(walked))
    assert all(item["coverage_complete"] for item in result["category_results"])

    cpu_inventory = [
        {**item, "device_id": "device-vrp", "sensor_key": f"cpu-{item['index'][0]}",
         "lifecycle_status": "active", "enabled": True}
        for item in result["sensors"]
        if item["measurement_type"] == "cpu_usage_percent"
    ]
    samples = []
    monkeypatch.setattr(database, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        inventory, "record_sensor_sample",
        lambda _conn, device_id, sensor_key, value, raw, quality, _at:
            samples.append((device_id, sensor_key, value, raw, quality)),
    )
    # The running poll sees a changed operative state and must apply the same
    # external-OID filter used during discovery.
    rows[status_oid] = [("1", "2")]
    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.10", "public", 161, "2c", cpu_inventory, walk_func=walk,
    ))
    assert poll_result == {"good": 0, "missing": 1, "invalid": 0, "unsupported_mapping": 0}
    assert samples == [("device-vrp", "cpu-1", None, "34", "missing")]


def test_comware_fixture_maps_integer_state_codes_and_scalar_zero_skip(monkeypatch):
    fixture_root = Path(__file__).parent / "fixtures" / "librenms_rule_service"
    rule = next(item for item in rules.parse_rules(fixture_root) if item["os_key"] == "comware")
    fan_oid = "1.3.6.1.4.1.25506.8.35.9.1.1.1.2"
    power_oid = "1.3.6.1.4.1.25506.8.35.9.1.2.1.2"
    watts_oid = "1.3.6.1.4.1.25506.2.6.1.3.1.1.3"
    rows = {
        fan_oid: [("1", "1"), ("2", "2"), ("3", "3")],
        power_oid: [("1", "1"), ("2", "3")],
        watts_oid: [("1", "0"), ("2", "1500")],
    }

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(probe, "get_db_connection", lambda: Connection())

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.11", "public", 161, rule=rule,
        identity={"vendor": "H3C"}, walk_func=_walk_from(rows),
    ))

    fans = [item for item in result["sensors"] if item["component_class"] == "fan_state"]
    assert {tuple(item["index"]): item["value"] for item in fans} == {
        (1,): 0.0, (2,): 2.0, (3,): 3.0,
    }
    assert next(item for item in fans if item["index"] == [3])["presence_status"] == "not_present"
    watts = [item for item in result["sensors"] if item["measurement_type"] == "power_watts"]
    assert [(item["index"], item["value"]) for item in watts] == [([2], 1.5)]


def test_skip_value_supports_librenms_string_regex_exists_and_index_operators():
    cases = [
        ({"op": "starts", "value": "Jun"}, "Juniper", True),
        ({"op": "not_starts", "value": "Cisco"}, "Juniper", True),
        ({"op": "ends", "value": "os"}, "Junos", True),
        ({"op": "not_ends", "value": ".257"}, "sensor.258", True),
        ({"op": "contains", "value": "Board"}, "Main Board", True),
        ({"op": "not_contains", "value": "fan"}, "Main Board", True),
        ({"op": "regex", "value": r"/^8\.7\.[4-6]\./"}, "8.7.5.1", True),
        ({"op": "not_regex", "value": r"/^8\.7\.[4-6]\./"}, "8.7.3.1", True),
        ({"op": "exists", "value": False, "_oid": "condition"}, None, True),
        ({"op": "exists", "value": True, "_oid": "condition"}, "present", True),
    ]

    for condition, raw_value, expected in cases:
        condition_values = {"condition": raw_value} if "_oid" in condition else None
        assert probe._skip_value(raw_value, [condition], condition_values=condition_values) is expected

    indexed = [{"op": "not_ends", "value": ".257", "_oid": "__index__", "_index": True}]
    indexed_values, complete = probe._condition_values_at_index(
        indexed, suffix="1.258", raw_value="10", rows_by_oid={},
    )
    assert complete
    assert probe._skip_value("10", indexed, condition_values=indexed_values) is True


def test_skip_values_resolve_librenms_device_hardware_and_version_from_identity():
    hardware_conditions, hardware_oids, hardware_supported = probe._compile_skip_conditions(
        [{"device": "hardware", "op": "not_starts", "value": "AP7"}],
        db_conn=None,
        vendor="Ubiquiti",
        identity={"model": "AP7-Outdoor"},
    )
    assert hardware_oids == set()
    assert hardware_supported
    assert probe._skip_value("42", hardware_conditions) is False
    other_hardware_conditions, _other_hardware_oids, other_hardware_supported = probe._compile_skip_conditions(
        [{"device": "hardware", "op": "not_starts", "value": "AP7"}],
        db_conn=None,
        vendor="Ubiquiti",
        identity={"model": "UDM-Pro"},
    )
    assert other_hardware_supported
    assert probe._skip_value("42", other_hardware_conditions) is True

    version_conditions, version_oids, version_supported = probe._compile_skip_conditions(
        [{"device": "version", "op": "regex", "value": r"/^8\.7\.[4-6]\./"}],
        db_conn=None,
        vendor="Ubiquiti",
        identity={"software_version": "8.7.5.1"},
    )
    assert version_oids == set()
    assert version_supported
    assert probe._skip_value("41", version_conditions) is True

    missing_identity, _missing_oids, missing_supported = probe._compile_skip_conditions(
        [{"device": "version", "op": "regex", "value": r"/^8\.7\./"}],
        db_conn=None,
        vendor="Ubiquiti",
        identity={},
    )
    assert not missing_supported
    assert probe._skip_value("41", missing_identity) is None


def test_librenms_device_version_filter_is_snapshotted_into_poll_plan(monkeypatch):
    monkeypatch.setattr(probe, "get_db_connection", lambda: None)
    temp_oid = "1.3.6.1.4.1.55555.7.1"
    rule = {
        "id": "librenms-device-version-test", "os_key": "airos", "vendor": "Ubiquiti",
        "hardware_definitions": {
            "processors": [], "mempools": [],
            "sensors": [{
                "source_module": "sensors", "source_class": "temperature",
                "component_class": "temperature", "measurement_type": "temperature",
                "numeric_oid_prefix": temp_oid, "unit": "celsius",
                "skip_values": [{
                    "device": "version", "op": "regex", "value": r"/^8\.7\.[4-6]\./",
                }],
                "raw": {"num_oid": temp_oid, "unit": "celsius"}, "limits": {},
            }],
        },
    }

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.14", "public", 161, rule=rule,
        identity={"vendor": "Ubiquiti", "software_version": "8.7.7.1"},
        walk_func=_walk_from({temp_oid: [("1", "42")]}),
    ))

    sensor = next(item for item in result["sensors"] if item["component_class"] == "temperature")
    assert sensor["value"] == 42.0
    assert sensor["quality"] == "good"
    condition = sensor["metadata"]["poll_plan"]["skip_values"][0]
    assert condition["device"] == "version"
    assert condition["_device_value"] == "8.7.7.1"
    assert sensor["metadata"]["poll_plan"]["skip_conditions_supported"] is True


def test_unifi_mempool_with_missing_frogfoot_mib_is_explicitly_unsupported(monkeypatch):
    monkeypatch.setattr(probe, "get_db_connection", lambda: None)
    source = rules.source_root() / "resources/definitions/os_discovery/unifi.yaml"
    definition, diagnostics = rules._load_yaml_result(source)
    assert not diagnostics
    hardware = rules._parse_hardware_definitions(definition, source_path="unifi.yaml")
    assert hardware["mempools"][0]["memory"]["total_oid"] == "FROGFOOT-RESOURCES-MIB::memTotal"
    assert hardware["mempools"][0]["memory"]["free_oid"] == "FROGFOOT-RESOURCES-MIB::memFree"

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.21", "public", 161,
        rule={"id": "unifi", "os_key": "unifi", "vendor": "Ubiquiti", "hardware_definitions": hardware},
        identity={"vendor": "Ubiquiti"},
        walk_func=_walk_from({}),
    ))

    assert result["sensors"] == []
    memory = next(item for item in result["category_results"] if item["component_class"] == "memory_pool")
    assert memory["status"] == "unsupported"
    assert memory["reason_code"] == "unsupported_definition"


def test_librenms_skip_conditions_handle_missing_rows_and_fixed_oid_indexes(monkeypatch):
    temp_oid = "1.3.6.1.4.1.55555.1.1"
    voltage_oid = "1.3.6.1.4.1.55555.2.1"
    status_oid = "1.3.6.1.4.1.55555.3.1"
    flag_oid = "1.3.6.1.4.1.55555.4.1"
    symbols = {
        "statusColumn": status_oid,
        "scalarFlag": flag_oid,
    }
    monkeypatch.setattr(probe, "get_db_connection", lambda: None)
    monkeypatch.setattr(
        probe, "_resolve_mib_symbol",
        lambda _conn, token, vendor="": symbols.get(str(token).rsplit("::", 1)[-1], ""),
    )
    rows = {
        temp_oid: [("1", "35"), ("2", "36")],
        status_oid: [("1", "1")],
        voltage_oid: [("1", "12"), ("2", "13")],
        flag_oid: [("0", "2")],
    }
    rule = {
        "id": "librenms-skip-semantics-test",
        "os_key": "example",
        "vendor": "Example",
        "hardware_definitions": {
            "processors": [], "mempools": [],
            "sensors": [
                {
                    "source_module": "sensors", "source_class": "temperature",
                    "component_class": "temperature", "measurement_type": "temperature",
                    "numeric_oid_prefix": temp_oid, "unit": "celsius",
                    "skip_values": [{"oid": "EXAMPLE-MIB::statusColumn", "op": "exists", "value": False}],
                    "raw": {"num_oid": temp_oid, "unit": "celsius"}, "limits": {},
                },
                {
                    "source_module": "sensors", "source_class": "voltage",
                    "component_class": "voltage", "measurement_type": "voltage",
                    "numeric_oid_prefix": voltage_oid, "unit": "volts",
                    "skip_values": [{"oid": "EXAMPLE-MIB::scalarFlag.0", "op": "!=", "value": 1}],
                    "raw": {"num_oid": voltage_oid, "unit": "volts"}, "limits": {},
                },
            ],
        },
    }

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.12", "public", 161, rule=rule,
        identity={"vendor": "Example"}, walk_func=_walk_from(rows),
    ))

    temperatures = [item for item in result["sensors"] if item["measurement_type"] == "temperature_celsius"]
    assert [(item["index"], item["value"]) for item in temperatures] == [([1], 35.0)]
    assert not any(item["measurement_type"] == "voltage_volts" for item in result["sensors"])
    assert all(item["quality"] == "good" for item in temperatures)
    temperature_category = next(
        item for item in result["category_results"]
        if item["component_class"] == "temperature"
    )
    assert temperature_category["coverage_complete"]


def test_unimplemented_librenms_user_func_never_exports_raw_as_canonical(monkeypatch):
    import database

    temp_oid = "1.3.6.1.4.1.55555.5.1"
    rule = {
        "id": "librenms-user-func-test", "os_key": "example", "vendor": "Example",
        "hardware_definitions": {
            "processors": [], "mempools": [],
            "sensors": [{
                "source_module": "sensors", "source_class": "temperature",
                "component_class": "temperature", "measurement_type": "temperature",
                "numeric_oid_prefix": temp_oid, "unit": "celsius",
                "user_func": "example_vendor_transform",
                "raw": {"num_oid": temp_oid, "unit": "celsius", "user_func": "example_vendor_transform"},
                "limits": {},
            }],
        },
    }
    rows = {temp_oid: [("1", "86")]}
    monkeypatch.setattr(probe, "get_db_connection", lambda: None)

    discovered = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.13", "public", 161, rule=rule,
        identity={"vendor": "Example"}, walk_func=_walk_from(rows),
    ))
    sensor = next(item for item in discovered["sensors"] if item["component_class"] == "temperature")
    assert sensor["value"] is None
    assert sensor["quality"] == "unsupported_mapping"
    assert sensor["metadata"]["poll_plan"]["transform_supported"] is False

    writes = []

    class Connection:
        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(database, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        inventory, "record_sensor_sample",
        lambda _conn, _device_id, _sensor_key, value, raw, quality, _at:
            writes.append((value, raw, quality)),
    )
    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.13", "public", 161, "2c",
        [{**sensor, "device_id": "device-user-func", "lifecycle_status": "active", "enabled": True}],
        walk_func=_walk_from(rows),
    ))
    assert poll_result == {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 1}
    assert writes == [(None, "86", "unsupported_mapping")]
