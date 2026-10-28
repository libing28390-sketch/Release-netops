from __future__ import annotations

import asyncio
import json
from pathlib import Path

from services import librenms_rule_service as rules
from services import librenms_source_policy as source_policy
from services import snmp_hardware_inventory_service as inventory
from services import snmp_hardware_probe_service as probe
from services import snmp_service


def _walk_from(mapping):
    async def walk(_ip, _community, oid, _port, _version):
        return list(mapping.get(oid, []))
    return walk


def _accept_fixture_rule(monkeypatch):
    """Isolate rule-execution tests from the production provenance gate."""
    monkeypatch.setattr(probe, "verify_bundled_rule", lambda _rule: True)
    monkeypatch.setattr(probe, "_pinned_hardware_definition_matches", lambda _rule: True)


def test_unverified_librenms_rule_fails_before_device_reads(monkeypatch):
    walked = []
    monkeypatch.setattr(probe, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")))

    async def walk(*args):
        walked.append(args)
        return []

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.50", "test-only-community", 161,
        rule={
            "id": "unverified", "os_key": "example", "vendor": "Example",
            "source_commit": "untrusted", "source_path": "custom.yaml",
            "discovery_source_path": "custom.yaml",
            "hardware_definitions": {"processors": [], "mempools": [], "sensors": []},
        },
        identity={"vendor": "Example"}, walk_func=walk,
    ))

    assert result["sensors"] == []
    assert result["category_results"] == [{
        "source_type": "librenms_rule", "component_class": "source",
        "status": "unsupported", "coverage_complete": False,
        "reason_code": "unverified_librenms_rule",
        "reason": "The OS rule source or parsed hardware definitions do not match the pinned LibreNMS bundle.",
    }]
    assert walked == []


def test_verified_rule_without_supported_yaml_definitions_fails_closed(monkeypatch):
    _accept_fixture_rule(monkeypatch)
    walked = []
    monkeypatch.setattr(
        probe,
        "get_db_connection",
        lambda: (_ for _ in ()).throw(AssertionError("database must not be opened")),
    )

    async def walk(*args):
        walked.append(args)
        return []

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.53", "test-only-community", 161,
        rule={
            "id": "unsupported-method-only", "os_key": "example", "vendor": "Example",
            "hardware_definitions": {"processors": [], "mempools": [], "sensors": []},
        },
        identity={"vendor": "Example"}, walk_func=walk,
    ))

    assert result["sensors"] == []
    assert result["category_results"] == [{
        "source_type": "librenms_rule", "component_class": "source",
        "status": "unsupported", "coverage_complete": False,
        "reason_code": "unsupported_librenms_rule",
        "reason": "The pinned LibreNMS YAML rule has no hardware definitions supported by this executor.",
    }]
    assert walked == []


def test_hardware_definition_payload_must_match_pinned_yaml():
    os_key = "vrp"
    source_path = f"resources/definitions/os_discovery/{os_key}.yaml"
    discovery, diagnostics = rules._load_yaml_result(
        source_policy.LIBRENMS_BUNDLE_ROOT / source_path,
    )
    hardware = rules._parse_hardware_definitions(discovery, source_path=source_path)
    if diagnostics:
        hardware["compatibility"]["diagnostics"].extend(diagnostics)
        source_errors = [
            item for item in diagnostics
            if item.get("code") != "yaml_recovered_upstream_format"
        ]
        if source_errors and hardware["compatibility"]["level"] == "supported":
            hardware["compatibility"]["level"] = "partial"
    rule = {"os_key": os_key, "hardware_definitions": hardware}

    assert probe._pinned_hardware_definition_matches(rule)
    changed = json.loads(json.dumps(hardware))
    changed["processors"][0]["num_oid"] = "1.3.6.1.4.1.55555.99.{{ $index }}"
    assert not probe._pinned_hardware_definition_matches({
        "os_key": os_key, "hardware_definitions": changed,
    })


def test_definition_oid_prefers_explicit_value_and_fails_closed(monkeypatch):
    resolved_symbols = {"TEST-MIB::sampleValue": "1.3.6.1.4.1.55555.9.1"}
    seen = []

    def resolve(_conn, token, *, vendor="", cache=None):
        seen.append(str(token))
        return resolved_symbols.get(str(token), "")

    monkeypatch.setattr(probe, "_resolve_mib_symbol", resolve)
    assert probe._resolve_definition_oid(
        None,
        {"value_oid": "TEST-MIB::sampleValue", "num_oid": "1.3.6.1.4.1.55555.1"},
        vendor="Example",
    ) == "1.3.6.1.4.1.55555.9.1"
    assert seen == ["TEST-MIB::sampleValue"]

    assert probe._resolve_definition_oid(
        None,
        {"value_oid": "UNKNOWN-MIB::missing", "num_oid": "1.3.6.1.4.1.55555.1", "table_oid": "1.3.6.1.4.1.55555.2"},
        vendor="Example",
    ) == ""
    assert probe._resolve_definition_oid(
        None,
        {"num_oid": "1.3.6.1.4.1.55555.1"},
        vendor="Example",
    ) == "1.3.6.1.4.1.55555.1"


