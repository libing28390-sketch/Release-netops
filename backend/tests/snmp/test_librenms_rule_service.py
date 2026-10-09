from __future__ import annotations

import json
from pathlib import Path

import database
from services import librenms_rule_service as rules


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "librenms_rule_service"


def _fixture_rules():
    parsed = rules.parse_rules(FIXTURE_ROOT)
    return {item["os_key"]: item for item in parsed}


def test_comware_fixture_preserves_oid_prefix_and_hardware_states():
    parsed = _fixture_rules()
    comware = parsed["comware"]

    assert comware["identity_match"]["contract"] == rules.IDENTITY_CONTRACT
    assert comware["identity_match"]["compatibility"] == "supported"
    predicate = comware["identity_match"]["clauses"][0]["all"][0]
    assert predicate["op"] == "oid_prefix"
    assert predicate["values"] == ["1.3.6.1.4.1.25506"]

    assert rules.match_identity(
        comware["identity_match"],
        {"sys_object_id": ".1.3.6.1.4.1.25506.8.35.9"},
    )["matched"]
    assert not rules.match_identity(
        comware["identity_match"],
        {"sys_object_id": ".1.3.6.1.4.1.2550699.8"},
    )["matched"]

    definitions = comware["hardware_definitions"]
    assert definitions["contract"] == rules.HARDWARE_CONTRACT
    assert definitions["processors"] == []
    assert definitions["mempools"] == []
    assert [item["component_class"] for item in definitions["sensors"]] == [
        "fan_state", "power_supply_state", "power_measurement",
    ]
    assert definitions["sensors"][0]["measurement_type"] == "state"
    assert definitions["sensors"][0]["state_mapping"][0] == {
        "raw_value": 1, "description": "active", "generic_state": 0,
    }
    assert definitions["sensors"][1]["state_name"] == "hh3cdevMPowerStatusTable"
    assert definitions["sensors"][2]["measurement_type"] == "power"
    assert definitions["sensors"][2]["divisor"] == 1000
    assert definitions["sensors"][2]["skip_values"] == [0]


def test_aruba_instant_yaml_separates_ap_and_radio_component_states():
    parsed = {item["os_key"]: item for item in rules.parse_rules()}
    sensors = parsed["aruba-instant"]["hardware_definitions"]["sensors"]
    wireless_states = [
        item for item in sensors
        if item.get("source_class") == "state"
        and item.get("group") in {"Cluster APs", "Cluster Radios"}
    ]

    assert [item["component_class"] for item in wireless_states] == [
        "wireless_access_point", "wireless_radio",
    ]
    assert [item["measurement_type"] for item in wireless_states] == ["state", "state"]

    vrp_wlan_states = [
        item for item in parsed["vrp"]["hardware_definitions"]["sensors"]
        if "hwwlancluster" in str(item.get("state_name") or "").casefold()
    ]
    yunshan_wlan_states = [
        item for item in parsed["yunshan"]["hardware_definitions"]["sensors"]
        if "hwwlancluster" in str(item.get("state_name") or "").casefold()
    ]
    assert vrp_wlan_states and all(item["component_class"] == "wireless_controller" for item in vrp_wlan_states)
    assert yunshan_wlan_states and all(item["component_class"] == "wireless_controller" for item in yunshan_wlan_states)

    routeros_radio_states = [
        item for item in parsed["routeros"]["hardware_definitions"]["sensors"]
        if "mtxrwl60g" in str(item.get("state_name") or "").casefold()
    ]
    timos_cellular_states = [
        item for item in parsed["timos"]["hardware_definitions"]["sensors"]
        if str(item.get("group") or "").casefold() == "cellular status"
    ]
    airos_af_states = [
        item for item in parsed["airos-af"]["hardware_definitions"]["sensors"]
        if any(token in str(item.get("state_name") or "").casefold() for token in ("gpssync", "curtxmodrate"))
    ]
    assert routeros_radio_states and all(item["component_class"] == "wireless_radio" for item in routeros_radio_states)
    assert timos_cellular_states and all(item["component_class"] == "wireless_radio" for item in timos_cellular_states)
    assert airos_af_states and all(item["component_class"] == "wireless_radio" for item in airos_af_states)