def test_symbol_resolution_requires_a_verified_pinned_librenms_mib(monkeypatch):
    expected_path = "h3c/_upstream/comware/HH3C-DOT11-ACMT-MIB"
    expected_hash = "a" * 64
    queries = []

    class Result:
        def fetchall(self):
            return [
                ("1.3.6.1.4.1.25506.2.75.1.1.2.21", expected_path, expected_hash),
                ("1.3.6.1.4.1.99999.1", "untrusted/HH3C-DOT11-ACMT-MIB", "b" * 64),
            ]

    class Connection:
        def execute(self, query, params):
            queries.append((query, params))
            return Result()

    verified = []

    def verify(**kwargs):
        verified.append(kwargs)
        return [object()] if (
            kwargs.get("module_name") == "HH3C-DOT11-ACMT-MIB"
            and kwargs.get("relative_path") == expected_path
            and kwargs.get("sha256") == expected_hash
        ) else []

    monkeypatch.setattr(probe, "verified_librenms_mib_source_entries", verify)
    resolved = probe._resolve_mib_symbol(
        Connection(), "HH3C-DOT11-ACMT-MIB::hh3cDot11TotalAPconnected", vendor="H3C",
    )

    assert resolved == "1.3.6.1.4.1.25506.2.75.1.1.2.21"
    assert "m.source_type = 'librenms'" in queries[0][0]
    assert "m.source_commit = ?" in queries[0][0]
    assert verified == [
        {
            "module_name": "HH3C-DOT11-ACMT-MIB",
            "relative_path": expected_path,
            "sha256": expected_hash,
        },
        {
            "module_name": "HH3C-DOT11-ACMT-MIB",
            "relative_path": "untrusted/HH3C-DOT11-ACMT-MIB",
            "sha256": "b" * 64,
        },
    ]


def test_unqualified_symbol_with_conflicting_verified_oids_fails_closed(monkeypatch):
    class Result:
        def fetchall(self):
            return [
                ("1.3.6.1.4.1.1", "h3c/_upstream/mib-a", "a" * 64),
                ("1.3.6.1.4.1.2", "huawei/_upstream/mib-b", "b" * 64),
            ]

    class Connection:
        def execute(self, _query, _params):
            return Result()

    monkeypatch.setattr(probe, "verified_librenms_mib_source_entries", lambda **_kwargs: [object()])
    assert probe._resolve_mib_symbol(Connection(), "ambiguousSymbol", vendor="H3C") == ""


def test_entity_physical_name_template_resolves_full_module_symbol(monkeypatch):
    _accept_fixture_rule(monkeypatch)
    sensor_oid = "1.3.6.1.4.1.55555.11.1"
    entity_name_oid = probe._ENTITY_NAME_OID
    requested_symbols = []

    class Connection:
        def close(self):
            pass

    def resolve(_conn, token, *, vendor="", cache=None):
        requested_symbols.append(str(token))
        return entity_name_oid if str(token) == "ENTITY-MIB::entPhysicalName" else ""

    monkeypatch.setattr(probe, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(probe, "_resolve_mib_symbol", resolve)
    rule = {
        "id": "entity-name-template", "os_key": "example", "vendor": "Example",
        "hardware_definitions": {
            "processors": [], "mempools": [],
            "sensors": [{
                "source_module": "sensors", "source_class": "temperature",
                "component_class": "temperature", "measurement_type": "temperature",
                "numeric_oid_prefix": sensor_oid, "num_oid": sensor_oid,
                "unit": "celsius", "descr": "{{ ENTITY-MIB::entPhysicalName:2 }} {{ $subindex1 }}",
                "raw": {"num_oid": sensor_oid, "unit": "celsius"}, "limits": {},
            }],
        },
    }
    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.51", "test-only-community", 161, rule=rule,
        identity={"vendor": "Example"},
        walk_func=_walk_from({
            sensor_oid: [("1.2", "41")],
            entity_name_oid: [("1", "Chassis"), ("2", "Line card")],
        }),
    ))

    assert "ENTITY-MIB::entPhysicalName" in requested_symbols
    assert next(item for item in result["sensors"] if item["component_class"] == "temperature")["sensor_name"] == "Line card 2"






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

    nested = probe._mapped_state("5", {"5": {"generic": "ok", "descr": "run"}})
    assert nested == (0.0, {"5": 0}, "good")


def test_librenms_probe_retains_all_rows_and_marks_unknown_cpu_window(monkeypatch):
    _accept_fixture_rule(monkeypatch)
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
        "192.0.2.2", "test-only-community", 161, rule=rule,
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
    assert all(item["source_type"] == "librenms_rule" for item in [*cpu, *temp])
    assert {item["source_type"] for item in result["category_results"]} == {"librenms_rule"}
    assert all(item["coverage_complete"] for item in result["category_results"])


def test_vrp_fixture_executes_external_and_self_oid_skip_conditions(monkeypatch):
    import database

    _accept_fixture_rule(monkeypatch)
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
        "hwEntityCpuUsage": cpu_oid,
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
        lambda _conn, token, vendor="", cache=None: symbol_oids.get(str(token).rsplit("::", 1)[-1], ""),
    )

    async def walk(_ip, _community, oid, _port, _version):
        walked.append(oid)
        return rows.get(oid, [])

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.10", "test-only-community", 161, rule=rule,
        identity={"vendor": "Huawei"}, walk_func=walk,
    ))

    cpu = [item for item in result["sensors"] if item["measurement_type"] == "cpu_usage_percent"]
    assert [(item["index"], item["value"]) for item in cpu] == [([1], 34.0)]
    temperature = [item for item in result["sensors"] if item["measurement_type"] == "temperature_celsius"]
    assert [(item["index"], item["value"]) for item in temperature] == [([1], 35.0)]
    assert {status_oid, threshold_oid, mode_oid}.issubset(set(walked))
    cpu_inventory = [
        {**item, "device_id": "device-vrp", "sensor_key": f"cpu-{item['index'][0]}",
         "lifecycle_status": "active", "enabled": True}
        for item in result["sensors"]
        if item["measurement_type"] == "cpu_usage_percent"
    ]
    samples = []
    monkeypatch.setattr(database.core, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        inventory, "record_sensor_samples_batch",
        lambda _conn, batch: samples.extend(
            (sample["device_id"], sample["sensor_key"], sample["value"],
             sample["raw_value"], sample["quality"])
            for sample in batch
        ),
    )
    # The running poll sees a changed operative state and must apply the same
    # external-OID filter used during discovery.
    rows[status_oid] = [("1", "2")]
    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.10", "test-only-community", 161, "2c", cpu_inventory, walk_func=walk,
    ))
    assert poll_result == {"good": 0, "missing": 1, "invalid": 0, "unsupported_mapping": 0}
    assert samples == [("device-vrp", "cpu-1", None, "34", "missing")]


def test_comware_fixture_maps_integer_state_codes_and_scalar_zero_skip(monkeypatch):
    _accept_fixture_rule(monkeypatch)
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
    symbol_oids = {
        "hh3cDevMFanStatus": fan_oid,
        "hh3cDevMPowerStatus": power_oid,
        "hh3cEntityExtCurrentPower": watts_oid,
    }
    monkeypatch.setattr(
        probe, "_resolve_mib_symbol",
        lambda _conn, token, vendor="", cache=None: symbol_oids.get(str(token).rsplit("::", 1)[-1], ""),
    )

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.11", "test-only-community", 161, rule=rule,
        identity={"vendor": "H3C"}, walk_func=_walk_from(rows),
    ))

    fans = [item for item in result["sensors"] if item["component_class"] == "fan_state"]
    assert {tuple(item["index"]): item["value"] for item in fans} == {
        (1,): 0.0, (2,): 2.0, (3,): 3.0,
    }
    assert next(item for item in fans if item["index"] == [3])["presence_status"] == "not_present"
    watts = [item for item in result["sensors"] if item["measurement_type"] == "power_watts"]
    assert [(item["index"], item["value"]) for item in watts] == [([2], 1.5)]








def test_mempool_values_match_librenms_percent_only_and_overflow_normalization():
    assert probe._mempool_targets({"percent_used": {"kind": "oid"}}) == {
        "used", "total", "percent_used",
    }
    values = probe._mempool_metric_values(
        {"percent_used": "150"}, factor=1.0, offset=0.0,
        precision=1.0, unit_factor=1.0,
    )
    assert values == {"used": 15.0, "total": 100.0, "percent_used": 15.0}

    fractional = probe._mempool_metric_values(
        {"percent_used": "50.237"}, factor=1.0, offset=0.0,
        precision=1.0, unit_factor=1.0,
    )
    assert fractional == {"used": 50.24, "total": 100.0, "percent_used": 50.0}






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
    _accept_fixture_rule(monkeypatch)
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
        "192.0.2.14", "test-only-community", 161, rule=rule,
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
    _accept_fixture_rule(monkeypatch)
    monkeypatch.setattr(probe, "get_db_connection", lambda: None)
    monkeypatch.setattr(probe, "_get_many", lambda *_args: asyncio.sleep(0, result={}))
    source = rules.source_root() / "resources/definitions/os_discovery/unifi.yaml"
    definition, diagnostics = rules._load_yaml_result(source)
    assert not diagnostics
    hardware = rules._parse_hardware_definitions(definition, source_path="unifi.yaml")
    assert hardware["mempools"][0]["memory"]["total_oid"] == "FROGFOOT-RESOURCES-MIB::memTotal"
    assert hardware["mempools"][0]["memory"]["free_oid"] == "FROGFOOT-RESOURCES-MIB::memFree"

    result = asyncio.run(probe.probe_librenms_hardware(
        "192.0.2.21", "test-only-community", 161,
        rule={"id": "unifi", "os_key": "unifi", "vendor": "Ubiquiti", "hardware_definitions": hardware},
        identity={"vendor": "Ubiquiti"},
        walk_func=_walk_from({}),
    ))

    assert result["sensors"] == []
    assert {item["source_type"] for item in result["category_results"]} == {"librenms_rule"}
    memory = next(item for item in result["category_results"] if item["component_class"] == "memory_pool")
    assert memory["status"] == "unsupported"
    assert memory["reason_code"] == "unsupported_definition"


def test_librenms_skip_conditions_handle_missing_rows_and_fixed_oid_indexes(monkeypatch):
    _accept_fixture_rule(monkeypatch)
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
        lambda _conn, token, vendor="", cache=None: symbols.get(str(token).rsplit("::", 1)[-1], ""),
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
        "192.0.2.12", "test-only-community", 161, rule=rule,
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

    _accept_fixture_rule(monkeypatch)
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
        "192.0.2.13", "test-only-community", 161, rule=rule,
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

    monkeypatch.setattr(database.core, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        inventory, "record_sensor_samples_batch",
        lambda _conn, batch: writes.extend(
            (sample["value"], sample["raw_value"], sample["quality"])
            for sample in batch
        ),
    )
    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.13", "test-only-community", 161, "2c",
        [{**sensor, "device_id": "device-user-func", "lifecycle_status": "active", "enabled": True}],
        walk_func=_walk_from(rows),
    ))
    assert poll_result == {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 1}
    assert writes == [(None, "86", "unsupported_mapping")]