def test_vrp_fixture_preserves_processor_mempool_and_sensor_semantics():
    vrp = _fixture_rules()["vrp"]
    definition = vrp["hardware_definitions"]

    assert definition["compatibility"]["level"] == "supported"
    assert len(definition["processors"]) == 1
    processor = definition["processors"][0]
    assert processor["component_class"] == "processor"
    assert processor["measurement_type"] == "cpu_usage"
    assert processor["value_oid"] == "HUAWEI-ENTITY-EXTENT-MIB::hwEntityCpuUsage"
    assert processor["skip_values"][0]["op"] == "!="

    mempool = definition["mempools"][0]
    assert mempool["component_class"] == "memory_pool"
    assert mempool["memory"] == {
        "used_oid": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemoryUsage",
        "free_oid": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemoryFree",
        "total_oid": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemorySize",
        "percent_used_oid": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemoryUsage",
        "relations": {
            "used": {
                "kind": "oid",
                "value": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemoryUsage",
            },
            "free": {
                "kind": "oid",
                "value": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemoryFree",
            },
            "total": {
                "kind": "oid",
                "value": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemorySize",
            },
            "percent_used": {
                "kind": "oid",
                "value": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityMemoryUsage",
            },
        },
        "precision": None,
        "allocation_unit": 1024,
        "pool_class": None,
    }

    temperature = definition["sensors"][0]
    assert temperature["component_class"] == "temperature"
    assert temperature["measurement_type"] == "temperature"
    assert temperature["entPhysicalIndex_measured"] == "ports"
    assert temperature["limits"] == {
        "warn_limit": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityTempMinorAlmThreshold",
        "high_limit": "HUAWEI-ENTITY-EXTENT-MIB::hwEntityTempMajorAlmThreshold",
    }
    assert temperature["divisor"] == 1

    identity = vrp["identity_match"]
    assert len(identity["clauses"]) == 1
    assert rules.match_identity(
        identity, {"sys_descr": "Huawei Versatile Routing Platform Software V8"}
    )["matched"]
    assert not rules.match_identity(identity, {"sys_descr": "unrelated switch"})["matched"]


def test_identity_dictionary_lists_negation_regex_and_unsupported_are_explicit():
    identity = rules._compile_identity({
        "discovery": {
            "sysObjectID": {"prefix": [".1.3.6.1.4.1.9", ".1.3.6.1.4.1.11"]},
            "sysDescr_except": ["laboratory"],
            "sysDescr_regex": ["/^Cisco.*IOS/i"],
        }
    })
    assert identity["compatibility"] == "supported"
    assert rules.match_identity(
        identity,
        {
            "sys_object_id": "1.3.6.1.4.1.9.1",
            "sys_descr": "cisco catalyst IOS XE",
        },
    )["matched"]
    assert not rules.match_identity(
        identity,
        {
            "sys_object_id": "1.3.6.1.4.1.9.1",
            "sys_descr": "Cisco IOS laboratory build",
        },
    )["matched"]
    assert not rules.match_identity(
        identity,
        {
            "sys_object_id": "1.3.6.1.4.1.99.1",
            "sys_descr": "Cisco IOS XE",
        },
    )["matched"]

    unsupported = rules._compile_identity({
        "discovery": [{"snmpget": [{"oid": "1.2.3", "op": "regex", "value": "x"}]}]
    })
    assert unsupported["compatibility"] == "unsupported"
    assert unsupported["diagnostics"][0]["code"] == "unsupported_identity_snmp_clause"
    assert not rules.match_identity(unsupported, {"platform": "test"})["matched"]