def test_poll_batches_exact_instance_oids_without_table_walks(monkeypatch):
    base_oid = "1.3.6.1.4.1.55555.20.1"
    requested_batches = []
    persisted = []

    async def get_many(_ip, _community, oids, _port, _version):
        requested_batches.append(list(oids))
        return {oid: "420" for oid in oids}

    monkeypatch.setattr(snmp_service, "_snmp_get_many_versioned", get_many)
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))
    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.52", "test-only-community", 161, "2c",
        [{
            "device_id": "device-get-batch", "sensor_key": "temperature-17",
            "measurement_type": "temperature_celsius", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "direct", "oid": base_oid, "index": "17",
                "factor": 0.1, "offset": 0.0,
            }},
        }],
    ))

    assert requested_batches == [[f"{base_oid}.17"]]
    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["raw_value"] == "420"
    assert persisted[0]["value"] == 42.0


def test_poll_table_sum_records_zero_for_a_complete_empty_table(monkeypatch):
    oid = "1.3.6.1.4.1.55555.41"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.54", "test-only-community", 161, "2c",
        [{
            "device_id": "device-empty-table-sum", "sensor_key": "wireless-client-total",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_sum", "oid": oid}},
        }],
        walk_func=_walk_from({oid: []}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] == 0.0
    assert persisted[0]["quality"] == "good"


def test_poll_table_count_records_complete_table_row_count(monkeypatch):
    oid = "1.3.6.1.4.1.55555.48"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.58", "test-only-community", 161, "2c",
        [{
            "device_id": "device-table-count", "sensor_key": "wireless-client-count",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_count", "oid": oid}},
        }],
        walk_func=_walk_from({oid: [("1", "12"), ("2", "7"), ("3", "0")]}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] == 3.0
    assert persisted[0]["raw_value"] == "3"
    assert persisted[0]["quality"] == "good"


def test_poll_table_count_records_zero_for_complete_empty_table(monkeypatch):
    oid = "1.3.6.1.4.1.55555.49"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.59", "test-only-community", 161, "2c",
        [{
            "device_id": "device-empty-table-count", "sensor_key": "wireless-client-count-empty",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_count", "oid": oid}},
        }],
        walk_func=_walk_from({oid: []}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] == 0.0
    assert persisted[0]["raw_value"] == "0"


def test_poll_table_count_marks_incomplete_walk_missing(monkeypatch):
    oid = "1.3.6.1.4.1.55555.50"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    class PartialWalkError(Exception):
        partial_results = [("1", "15")]

    async def partial_walk(_ip, _community, requested_oid, _port, _version):
        assert requested_oid == oid
        raise PartialWalkError("incomplete table")

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.60", "test-only-community", 161, "2c",
        [{
            "device_id": "device-partial-table-count", "sensor_key": "wireless-client-count-partial",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_count", "oid": oid}},
        }],
        walk_func=partial_walk,
    ))

    assert result == {"good": 0, "missing": 1, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] is None
    assert persisted[0]["quality"] == "missing"


def test_poll_table_value_applies_offset_and_uses_fallback_only_after_complete_walk(monkeypatch):
    oid = "1.3.6.1.4.1.55555.52"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))
    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.62", "test-only-community", 161, "2c",
        [
            {
                "device_id": "device-table-value", "sensor_key": "wireless-interference-present",
                "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
                "enabled": True,
                "metadata": {"poll_plan": {
                    "kind": "table_value", "oid": oid, "index": "1.1.36",
                    "offset": 128.0, "fallback_value": -128.0,
                }},
            },
            {
                "device_id": "device-table-value", "sensor_key": "wireless-interference-absent",
                "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
                "enabled": True,
                "metadata": {"poll_plan": {
                    "kind": "table_value", "oid": oid, "index": "1.1.44",
                    "offset": 128.0, "fallback_value": -128.0,
                }},
            },
        ],
        walk_func=_walk_from({oid: [("1.1.36", "-80")]}),
    ))

    assert result == {"good": 2, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert sorted(sample["value"] for sample in persisted) == [0.0, 48.0]
    assert all(sample["quality"] == "good" for sample in persisted)


def test_poll_wireless_channel_transforms_keep_frequency_units_and_limits(monkeypatch):
    observations = {
        "1.3.6.1.4.1.55555.61": "36",
        "1.3.6.1.4.1.55555.62": "116e",
        "1.3.6.1.4.1.55555.63": "1150",
    }
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.62", "test-only-community", 161, "2c",
        [{
            "device_id": "wireless-transform-device",
            "sensor_key": f"wireless-transform-{index}",
            "measurement_type": "wireless_sensor_value",
            "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "direct", "oid": oid, "index": "1",
                "value_transform": transform, "factor": factor,
                "value_max": value_max,
            }},
        } for index, (oid, transform, factor, value_max) in enumerate((
            ("1.3.6.1.4.1.55555.61", "channel_to_frequency", 1.0, None),
            ("1.3.6.1.4.1.55555.62", "aruba_instant_channel_to_frequency", 1.0, None),
            ("1.3.6.1.4.1.55555.63", "", 0.1, 100.0),
        ))],
        walk_func=_walk_from({
            oid: [("1", raw)] for oid, raw in observations.items()
        }),
    ))

    assert result == {"good": 3, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert sorted(sample["value"] for sample in persisted) == [100.0, 5180.0, 5580.0]


def test_poll_table_group_sum_filters_labels_and_applies_factor(monkeypatch):
    value_oid = "1.3.6.1.4.1.55555.42"
    ssid_oid = "1.3.6.1.4.1.55555.43"
    radio_oid = "1.3.6.1.4.1.55555.44"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))
    rows = {
        value_oid: [("1.1", "30"), ("1.2", "40"), ("2.1", "100")],
        ssid_oid: [("1.1", "Corp"), ("1.2", "Corp"), ("2.1", "Guest")],
        radio_oid: [("1.1", "radio0"), ("1.2", "radio0"), ("2.1", "radio0")],
    }

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.55", "test-only-community", 161, "2c",
        [{
            "device_id": "device-group-table-sum", "sensor_key": "wireless-client-total-corp-radio0",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "table_group_sum", "oid": value_oid,
                "label_oids": {"ssid": ssid_oid, "radio": radio_oid},
                "group_labels": {"ssid": "Corp", "radio": "radio0"},
                "factor": 0.1,
            }},
        }],
        walk_func=_walk_from(rows),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] == 7.0
    assert persisted[0]["raw_value"] == "70.0"


def test_poll_table_multi_sum_joins_same_index_and_sums_all_tables(monkeypatch):
    clients_2g_oid = "1.3.6.1.4.1.55555.47"
    clients_5g_oid = "1.3.6.1.4.1.55555.48"
    corp_index = "4.67.111.114.112"
    only_2g_index = "6.79.110.108.121.50"
    only_5g_index = "5.79.110.108.121"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    def sensor(sensor_key, index):
        return {
            "device_id": "device-huawei-multi-table-sum",
            "sensor_key": sensor_key,
            "measurement_type": "wireless_sensor_value",
            "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "table_multi_sum",
                "oids": [clients_2g_oid, clients_5g_oid],
                "index": index,
            }},
        }

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.57", "test-only-community", 161, "2c",
        [
            sensor("huawei-corp-all-bands", corp_index),
            sensor("huawei-only-2g", only_2g_index),
            sensor("huawei-only-5g", only_5g_index),
            sensor("huawei-total-clients", ""),
        ],
        walk_func=_walk_from({
            clients_2g_oid: [(corp_index, "4"), (only_2g_index, "2")],
            clients_5g_oid: [(corp_index, "3"), (only_5g_index, "5")],
        }),
    ))

    assert result == {"good": 4, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    samples = {sample["sensor_key"]: sample for sample in persisted}
    assert samples["huawei-corp-all-bands"]["value"] == 7.0
    assert samples["huawei-only-2g"]["value"] == 2.0
    assert samples["huawei-only-5g"]["value"] == 5.0
    assert samples["huawei-total-clients"]["value"] == 14.0
    assert all(sample["quality"] == "good" for sample in samples.values())


def test_poll_table_multi_sum_requires_complete_walks_from_every_source(monkeypatch):
    clients_2g_oid = "1.3.6.1.4.1.55555.49"
    clients_5g_oid = "1.3.6.1.4.1.55555.50"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    async def partial_walk(_ip, _community, oid, _port, _version):
        if oid == clients_2g_oid:
            return [("4.67.111.114.112", "4")]
        raise TimeoutError("5 GHz table walk incomplete")

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.57", "test-only-community", 161, "2c",
        [{
            "device_id": "device-huawei-partial-multi-table-sum",
            "sensor_key": "huawei-corp-partial",
            "measurement_type": "wireless_sensor_value",
            "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "table_multi_sum",
                "oids": [clients_2g_oid, clients_5g_oid],
                "index": "4.67.111.114.112",
            }},
        }],
        walk_func=partial_walk,
    ))

    assert result == {"good": 0, "missing": 1, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] is None
    assert persisted[0]["raw_value"] is None
    assert persisted[0]["quality"] == "missing"


def test_poll_table_group_sum_falls_back_to_row_suffix_when_label_row_is_missing(monkeypatch):
    value_oid = "1.3.6.1.4.1.55555.45"
    label_oid = "1.3.6.1.4.1.55555.46"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.56", "test-only-community", 161, "2c",
        [{
            "device_id": "device-group-table-fallback", "sensor_key": "wireless-client-suffix-group",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "table_group_sum", "oid": value_oid,
                "label_oids": {"ssid": label_oid},
                "group_labels": {"ssid": "2.1"},
            }},
        }],
        walk_func=_walk_from({
            value_oid: [("1.1", "30"), ("2.1", "12")],
            label_oid: [("1.1", "Corp")],
        }),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] == 12.0
    assert persisted[0]["quality"] == "good"


def test_poll_table_group_count_counts_string_rows_matching_ssid(monkeypatch):
    oid = "1.3.6.1.4.1.55555.51"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.61", "test-only-community", 161, "2c",
        [{
            "device_id": "device-stellar-ssid-count", "sensor_key": "wireless-stellar-corp",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_group_count", "oid": oid, "group_value": "Corp"}},
        }],
        walk_func=_walk_from({oid: [("1", "Corp"), ("2", "Guest"), ("3", "Corp")]}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] == 2.0
    assert persisted[0]["raw_value"] == "2"
    assert persisted[0]["quality"] == "good"


def test_poll_table_group_count_records_zero_for_complete_empty_table(monkeypatch):
    oid = "1.3.6.1.4.1.55555.52"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.62", "test-only-community", 161, "2c",
        [{
            "device_id": "device-stellar-empty-ssid-count", "sensor_key": "wireless-stellar-empty",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_group_count", "oid": oid, "group_value": "Corp"}},
        }],
        walk_func=_walk_from({oid: []}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] == 0.0
    assert persisted[0]["raw_value"] == "0"


def test_poll_table_group_count_marks_incomplete_walk_missing(monkeypatch):
    oid = "1.3.6.1.4.1.55555.53"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    class PartialWalkError(Exception):
        partial_results = [("1", "Corp")]

    async def partial_walk(_ip, _community, _oid, _port, _version, **_kwargs):
        raise PartialWalkError("timeout")

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.63", "test-only-community", 161, "2c",
        [{
            "device_id": "device-stellar-partial-ssid-count", "sensor_key": "wireless-stellar-partial",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_group_count", "oid": oid, "group_value": "Corp"}},
        }],
        walk_func=partial_walk,
    ))

    assert result == {"good": 0, "missing": 1, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] is None
    assert persisted[0]["quality"] == "missing"