def test_unsupported_pcre_modifier_does_not_turn_into_a_looser_match():
    identity = rules._compile_identity({
        "discovery": [{"sysDescr_regex": "/trusted/D"}]
    })
    assert identity["compatibility"] == "unsupported"
    assert any(item["code"] == "unsupported_identity_regex" for item in identity["diagnostics"])
    assert not rules.match_identity(identity, {"sys_descr": "trusted"})["matched"]


def test_hardware_skip_compatibility_only_claims_native_operators():
    scalar = rules._definition_diagnostics({"skip_values": 0}, "fixture.scalar")
    numeric_condition = rules._definition_diagnostics(
        {"skip_values": [{"oid": "EXAMPLE-MIB::status", "op": "!=", "value": 3}]},
        "fixture.numeric",
    )
    regex_condition = rules._definition_diagnostics(
        {"skip_values": [{"op": "regex", "value": "^ok$"}]},
        "fixture.regex",
    )
    device_condition = rules._definition_diagnostics(
        {"skip_values": [{"device": "hardware", "op": "not_starts", "value": "AP7"}]},
        "fixture.device",
    )
    unknown_device_field = rules._definition_diagnostics(
        {"skip_values": [{"device": "serial", "op": "equals", "value": "abc"}]},
        "fixture.device_unknown",
    )

    assert [diagnostic["code"] for _status, diagnostic in scalar] == ["definition_without_num_oid"]
    assert [diagnostic["code"] for _status, diagnostic in numeric_condition] == ["definition_without_num_oid"]
    assert [diagnostic["code"] for _status, diagnostic in regex_condition] == ["definition_without_num_oid"]
    assert any(status == "partial" and diagnostic["code"] == "skip_device_field_requires_identity"
               for status, diagnostic in device_condition)
    assert any(status == "requires_adapter" and diagnostic["code"] == "skip_device_field_requires_adapter"
               for status, diagnostic in unknown_device_field)


def test_sensor_group_options_and_skip_thresholds_are_expanded_for_probe():
    hardware = rules._parse_hardware_definitions({
        "modules": {
            "sensors": {
                "temperature": {
                    "options": {"skip_value_lt": 0, "skip_value_gt": 90},
                    "data": [{
                        "num_oid": ".1.3.6.1.4.1.55555.1.0",
                        "skip_values": [{"op": "==", "value": 255}],
                    }],
                },
            },
        },
    }, source_path="fixture/options.yaml")

    skip_values = hardware["sensors"][0]["skip_values"]
    assert skip_values == [
        {"op": "==", "value": 255},
        {"op": "<", "value": 0},
        {"op": ">", "value": 90},
    ]


def test_sync_and_resolve_keep_legacy_candidates_and_return_structured_contract(isolated_db):
    conn = database.get_db_connection()
    try:
        result = rules.sync_rules(conn, FIXTURE_ROOT)
        assert result["imported"] == 2
        assert result["diagnostics"] == 0

        resolved = rules.resolve_rule(
            conn,
            {
                "sys_object_id": ".1.3.6.1.4.1.25506.8.35.9",
                "sys_descr": "HPE Comware",
            },
        )
        assert resolved is not None
        assert resolved["os_key"] == "comware"
        assert resolved["identity_match"]["matched"] is True
        assert resolved["identity_match"]["matched_by"][0]["field"] == "sysObjectID"
        assert resolved["hardware_definitions"]["contract"] == rules.HARDWARE_CONTRACT
        assert isinstance(resolved["oid_candidates"], list)
        assert resolved["discovery_source_path"] == "resources/definitions/os_discovery/comware.yaml"

        stored = json.loads(
            conn.execute(
                "SELECT detection_json FROM snmp_librenms_rules WHERE os_key = 'comware'"
            ).fetchone()["detection_json"]
        )
        assert stored["hardware_definitions"]["sensors"][0]["component_class"] == "fan_state"
        assert stored["discovery_source_path"] == "resources/definitions/os_discovery/comware.yaml"
    finally:
        conn.close()