def test_poll_table_sum_marks_incomplete_walk_missing_instead_of_good(monkeypatch):
    oid = "1.3.6.1.4.1.55555.47"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    class PartialWalkError(Exception):
        partial_results = [("1", "15")]

    async def partial_walk(_ip, _community, requested_oid, _port, _version):
        assert requested_oid == oid
        raise PartialWalkError("incomplete table")

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.57", "test-only-community", 161, "2c",
        [{
            "device_id": "device-partial-table-sum", "sensor_key": "wireless-client-partial",
            "measurement_type": "wireless_sensor_value", "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {"kind": "table_sum", "oid": oid}},
        }],
        walk_func=partial_walk,
    ))

    assert result == {"good": 0, "missing": 1, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["value"] is None
    assert persisted[0]["raw_value"] is None
    assert persisted[0]["quality"] == "missing"


def test_poll_applies_explicit_value_map_to_truth_value_enum(monkeypatch):
    oid = "1.3.6.1.4.1.55555.30"
    persisted = []
    monkeypatch.setattr(
        probe, "_persist_hardware_sensor_samples",
        lambda samples: persisted.extend(samples),
    )

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.53", "test-only-community", 161, "2c",
        [{
            "device_id": "device-radio-admin",
            "sensor_key": "radio-admin-1",
            "measurement_type": "wireless_sensor_value",
            "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "direct",
                "oid": oid,
                "index": "1.50.1",
                "value_map": {"1": 1, "true(1)": 1, "2": 0, "false(2)": 0},
            }},
        }],
        walk_func=_walk_from({oid: [("1.50.1", "false(2)")]}),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert persisted[0]["raw_value"] == "false(2)"
    assert persisted[0]["value"] == 0.0


def _prepare_librenms_os_hardware_probe(monkeypatch):
    symbols: dict[tuple[str, str], str] = {}

    class Connection:
        def close(self):
            pass

    def map_oid(mib_path, symbol):
        key = (str(mib_path), str(symbol))
        if key not in symbols:
            symbols[key] = f"1.3.6.1.4.1.55555.{len(symbols) + 1}"
        return symbols[key]

    def resolve(_conn, mib_path, symbol, *, cache=None):
        return map_oid(mib_path, symbol)

    monkeypatch.setattr(probe, "verify_bundled_rule", lambda _rule: True)
    monkeypatch.setattr(source_policy, "verify_librenms_os_rule", lambda _rule: True)
    monkeypatch.setattr(probe, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(probe, "_resolve_pinned_librenms_mib_symbol", resolve)

    def oid(mib_path: str, symbol: str) -> str:
        return map_oid(mib_path, symbol)

    return oid


def test_librenms_comware_os_rule_uses_entity_class_and_nonzero_filters(monkeypatch):
    oid = _prepare_librenms_os_hardware_probe(monkeypatch)
    h3c_mib = "mibs/comware/HH3C-ENTITY-EXT-MIB"
    entity_mib = "mibs/ENTITY-MIB"
    rows = {
        (h3c_mib, "hh3cEntityExtCpuUsage"): [("25", "15"), ("26", "0")],
        (h3c_mib, "hh3cEntityExtMemUsage"): [("25", "75"), ("26", "12"), ("27", "0")],
        (h3c_mib, "hh3cEntityExtMemSize"): [("25", "8192"), ("26", "512"), ("27", "2048")],
        (entity_mib, "entPhysicalName"): [("25", "Board 1"), ("26", "Port 1"), ("27", "Board 2")],
        (entity_mib, "entPhysicalClass"): [("25", "module"), ("26", "port"), ("27", "module")],
    }

    result = asyncio.run(probe.probe_librenms_os_hardware(
        "192.0.2.80", "test-only-community", 161,
        rule={"os_key": "comware", "source_commit": source_policy.PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "H3C"},
        walk_func=_walk_from({oid(*key): values for key, values in rows.items()}),
    ))

    cpu = [item for item in result["sensors"] if item["component_class"] == "processor"]
    memory = [item for item in result["sensors"] if item["component_class"] == "memory_pool"]
    assert [(item["index"], item["value"]) for item in cpu] == [([25], 15.0)]
    assert [(item["index"], item["value"], item["entity_name"]) for item in memory] == [([25], 75.0, "Board 1")]
    assert all(item["source_type"] == "librenms_os_rule" for item in result["sensors"])
    assert memory[0]["metadata"]["librenms_entity_class"] == "module"
    assert memory[0]["metadata"]["poll_plan"]["kind"] == "direct"
    assert cpu[0]["metadata"]["window"] == "unknown"
    assert {item["status"] for item in result["category_results"]} == {"success", "not_found"}


def test_librenms_comware_sensor_rules_cover_chassis_and_transceiver_hardware(monkeypatch):
    oid = _prepare_librenms_os_hardware_probe(monkeypatch)
    h3c_mib = "mibs/comware/HH3C-ENTITY-EXT-MIB"
    entity_mib = "mibs/ENTITY-MIB"
    if_mib = "mibs/IF-MIB"
    transceiver_mib = "mibs/comware/HH3C-TRANSCEIVER-INFO-MIB"
    rows = {
        (h3c_mib, "hh3cEntityExtTemperature"): [("100", "47"), ("101", "65535")],
        (h3c_mib, "hh3cEntityExtTemperatureThreshold"): [("100", "65"), ("101", "70")],
        (entity_mib, "entPhysicalName"): [("100", "Chassis Sensor"), ("101", "Invalid Sensor")],
        (entity_mib, "entPhysicalClass"): [("100", "sensor"), ("101", "sensor")],
        (if_mib, "ifAdminStatus"): [("2", "up(1)"), ("3", "2"), ("4", "1"), ("5", "1"), ("6", "1")],
        (if_mib, "ifName"): [("2", "Ten-GigabitEthernet1/0/2"), ("3", "Ten-GigabitEthernet1/0/3"), ("4", "Ten-GigabitEthernet1/0/4"), ("5", "Ten-GigabitEthernet1/0/5"), ("6", "Ten-GigabitEthernet1/0/6")],
        (if_mib, "ifDescr"): [],
        (transceiver_mib, "hh3cTransceiverDiagnostic"): [("2", "1"), ("3", "1"), ("4", "1"), ("5", "1"), ("6", "1")],
        (transceiver_mib, "hh3cTransceiverTemperature"): [("2", "42"), ("3", "43"), ("4", "2147483647")],
        (transceiver_mib, "hh3cTransceiverTempHiAlarm"): [("2", "90000")],
        (transceiver_mib, "hh3cTransceiverTempLoAlarm"): [("2", "-10000")],
        (transceiver_mib, "hh3cTransceiverTempHiWarn"): [("2", "80000")],
        (transceiver_mib, "hh3cTransceiverTempLoWarn"): [("2", "0")],
        (transceiver_mib, "hh3cTransceiverCurRXPower"): [("2", "-1250"), ("3", "-900"), ("6", "2147483647")],
        (transceiver_mib, "hh3cTransceiverCurTXPower"): [("2", "-500"), ("3", "-600"), ("5", "-420")],
        (transceiver_mib, "hh3cTransceiverRcvPwrHiAlarm"): [("2", "100000")],
        (transceiver_mib, "hh3cTransceiverRcvPwrLoAlarm"): [("2", "10")],
        (transceiver_mib, "hh3cTransceiverRcvPwrHiWarn"): [("2", "50000")],
        (transceiver_mib, "hh3cTransceiverRcvPwrLoWarn"): [("2", "50")],
        (transceiver_mib, "hh3cTransceiverPwrOutHiAlarm"): [("2", "100000")],
        (transceiver_mib, "hh3cTransceiverPwrOutLoAlarm"): [("2", "10")],
        (transceiver_mib, "hh3cTransceiverPwrOutHiWarn"): [("2", "50000")],
        (transceiver_mib, "hh3cTransceiverPwrOutLoWarn"): [("2", "50")],
        (transceiver_mib, "hh3cTransceiverVoltage"): [("2", "330")],
        (transceiver_mib, "hh3cTransceiverVccHiAlarm"): [("2", "36000")],
        (transceiver_mib, "hh3cTransceiverVccLoAlarm"): [("2", "30000")],
        (transceiver_mib, "hh3cTransceiverVccHiWarn"): [("2", "35000")],
        (transceiver_mib, "hh3cTransceiverVccLoWarn"): [("2", "31000")],
        (transceiver_mib, "hh3cTransceiverBiasCurrent"): [("2", "12000")],
        (transceiver_mib, "hh3cTransceiverBiasHiAlarm"): [("2", "200000")],
        (transceiver_mib, "hh3cTransceiverBiasLoAlarm"): [("2", "10000")],
        (transceiver_mib, "hh3cTransceiverBiasHiWarn"): [("2", "150000")],
        (transceiver_mib, "hh3cTransceiverBiasLoWarn"): [("2", "20000")],
    }

    result = asyncio.run(probe.probe_librenms_os_hardware(
        "192.0.2.84", "test-only-community", 161,
        rule={"os_key": "comware", "source_commit": source_policy.PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "H3C"},
        walk_func=_walk_from({oid(*key): values for key, values in rows.items()}),
    ))

    sensors = result["sensors"]
    by_source = {sensor["source_id"]: sensor for sensor in sensors}
    assert by_source["comware:temperature:entity:100"]["value"] == 47.0
    assert by_source["comware:temperature:entity:100"]["thresholds"] == {"critical_upper": 65.0}
    assert by_source["comware:transceiver:temperature:2"]["value"] == 42.0
    assert by_source["comware:transceiver:rx:2"]["value"] == -12.5
    assert by_source["comware:transceiver:tx:2"]["value"] == -5.0
    assert by_source["comware:transceiver:tx:5"]["value"] == -4.2
    assert "comware:transceiver:rx:5" not in by_source
    assert by_source["comware:transceiver:voltage:2"]["value"] == 3.3
    assert by_source["comware:transceiver:current:2"]["value"] == 0.12
    assert not any(sensor["source_id"].endswith(":3") for sensor in sensors)
    assert not any(sensor["source_id"].endswith(":4") for sensor in sensors)
    assert not any(sensor["source_id"].endswith(":6") for sensor in sensors)
    assert all(sensor["source_type"] == "librenms_os_rule" for sensor in sensors)
    assert {item["component_class"] for item in result["category_results"]} >= {
        "temperature", "optical_power", "voltage", "current",
    }
    assert all(
        item["status"] == "success"
        for item in result["category_results"]
        if item["component_class"] in {"temperature", "optical_power", "voltage", "current"}
    )


def test_librenms_cisco_os_rule_prefers_process_cores_qfp_and_cemp(monkeypatch):
    oid = _prepare_librenms_os_hardware_probe(monkeypatch)
    process_mib = "mibs/cisco/CISCO-PROCESS-MIB"
    cemp_mib = "mibs/cisco/CISCO-ENHANCED-MEMPOOL-MIB"
    cmp_mib = "mibs/cisco/CISCO-MEMORY-POOL-MIB"
    qfp_mib = "mibs/cisco/CISCO-ENTITY-QFP-MIB"
    entity_mib = "mibs/ENTITY-MIB"
    rows = {
        (process_mib, "cpmCPUTotal5minRev"): [("1", "22")],
        (process_mib, "cpmCPUTotal5min"): [("1", "30"), ("2", "12")],
        (process_mib, "cpmCPUTotalPhysicalIndex"): [("1", "101"), ("2", "102")],
        (process_mib, "cpmCore5min"): [("1.1", "4"), ("1.2", "5")],
        (qfp_mib, "ceqfpUtilProcessingLoad"): [("101.3", "7"), ("101.2", "8")],
        (entity_mib, "entPhysicalName"): [("101", "Route Processor"), ("102", "Switch Processor")],
        (cemp_mib, "cempMemPoolUsed"): [("101.1", "100")],
        (cemp_mib, "cempMemPoolValid"): [("101.1", "true")],
        (cemp_mib, "cempMemPoolName"): [("101.1", "Processor Pool")],
        (cemp_mib, "cempMemPoolHCUsed"): [("101.1", "400")],
        (cemp_mib, "cempMemPoolFree"): [("101.1", "900")],
        (cemp_mib, "cempMemPoolHCFree"): [("101.1", "600")],
        (cmp_mib, "ciscoMemoryPoolUsed"): [("1", "900")],
        (cmp_mib, "ciscoMemoryPoolFree"): [("1", "100")],
        (cmp_mib, "ciscoMemoryPoolName"): [("1", "Ignored fallback")],
    }

    result = asyncio.run(probe.probe_librenms_os_hardware(
        "192.0.2.81", "test-only-community", 161,
        rule={"os_key": "ios", "source_commit": source_policy.PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Cisco"},
        walk_func=_walk_from({oid(*key): values for key, values in rows.items()}),
    ))

    cpu = [item for item in result["sensors"] if item["component_class"] == "processor"]
    memory = [item for item in result["sensors"] if item["component_class"] == "memory_pool"]
    assert {(tuple(item["index"]), item["value"]) for item in cpu} == {
        ((1, 1), 4.0), ((1, 2), 5.0), ((2,), 12.0), ((101, 3), 7.0),
    }
    assert len(memory) == 1
    assert memory[0]["value"] == 40.0
    assert memory[0]["metadata"]["librenms_mempool_type"] == "cemp"
    assert memory[0]["metadata"]["poll_plan"]["kind"] == "memory_ratio"
    assert memory[0]["metadata"]["poll_plan"]["used"]["oid"] == oid(cemp_mib, "cempMemPoolHCUsed")
    assert {item["metadata"]["window"] for item in cpu} == {"5m"}
    assert all(item["source_type"] == "librenms_os_rule" for item in result["sensors"])


def test_librenms_cisco_os_rule_falls_back_to_avg_busy_and_processor_memory(monkeypatch):
    oid = _prepare_librenms_os_hardware_probe(monkeypatch)
    process_mib = "mibs/cisco/CISCO-PROCESS-MIB"
    cmp_mib = "mibs/cisco/CISCO-MEMORY-POOL-MIB"
    cemp_mib = "mibs/cisco/CISCO-ENHANCED-MEMPOOL-MIB"
    process_rows = {
        (process_mib, "cpmCPUMemoryFree"): [("3", "50")],
        (process_mib, "cpmCPUMemoryUsed"): [("3", "50")],
    }

    async def get_many(_ip, _community, oids, _port, _version):
        return {item: "10" for item in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    result = asyncio.run(probe.probe_librenms_os_hardware(
        "192.0.2.82", "test-only-community", 161,
        rule={"os_key": "ios", "source_commit": source_policy.PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Cisco"},
        walk_func=_walk_from({oid(*key): values for key, values in process_rows.items()}),
    ))

    cpu = next(item for item in result["sensors"] if item["component_class"] == "processor")
    memory = next(item for item in result["sensors"] if item["component_class"] == "memory_pool")
    assert cpu["value"] == 10.0
    assert cpu["metadata"]["librenms_fallback"] == "OLD-CISCO-CPU-MIB::avgBusy5"
    assert cpu["metadata"]["window"] == "5m"
    assert memory["value"] == 50.0
    assert memory["metadata"]["librenms_mempool_type"] == "cpm"
    assert memory["metadata"]["librenms_memory_mib"] == "CISCO-PROCESS-MIB"


def test_librenms_cisco_memory_ratio_plan_polls_used_and_free(monkeypatch):
    used_oid = "1.3.6.1.4.1.9.9.221.1.1.1.1.18"
    free_oid = "1.3.6.1.4.1.9.9.221.1.1.1.1.20"
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.83", "test-only-community", 161, "2c",
        [{
            "device_id": "device-cisco-memory",
            "sensor_key": "cisco-memory-pool-101-1",
            "measurement_type": "memory_usage_percent",
            "lifecycle_status": "active",
            "enabled": True,
            "metadata": {"poll_plan": {
                "kind": "memory_ratio",
                "used": {"oid": used_oid, "index": "101.1", "factor": 1.0, "offset": 0.0},
                "free": {"oid": free_oid, "index": "101.1", "factor": 1.0, "offset": 0.0},
            }},
        }],
        walk_func=_walk_from({
            used_oid: [("101.1", "400")],
            free_oid: [("101.1", "600")],
        }),
    ))

    assert result == {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    assert [(sample["value"], sample["raw_value"], sample["quality"]) for sample in persisted] == [(40.0, "400", "good")]
