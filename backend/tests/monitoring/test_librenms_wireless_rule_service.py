from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from services import librenms_wireless_rule_service as wireless
from services import librenms_source_policy as source_policy
from services import snmp_hardware_probe_service as probe
from services import snmp_service
from services.snmp_hardware_inventory_service import _normalize_sensor
from services.librenms_source_policy import (
    PINNED_LIBRENMS_COMMIT,
    is_trusted_hardware_sensor,
    verify_librenms_mib_rule,
)


_MIBS = {
    "HH3C-DOT11-ACMT-MIB": "mibs/comware/HH3C-DOT11-ACMT-MIB",
    "HH3C-DOT11-APMT-MIB": "mibs/comware/HH3C-DOT11-APMT-MIB",
}


def _rule() -> dict:
    return {"os_key": "comware", "source_commit": PINNED_LIBRENMS_COMMIT}


def _install_mib_resolver(monkeypatch, symbols):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(wireless, "get_db_connection", Connection)

    def resolve(_conn, mib_path, symbol, *, cache=None):
        module = mib_path.rsplit("/", 1)[-1]
        return symbols.get((module, symbol))

    monkeypatch.setattr(probe, "_resolve_pinned_librenms_mib_symbol", resolve)


def _walk_from(mapping, *, octet_values=None):
    async def walk(_ip, _community, oid, _port, _version):
        class WalkRows(list):
            pass

        result = WalkRows(mapping.get(oid, []))
        result.octet_values = (octet_values or {}).get(oid, {})
        return result

    return walk


def _assert_unique_inventory_identities(sensors):
    normalized = [
        _normalize_sensor(sensor, datetime.now(timezone.utc))
        for sensor in sensors
    ]
    identities = [
        (
            item["source_type"], item["component_class"], item["measurement_type"],
            item["index_text"], item["series_variant"],
        )
        for item in normalized
    ]
    assert len(identities) == len(set(identities))


def test_every_pinned_librenms_wireless_rule_key_has_one_verified_python_source():
    rules = [
        profile["source_rule"]
        for profile in wireless._PROFILE_WIRELESS_RULES.values()
        if not profile.get("alias_of")
    ] + [
        wireless._CISCO_IOS_RULE,
        wireless._HUAWEI_VRP_RULE,
        wireless._CISCO_IOSXE_CELLULAR_RULE,
    ]
    rule_keys = {str(rule["rule_key"]) for rule in rules}
    assert rule_keys == set(source_policy._UPSTREAM_WIRELESS_RULE_KEYS)
    assert "wireless_h3c_comware" not in rule_keys
    for rule in rules:
        assert verify_librenms_mib_rule({
            **rule,
            "source_type": "librenms_mib_rule",
            "source_commit": PINNED_LIBRENMS_COMMIT,
        })


def test_h3c_wireless_mib_adapter_discovers_ap_states_counts_and_identity(monkeypatch):
    symbols = {
        ("HH3C-DOT11-ACMT-MIB", "hh3cDot11TotalAPconnected"): "1.3.6.1.4.1.55555.1",
        ("HH3C-DOT11-ACMT-MIB", "hh3cDot11StationCurAssocSum"): "1.3.6.1.4.1.55555.2",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APOperationStatus"): "1.3.6.1.4.1.55555.3",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPName"): "1.3.6.1.4.1.55555.4",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPModelName"): "1.3.6.1.4.1.55555.5",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APIPAddress"): "1.3.6.1.4.1.55555.6",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APMacAddress"): "1.3.6.1.4.1.55555.7",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPStationAssocCount"): "1.3.6.1.4.1.55555.8",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APCpuUsage"): "1.3.6.1.4.1.55555.9",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AdminStatus"): "1.3.6.1.4.1.55555.10",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11OperStatus"): "1.3.6.1.4.1.55555.11",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11Channel"): "1.3.6.1.4.1.55555.12",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11TxPowerLevel"): "1.3.6.1.4.1.55555.13",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APRadioIfIndex"): "1.3.6.1.4.1.55555.14",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11ResourceUseRatio"): "1.3.6.1.4.1.55555.15",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AvgRxSignalStrength"): "1.3.6.1.4.1.55555.16",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlBusy"): "1.3.6.1.4.1.55555.17",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlTxBusy"): "1.3.6.1.4.1.55555.18",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlRxBusy"): "1.3.6.1.4.1.55555.19",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirExtChnlBusy"): "1.3.6.1.4.1.55555.20",
    }

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(wireless, "get_db_connection", Connection)

    def resolve(_conn, mib_path, symbol, *, cache=None):
        module = mib_path.rsplit("/", 1)[-1]
        return symbols[(module, symbol)]

    monkeypatch.setattr(probe, "_resolve_pinned_librenms_mib_symbol", resolve)
    rows = {
        symbols[("HH3C-DOT11-ACMT-MIB", "hh3cDot11TotalAPconnected")]: [("0", "2")],
        symbols[("HH3C-DOT11-ACMT-MIB", "hh3cDot11StationCurAssocSum")]: [("0", "15")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11APOperationStatus")]: [
            ("1.50", "run(5)"), ("1.49", "5"), ("1.51", "download(3)"),
        ],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPName")]: [("1.50", "AP_12"), ("1.49", "AP_13")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPModelName")]: [("1.50", "WA6320-HCL"), ("1.49", "WA6320-HCL")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11APIPAddress")]: [("1.50", "192.0.2.12"), ("1.49", "192.0.2.13")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11APMacAddress")]: [("1.50", "00:11:22:33:44:12"), ("1.49", "00:11:22:33:44:13")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPStationAssocCount")]: [("1.50", "8"), ("1.49", "7")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11APCpuUsage")]: [("1.50", "18"), ("1.49", "21")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11AdminStatus")]: [("1.50.1", "true(1)"), ("1.50.2", "false(2)")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11OperStatus")]: [
            ("1.50.1", "true(1)"),
            ("1.50.2", "false(2)"),
        ],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11Channel")]: [
            ("1.50.1", "36"), ("1.50.2", "149"),
        ],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11TxPowerLevel")]: [("1.50.1", "18")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11APRadioIfIndex")]: [("1.50.1", "101")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11ResourceUseRatio")]: [("1.50.1", "24")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11AvgRxSignalStrength")]: [("1.50.1", "-62")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlBusy")]: [("1.50.1", "35")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlTxBusy")]: [("1.50.1", "12")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlRxBusy")]: [("1.50.1", "20")],
        symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11AirExtChnlBusy")]: [("1.50.1", "255")],
    }

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.80", "test-only-community", 161,
        rule=_rule(), identity={"vendor": "H3C"},
        walk_func=_walk_from(rows, octet_values={
            symbols[("HH3C-DOT11-APMT-MIB", "hh3cDot11APMacAddress")]: {
                "1.50": bytes.fromhex("001122334412"),
                "1.49": bytes.fromhex("001122334413"),
            },
        }),
    ))

    sensors = result["sensors"]
    by_source = {sensor["source_id"]: sensor for sensor in sensors}
    assert by_source["h3c:wireless:ap-count:controller"]["value"] == 2
    assert by_source["h3c:wireless:clients:controller"]["value"] == 15
    assert by_source["h3c:wireless:ap-state:2"]["raw_value"] == "run(5)"
    assert by_source["h3c:wireless:ap-state:2"]["value"] == 0
    assert probe._mapped_state(
        by_source["h3c:wireless:ap-state:2"]["raw_value"],
        by_source["h3c:wireless:ap-state:2"]["states"],
    )[2] == "good"
    assert by_source["h3c:wireless:ap-state:2"]["index_labels"]["ap_name"] == "AP_12"
    assert by_source["h3c:wireless:ap-state:2"]["index_labels"]["ap_model"] == "WA6320-HCL"
    assert by_source["h3c:wireless:ap-state:2"]["index_labels"]["ap_mac"] == "00:11:22:33:44:12"
    assert by_source["h3c:wireless:ap:clients:2"]["value"] == 8
    assert by_source["h3c:wireless:ap:cpu:1"]["value"] == 21
    assert by_source["h3c:wireless:radio-state:2:1"]["value"] == 0
    assert by_source["h3c:wireless:radio-state:2:2"]["value"] == 2
    assert by_source["h3c:wireless:radio-admin-status:2:1"]["value"] == 1
    assert by_source["h3c:wireless:radio-admin-status:2:2"]["value"] == 0
    assert by_source["h3c:wireless:radio-admin-status:2:2"]["metadata"]["poll_plan"]["value_map"]["false(2)"] == 0
    assert probe._mapped_state(
        by_source["h3c:wireless:radio-state:2:2"]["raw_value"],
        by_source["h3c:wireless:radio-state:2:2"]["states"],
    ) == (2.0, {"1": 0, "true(1)": 0, "2": 2, "false(2)": 2}, "good")
    assert by_source["h3c:wireless:radio:utilization:2:1"]["value"] == 35
    assert by_source["h3c:wireless:radio:radio-resource-usage:2:1"]["value"] == 24
    assert by_source["h3c:wireless:radio:channel:2:1"]["value"] == 36
    assert by_source["h3c:wireless:radio:signal-strength:2:1"]["value"] == -62
    assert by_source["h3c:wireless:radio:tx-power:2:1"]["value"] == 18
    assert by_source["h3c:wireless:radio:interface-index:2:1"]["value"] == 101
    assert "h3c:wireless:radio:ext-channel-utilization:2:1" not in by_source
    assert all(is_trusted_hardware_sensor(sensor) for sensor in sensors)
    _assert_unique_inventory_identities(sensors)
    assert {result["component_class"]: result["status"] for result in result["category_results"]} == {
        "wireless_controller": "success",
        "wireless_access_point": "success",
        "wireless_radio": "success",
    }


def test_h3c_wireless_mib_adapter_reports_empty_table_as_complete_not_found(monkeypatch):
    symbols = {
        ("HH3C-DOT11-ACMT-MIB", "hh3cDot11TotalAPconnected"): "1.3.6.1.4.1.55556.1",
        ("HH3C-DOT11-ACMT-MIB", "hh3cDot11StationCurAssocSum"): "1.3.6.1.4.1.55556.2",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APOperationStatus"): "1.3.6.1.4.1.55556.3",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPName"): "1.3.6.1.4.1.55556.4",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPModelName"): "1.3.6.1.4.1.55556.5",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APIPAddress"): "1.3.6.1.4.1.55556.6",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APMacAddress"): "1.3.6.1.4.1.55556.7",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11CurrAPStationAssocCount"): "1.3.6.1.4.1.55556.8",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APCpuUsage"): "1.3.6.1.4.1.55556.9",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AdminStatus"): "1.3.6.1.4.1.55556.10",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11OperStatus"): "1.3.6.1.4.1.55556.11",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11Channel"): "1.3.6.1.4.1.55556.12",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11TxPowerLevel"): "1.3.6.1.4.1.55556.13",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11APRadioIfIndex"): "1.3.6.1.4.1.55556.14",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11ResourceUseRatio"): "1.3.6.1.4.1.55556.15",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AvgRxSignalStrength"): "1.3.6.1.4.1.55556.16",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlBusy"): "1.3.6.1.4.1.55556.17",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlTxBusy"): "1.3.6.1.4.1.55556.18",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirPrimChnlRxBusy"): "1.3.6.1.4.1.55556.19",
        ("HH3C-DOT11-APMT-MIB", "hh3cDot11AirExtChnlBusy"): "1.3.6.1.4.1.55556.20",
    }

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(wireless, "get_db_connection", Connection)
    monkeypatch.setattr(
        probe,
        "_resolve_pinned_librenms_mib_symbol",
        lambda _conn, path, symbol, *, cache=None: symbols[(path.rsplit("/", 1)[-1], symbol)],
    )

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.81", "test-only-community", 161,
        rule=_rule(), identity={"vendor": "H3C"},
        walk_func=_walk_from({}),
    ))

    ap_result = next(item for item in result["category_results"] if item["component_class"] == "wireless_access_point")
    assert result["sensors"] == []
    assert ap_result["status"] == "not_found"
    assert ap_result["coverage_complete"] is True


def test_huawei_vrp_wireless_python_rule_matches_pinned_ap_and_ssid_discovery(monkeypatch):
    symbols = {
        ("HUAWEI-WLAN-GLOBAL-MIB", "hwWlanCurJointApNum"): "1.3.6.1.4.1.55557.1",
        ("HUAWEI-WLAN-AP-MIB", "hwWlanApName"): "1.3.6.1.4.1.55557.4",
        ("HUAWEI-WLAN-AP-MIB", "hwWlanApSn"): "1.3.6.1.4.1.55557.5",
        ("HUAWEI-WLAN-AP-MIB", "hwWlanApTypeInfo"): "1.3.6.1.4.1.55557.6",
        ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioMac"): "1.3.6.1.4.1.55557.7",
        ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioChUtilizationRate"): "1.3.6.1.4.1.55557.8",
        ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioChInterferenceRate"): "1.3.6.1.4.1.55557.9",
        ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioActualEIRP"): "1.3.6.1.4.1.55557.10",
        ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioType"): "1.3.6.1.4.1.55557.11",
        ("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioWorkingChannel"): "1.3.6.1.4.1.55557.12",
        ("HUAWEI-WLAN-VAP-MIB", "hwWlanVapStaOnlineCnt"): "1.3.6.1.4.1.55557.13",
        ("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid2gStaCnt"): "1.3.6.1.4.1.55557.2",
        ("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid5gStaCnt"): "1.3.6.1.4.1.55557.3",
    }
    _install_mib_resolver(monkeypatch, symbols)
    ap_mac_index = "0.17.34.51.68.85"
    radio_index = f"{ap_mac_index}.1"
    rows = {
        symbols[("HUAWEI-WLAN-GLOBAL-MIB", "hwWlanCurJointApNum")]: [("0", "2")],
        symbols[("HUAWEI-WLAN-AP-MIB", "hwWlanApName")]: [(ap_mac_index, "AP-01")],
        symbols[("HUAWEI-WLAN-AP-MIB", "hwWlanApSn")]: [(ap_mac_index, "SN-01")],
        symbols[("HUAWEI-WLAN-AP-MIB", "hwWlanApTypeInfo")]: [(ap_mac_index, "WA6320")],
        symbols[("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioMac")]: [(radio_index, "00:11:22:33:44:66")],
        symbols[("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioChUtilizationRate")]: [(radio_index, "28")],
        symbols[("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioChInterferenceRate")]: [(radio_index, "12")],
        symbols[("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioActualEIRP")]: [(radio_index, "18")],
        symbols[("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioType")]: [(radio_index, "27")],
        symbols[("HUAWEI-WLAN-AP-RADIO-MIB", "hwWlanRadioWorkingChannel")]: [(radio_index, "36")],
        symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanVapStaOnlineCnt")]: [
            (f"{radio_index}.10", "3"), (f"{radio_index}.11", "4"),
        ],
        symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid2gStaCnt")]: [("4.67.111.114.112", "5")],
        symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid5gStaCnt")]: [
            ("4.67.111.114.112", "9"), ("5.71.117.101.115.116", "3"),
        ],
    }

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.90", "test-only-community", 161,
        rule={"os_key": "vrp", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Huawei", "model": "AC6805"},
        walk_func=_walk_from(rows),
    ))

    by_source = {sensor["source_id"]: sensor for sensor in result["sensors"]}
    assert by_source["huawei:wireless:ap-count:controller"]["value"] == 2
    assert by_source["huawei:wireless:ssid:2.4 GHz:Corp"]["value"] == 5
    assert by_source["huawei:wireless:ssid:5 GHz:Corp"]["value"] == 9
    assert by_source["huawei:wireless:ssid:5 GHz:Guest"]["value"] == 3
    assert by_source["huawei:wireless:ssid:total:Corp"]["value"] == 14
    assert by_source["huawei:wireless:ssid:total:Guest"]["value"] == 3
    assert by_source["huawei:wireless:clients:controller"]["value"] == 17
    assert by_source["huawei:wireless:ssid:total:Corp"]["metadata"]["poll_plan"] == {
        "kind": "table_multi_sum",
        "oids": [symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid2gStaCnt")], symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid5gStaCnt")]],
        "index": "4.67.111.114.112",
    }
    assert by_source["huawei:wireless:clients:controller"]["metadata"]["poll_plan"] == {
        "kind": "table_multi_sum",
        "oids": [symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid2gStaCnt")], symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid5gStaCnt")]],
        "index": "",
    }
    assert by_source["huawei:wireless:ssid:5 GHz:Guest"]["index_labels"]["ssid"] == "Guest"
    assert by_source["huawei:wireless:ap:presence:00:11:22:33:44:55"]["index_labels"]["ap_serial"] == "SN-01"
    assert by_source["huawei:wireless:ap:presence:00:11:22:33:44:55"]["value"] == 1
    assert by_source["huawei:wireless:radio:channel:00:11:22:33:44:55.1"]["value"] == 36
    assert by_source["huawei:wireless:radio:utilization:00:11:22:33:44:55.1"]["value"] == 28
    assert by_source["huawei:wireless:radio:clients:00:11:22:33:44:55.1"]["value"] == 7
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])
    _assert_unique_inventory_identities(result["sensors"])
    assert {item["component_class"]: item["status"] for item in result["category_results"]} == {
        "wireless_controller": "success",
        "wireless_ssid": "success",
        "wireless_access_point": "success",
        "wireless_radio": "success",
    }


def test_huawei_vrp_cross_band_ssid_and_controller_sums_poll_from_both_tables(monkeypatch):
    symbols = {
        ("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid2gStaCnt"): "1.3.6.1.4.1.55557.2",
        ("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid5gStaCnt"): "1.3.6.1.4.1.55557.3",
    }
    _install_mib_resolver(monkeypatch, symbols)
    ssid_2g_oid = symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid2gStaCnt")]
    ssid_5g_oid = symbols[("HUAWEI-WLAN-VAP-MIB", "hwWlanSsid5gStaCnt")]
    raw_rows = {
        ssid_2g_oid: [("4.67.111.114.112", "5")],
        ssid_5g_oid: [("4.67.111.114.112", "9"), ("5.71.117.101.115.116", "3")],
    }
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.90", "test-only-community", 161,
        rule={"os_key": "vrp", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Huawei", "model": "AC6805"},
        walk_func=_walk_from(raw_rows),
    ))
    aggregate_sensors = [
        _normalize_sensor(sensor, datetime.now(timezone.utc))
        for sensor in result["sensors"]
        if sensor["source_id"] in {
            "huawei:wireless:ssid:total:Corp",
            "huawei:wireless:ssid:total:Guest",
            "huawei:wireless:clients:controller",
        }
    ]
    persisted = []
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))

    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.90", "test-only-community", 161, "2c",
        aggregate_sensors,
        walk_func=_walk_from(raw_rows),
    ))

    assert poll_result == {"good": 3, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    samples_by_key = {sample["sensor_key"]: sample for sample in persisted}
    sensors_by_source = {sensor["source_id"]: sensor for sensor in aggregate_sensors}
    assert samples_by_key[sensors_by_source["huawei:wireless:ssid:total:Corp"]["sensor_key"]]["value"] == 14
    assert samples_by_key[sensors_by_source["huawei:wireless:ssid:total:Guest"]["sensor_key"]]["value"] == 3
    assert samples_by_key[sensors_by_source["huawei:wireless:clients:controller"]["sensor_key"]]["value"] == 17


def test_cisco_ios_air_wireless_python_rule_collects_per_radio_clients(monkeypatch):
    symbols = {
        ("CISCO-DOT11-ASSOCIATION-MIB", "cDot11ActiveWirelessClients"): "1.3.6.1.4.1.55558.1",
        ("ENTITY-MIB", "entPhysicalDescr"): "1.3.6.1.2.1.47.1.1.1.1.2",
        ("CISCO-WAN-3G-MIB", "c3gCurrentGsmRssi"): "1.3.6.1.4.1.55558.2",
        ("CISCO-WAN-3G-MIB", "c3gGsmChannelNumber"): "1.3.6.1.4.1.55558.3",
        ("CISCO-WAN-3G-MIB", "c3gGsmCurrentCellId"): "1.3.6.1.4.1.55558.4",
        ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrp"): "1.3.6.1.4.1.55558.5",
        ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrq"): "1.3.6.1.4.1.55558.6",
        ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrSnr"): "1.3.6.1.4.1.55558.7",
    }
    _install_mib_resolver(monkeypatch, symbols)
    rows = {
        symbols[("CISCO-DOT11-ASSOCIATION-MIB", "cDot11ActiveWirelessClients")]: [("10", "6"), ("2", "11")],
        symbols[("ENTITY-MIB", "entPhysicalDescr")]: [("101", "5GHz Radio"), ("100", "2.4GHz Radio")],
        symbols[("CISCO-WAN-3G-MIB", "c3gCurrentGsmRssi")]: [],
        symbols[("CISCO-WAN-3G-MIB", "c3gGsmChannelNumber")]: [],
        symbols[("CISCO-WAN-3G-MIB", "c3gGsmCurrentCellId")]: [],
        symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrp")]: [],
        symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrq")]: [],
        symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrSnr")]: [],
    }

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.91", "test-only-community", 161,
        rule={"os_key": "ios", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Cisco", "model": "AIR-AP2802I-B-K9"},
        walk_func=_walk_from(rows),
    ))

    by_source = {sensor["source_id"]: sensor for sensor in result["sensors"]}
    assert by_source["cisco:wireless:clients:2"]["value"] == 11
    assert by_source["cisco:wireless:clients:10"]["value"] == 6
    assert by_source["cisco:wireless:clients:2"]["index_labels"]["radio_ifindex"] == 2
    assert "2.4GHz Radio" in by_source["cisco:wireless:clients:2"]["sensor_name"]
    assert "5GHz Radio" in by_source["cisco:wireless:clients:10"]["sensor_name"]
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])
    assert result["category_results"][0]["status"] == "success"


def test_cisco_ios_cellular_trait_collects_all_pinned_wireless_sensor_types(monkeypatch):
    symbols = {
        ("CISCO-DOT11-ASSOCIATION-MIB", "cDot11ActiveWirelessClients"): "1.3.6.1.4.1.55558.11",
        ("ENTITY-MIB", "entPhysicalDescr"): "1.3.6.1.2.1.47.1.1.1.1.2",
        ("ENTITY-MIB", "entPhysicalName"): "1.3.6.1.2.1.47.1.1.1.1.7",
        ("CISCO-WAN-3G-MIB", "c3gCurrentGsmRssi"): "1.3.6.1.4.1.55558.12",
        ("CISCO-WAN-3G-MIB", "c3gGsmChannelNumber"): "1.3.6.1.4.1.55558.13",
        ("CISCO-WAN-3G-MIB", "c3gGsmCurrentCellId"): "1.3.6.1.4.1.55558.14",
        ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrp"): "1.3.6.1.4.1.55558.15",
        ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrq"): "1.3.6.1.4.1.55558.16",
        ("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrSnr"): "1.3.6.1.4.1.55558.17",
        ("CISCO-WAN-CELL-EXT-MIB", "cwceLteProfileApn"): "1.3.6.1.4.1.55558.18",
    }
    _install_mib_resolver(monkeypatch, symbols)
    rows = {
        symbols[("CISCO-DOT11-ASSOCIATION-MIB", "cDot11ActiveWirelessClients")]: [("7", "11")],
        symbols[("ENTITY-MIB", "entPhysicalDescr")]: [("7", "5GHz Radio")],
        symbols[("ENTITY-MIB", "entPhysicalName")]: [("1", "Modem 1 Cellular")],
        symbols[("CISCO-WAN-3G-MIB", "c3gCurrentGsmRssi")]: [("1", "-81")],
        symbols[("CISCO-WAN-3G-MIB", "c3gGsmChannelNumber")]: [("1", "645")],
        symbols[("CISCO-WAN-3G-MIB", "c3gGsmCurrentCellId")]: [("1", "1234")],
        symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrp")]: [("1", "-95")],
        symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrq")]: [("1", "-97")],
        symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrSnr")]: [("1", "135")],
        symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteProfileApn")]: [("1.1", "internet")],
    }
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.90", "test-only-community", 161,
        rule={"os_key": "ios", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Cisco", "model": "AIR-AP2802I-B-K9"},
        walk_func=_walk_from(rows),
    ))

    cellular = {
        item["metadata"]["wireless_sensor_class"]: item
        for item in result["sensors"]
        if item["metadata"].get("rule_key") == "wireless_cisco_ios"
        and item["metadata"].get("wireless_sensor_class") != "clients"
    }
    assert {"rssi", "channel", "cell", "rsrp", "rsrq", "snr"} <= set(cellular)
    assert cellular["rssi"]["value"] == -81
    assert cellular["channel"]["value"] == 645
    assert cellular["cell"]["value"] == 1234
    assert cellular["rsrp"]["value"] == -95
    assert abs(cellular["rsrq"]["value"] - (-9.7)) < 1e-9
    assert cellular["snr"]["value"] == 13.5
    assert cellular["rsrq"]["metadata"]["poll_plan"]["factor"] == 0.1
    assert cellular["snr"]["metadata"]["poll_plan"]["factor"] == 0.1
    assert all("internet" in item["sensor_name"] for item in cellular.values())
    assert all(is_trusted_hardware_sensor(item) for item in result["sensors"])
    _assert_unique_inventory_identities(result["sensors"])
    assert len([item for item in result["category_results"] if item["component_class"] == "wireless_radio"]) == 1
    assert result["category_results"][0]["status"] == "success"

    persisted = []
    poll_sensors = {
        sensor_class: _normalize_sensor(cellular[sensor_class], datetime.now(timezone.utc))
        for sensor_class in ("rsrq", "snr")
    }
    rsrq_oid = symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrRsrq")]
    snr_oid = symbols[("CISCO-WAN-CELL-EXT-MIB", "cwceLteCurrSnr")]

    async def get_many(_ip, _community, oids, _port, _version):
        raw_values = {
            f"{rsrq_oid}.1": "-97",
            f"{snr_oid}.1": "135",
        }
        return {oid: raw_values[oid] for oid in oids}

    monkeypatch.setattr(snmp_service, "_snmp_get_many_versioned", get_many)
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))
    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.90", "test-only-community", 161, "2c",
        [poll_sensors["rsrq"], poll_sensors["snr"]],
    ))

    assert poll_result == {"good": 2, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    samples_by_sensor = {sample["sensor_key"]: sample for sample in persisted}
    assert samples_by_sensor[poll_sensors["rsrq"]["sensor_key"]]["raw_value"] == "-97"
    assert abs(samples_by_sensor[poll_sensors["rsrq"]["sensor_key"]]["value"] - (-9.7)) < 1e-9
    assert samples_by_sensor[poll_sensors["snr"]["sensor_key"]]["raw_value"] == "135"
    assert samples_by_sensor[poll_sensors["snr"]["sensor_key"]]["value"] == 13.5


def test_iosxe_invokes_only_its_inherited_cisco_cellular_trait(monkeypatch):
    cellular_calls = []

    async def base(*_args, **_kwargs):
        return {"sensors": [], "category_results": [
            wireless._category_result("wireless_controller", status="not_found", complete=True,
                                      reason_code="empty", reason="No AP inventory."),
        ]}

    async def detail(*_args, **_kwargs):
        return {"sensors": [], "category_results": [
            wireless._category_result("wireless_radio", status="not_found", complete=True,
                                      reason_code="empty", reason="No AP radio rows."),
        ]}

    async def cellular(*_args, **kwargs):
        cellular_calls.append((kwargs["os_key"], kwargs["source_rule"]["rule_key"]))
        return {"sensors": [], "category_results": [
            wireless._category_result("wireless_radio", status="not_found", complete=True,
                                      reason_code="empty", reason="No cellular rows."),
        ]}

    monkeypatch.setattr(wireless, "_probe_profile_wireless", base)
    monkeypatch.setattr(wireless, "_probe_controller_ap_radio_detail", detail)
    monkeypatch.setattr(wireless, "_probe_cisco_cellular_wireless", cellular)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.90", "test-only-community", 161,
        rule={"os_key": "iosxe", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Cisco", "model": "C9800"},
    ))

    assert cellular_calls == [("iosxe", "wireless_cisco_iosxe_cellular")]
    assert len([item for item in result["category_results"] if item["component_class"] == "wireless_radio"]) == 1
    assert result["category_results"][-1]["status"] == "not_found"


def test_cisco_ios_wireless_rule_does_not_probe_non_air_model(monkeypatch):
    async def no_cellular(*_args, **_kwargs):
        return {"sensors": [], "category_results": [
            wireless._category_result("wireless_radio", status="not_found", complete=True,
                                      reason_code="empty", reason="No cellular rows."),
        ]}

    monkeypatch.setattr(wireless, "_probe_cisco_cellular_wireless", no_cellular)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.92", "test-only-community", 161,
        rule={"os_key": "ios", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Cisco", "model": "C9300-48P"},
        walk_func=_walk_from({}),
    ))
    assert result["sensors"] == []
    assert result["category_results"][0]["status"] == "unsupported"


def test_arubaos_profile_collects_pollable_librenms_ap_and_client_scalars(monkeypatch):
    async def get_many(_ip, _community, oids, _port, _version):
        return {oid: "2" if oid.endswith(".3.1.0") else "23" for oid in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.93", "test-only-community", 161,
        rule={"os_key": "arubaos", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Aruba", "model": "Aruba 7205"},
    ))

    by_class = {item["metadata"]["wireless_sensor_class"]: item for item in result["sensors"]}
    assert by_class["ap-count"]["value"] == 2
    assert by_class["clients"]["value"] == 23
    assert all(item["metadata"]["poll_plan"]["kind"] == "get" for item in result["sensors"])
    assert all(is_trusted_hardware_sensor(item) for item in result["sensors"])
    assert result["category_results"][0]["status"] == "success"


def test_arubaos_radio_detail_poll_plans_keep_librenms_power_and_interference_scaling(monkeypatch):
    profile = wireless._PROFILE_WIRELESS_RULES["arubaos"]
    oid_by_key = {key: f"1.3.6.1.4.1.55556.{index}" for index, key in enumerate(profile["detail_symbols"], start=1)}
    monkeypatch.setattr(
        wireless,
        "_resolve_pinned_symbols",
        lambda requests, _mibs: ({key: oid_by_key[key] for key in requests if key in oid_by_key}, []),
    )
    row_10x = "6.17.34.51.68.85.1"
    row_fallback = "6.17.34.51.68.86.1"
    rows = {
        oid_by_key["ap_name"]: [(row_10x, "AP-10X"), (row_fallback, "AP-Fallback")],
        oid_by_key["radio_type"]: [(row_10x, "5GHz"), (row_fallback, "5GHz")],
        oid_by_key["channel"]: [(row_10x, "36"), (row_fallback, "44")],
        oid_by_key["tx_power_10x"]: [(row_10x, "180")],
        oid_by_key["tx_power"]: [(row_fallback, "36")],
        oid_by_key["utilization"]: [(row_10x, "25"), (row_fallback, "30")],
        oid_by_key["associated_clients"]: [(row_10x, "2"), (row_fallback, "3")],
        oid_by_key["monitored_clients"]: [(row_10x, "4"), (row_fallback, "5")],
        oid_by_key["active_bssids"]: [(row_10x, "1"), (row_fallback, "2")],
        oid_by_key["monitored_bssids"]: [(row_10x, "1"), (row_fallback, "2")],
        oid_by_key["interference"]: [(f"{row_10x}.36", "600"), (f"{row_fallback}.44", "1200")],
    }
    result = asyncio.run(wireless._probe_controller_ap_radio_detail(
        "192.0.2.93", "test-only-community", 161,
        os_key="arubaos", profile=profile, version="2c", walk_func=_walk_from(rows),
    ))
    tx_10x = next(item for item in result["sensors"] if item["metadata"]["wireless_sensor_class"] == "tx-power" and item["index_labels"]["ap_name"] == "AP-10X")
    tx_fallback = next(item for item in result["sensors"] if item["metadata"]["wireless_sensor_class"] == "tx-power" and item["index_labels"]["ap_name"] == "AP-Fallback")
    interference = next(item for item in result["sensors"] if item["metadata"]["wireless_sensor_class"] == "interference" and item["index_labels"]["ap_name"] == "AP-10X")
    assert tx_10x["value"] == 18
    assert tx_10x["metadata"]["poll_plan"]["factor"] == 0.1
    assert tx_fallback["value"] == 18
    assert tx_fallback["metadata"]["poll_plan"]["factor"] == 0.5
    assert interference["value"] == 1
    assert interference["metadata"]["poll_plan"]["factor"] == 1 / 600
    assert interference["metadata"]["poll_plan"]["index"] == f"{row_10x}.36"


def test_cisco_wlc_reports_per_ssid_clients_and_pollable_total(monkeypatch):
    profile = wireless._PROFILE_WIRELESS_RULES["ciscowlc"]
    oid_by_key = {key: f"1.3.6.1.4.1.55553.{index}" for index, key in enumerate(profile["symbols"], start=1)}
    monkeypatch.setattr(
        wireless,
        "_resolve_pinned_symbols",
        lambda requests, _mibs: ({key: oid_by_key[key] for key in requests if key in oid_by_key}, []),
    )
    monkeypatch.setattr(probe, "_get_many", lambda *_args: asyncio.sleep(0, result={}))
    rows = {
        oid_by_key["ssid_clients"]: [("1", "5"), ("2", "7")],
        oid_by_key["ssid_names"]: [("1", "Corp"), ("2", "Guest")],
    }
    result = asyncio.run(wireless._probe_profile_wireless(
        "192.0.2.98", "test-only-community", 161,
        os_key="ciscowlc", profile=profile, version="2c", software_version="",
        walk_func=_walk_from(rows),
    ))

    ssid_clients = [
        item for item in result["sensors"]
        if item["component_class"] == "wireless_ssid"
        and item["metadata"]["wireless_sensor_class"] == "clients"
    ]
    total = next(
        item for item in result["sensors"]
        if item["component_class"] == "wireless_controller"
        and item["metadata"]["wireless_sensor_class"] == "clients"
    )
    assert {(item["index_labels"]["ssid"], item["value"]) for item in ssid_clients} == {
        ("Corp", 5.0), ("Guest", 7.0),
    }
    assert total["value"] == 12
    assert total["metadata"]["poll_plan"] == {
        "kind": "table_sum", "oid": oid_by_key["ssid_clients"], "factor": 1.0,
    }


def test_cisco_wlc_interference_poll_plan_reapplies_the_upstream_offset(monkeypatch):
    profile = wireless._PROFILE_WIRELESS_RULES["ciscowlc"]
    oid_by_key = {key: f"1.3.6.1.4.1.55554.{index}" for index, key in enumerate(profile["detail_symbols"], start=1)}
    monkeypatch.setattr(
        wireless,
        "_resolve_pinned_symbols",
        lambda requests, _mibs: ({key: oid_by_key[key] for key in requests if key in oid_by_key}, []),
    )
    ap_index = "6.17.34.51.68.85"
    radio_index = f"{ap_index}.1"
    rows = {
        oid_by_key["ap_name"]: [(ap_index, "AP-01")],
        oid_by_key["radio_type"]: [(radio_index, "802.11ax")],
        oid_by_key["channel"]: [(radio_index, "36")],
        oid_by_key["tx_power"]: [(radio_index, "3")],
        oid_by_key["utilization"]: [(radio_index, "27")],
        oid_by_key["associated_clients"]: [(radio_index, "8")],
        oid_by_key["interference"]: [(f"{radio_index}.36", "-80")],
    }
    result = asyncio.run(wireless._probe_controller_ap_radio_detail(
        "192.0.2.97", "test-only-community", 161,
        os_key="ciscowlc", profile=profile, version="2c", walk_func=_walk_from(rows),
    ))

    interference = next(item for item in result["sensors"] if item["metadata"]["wireless_sensor_class"] == "interference")
    assert interference["value"] == 48
    assert interference["metadata"]["poll_plan"] == {
        "kind": "table_value", "oid": oid_by_key["interference"],
        "index": f"{radio_index}.36", "factor": 1.0,
        "offset": 128.0, "fallback_value": -128.0,
    }


def test_aruba_instant_collects_ssid_clients_and_uses_exact_labels(monkeypatch):
    symbols = {
        "ssid_clients": "1.3.6.1.4.1.55559.1",
        "ssid_names": "1.3.6.1.4.1.55559.2",
        "ap_serials": "1.3.6.1.4.1.55559.3",
    }
    monkeypatch.setattr(
        wireless,
        "_resolve_pinned_symbols",
        lambda _requests, _mibs: (symbols, []),
    )

    async def get_many(_ip, _community, oids, _port, _version):
        return {oid: "2" for oid in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    rows = {
        symbols["ssid_clients"]: [("4.67.111.114.112", "9")],
        symbols["ssid_names"]: [("4.67.111.114.112", "Corp")],
        symbols["ap_serials"]: [("6.0.17.34.51.68.85", "AP-01")],
    }
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.94", "test-only-community", 161,
        rule={"os_key": "aruba-instant", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Aruba", "model": "IAP-315", "software_version": "8.4.0.0"},
        walk_func=_walk_from(rows),
    ))

    ssid = next(item for item in result["sensors"] if item["component_class"] == "wireless_ssid")
    assert ssid["value"] == 9
    assert ssid["index_labels"]["ssid"] == "Corp"
    controller = next(item for item in result["sensors"] if item["metadata"]["wireless_sensor_class"] == "ap-count")
    assert controller["value"] == 1
    total_clients = next(
        item for item in result["sensors"]
        if item["component_class"] == "wireless_controller"
        and item["metadata"]["wireless_sensor_class"] == "clients"
    )
    assert total_clients["value"] == 9
    assert total_clients["metadata"]["poll_plan"] == {
        "kind": "table_sum", "oid": symbols["ssid_clients"], "factor": 1.0,
    }
    assert controller["metadata"]["poll_plan"] == {
        "kind": "table_count", "oid": symbols["ap_serials"],
    }
    assert all(is_trusted_hardware_sensor(item) for item in result["sensors"])
    assert {"wireless_controller", "wireless_ssid"}.issubset(
        {item["component_class"] for item in result["category_results"]}
    )


def test_aruba_instant_uses_legacy_client_table_before_8_4_and_fails_closed_without_version(monkeypatch):
    profile = wireless._PROFILE_WIRELESS_RULES["aruba-instant"]
    oid_by_key = {
        "ssid_clients": "1.3.6.1.4.1.55559.11",
        "ssid_names": "1.3.6.1.4.1.55559.12",
        "ap_serials": "1.3.6.1.4.1.55559.13",
        "client_macs": "1.3.6.1.4.1.55559.14",
    }
    monkeypatch.setattr(
        wireless,
        "_resolve_pinned_symbols",
        lambda requests, _mibs: ({key: oid_by_key[key] for key in requests if key in oid_by_key}, []),
    )
    monkeypatch.setattr(probe, "_get_many", lambda *_args: asyncio.sleep(0, result={}))
    rows = {
        oid_by_key["ap_serials"]: [("1", "AP-01"), ("2", "AP-02")],
        oid_by_key["client_macs"]: [("1", "aa:bb:cc:dd:ee:01"), ("2", "aa:bb:cc:dd:ee:02")],
        oid_by_key["ssid_clients"]: [("1", "9")],
        oid_by_key["ssid_names"]: [("1", "Corp")],
    }

    async def probe_version(software_version):
        return await wireless._probe_profile_wireless(
            "192.0.2.94", "test-only-community", 161,
            os_key="aruba-instant", profile=profile, version="2c",
            software_version=software_version, walk_func=_walk_from(rows),
        )

    legacy = asyncio.run(probe_version("8.3.0.0"))
    legacy_clients = [item for item in legacy["sensors"] if item["metadata"]["wireless_sensor_class"] == "clients"]
    assert [(item["component_class"], item["value"]) for item in legacy_clients] == [("wireless_controller", 2)]
    assert legacy_clients[0]["metadata"]["poll_plan"] == {
        "kind": "table_count", "oid": oid_by_key["client_macs"],
    }

    unknown = asyncio.run(probe_version(""))
    assert not any(item["metadata"]["wireless_sensor_class"] == "clients" for item in unknown["sensors"])
    assert any(
        item["component_class"] == "wireless_controller" and item["status"] in {"partial", "failed"}
        for item in unknown["category_results"]
    )


def test_unifi_client_aggregates_group_by_radio_and_nonempty_ssid(monkeypatch):
    profile = wireless._PROFILE_WIRELESS_RULES["unifi"]
    oid_by_key = {key: f"1.3.6.1.4.1.55558.{index}" for index, key in enumerate(profile["symbols"], start=1)}
    monkeypatch.setattr(
        wireless,
        "_resolve_pinned_symbols",
        lambda requests, _mibs: ({key: oid_by_key[key] for key in requests if key in oid_by_key}, []),
    )
    monkeypatch.setattr(probe, "_get_many", lambda *_args: asyncio.sleep(0, result={}))
    rows = {
        oid_by_key["vif_ccq"]: [("1", "800"), ("2", "700")],
        oid_by_key["vif_clients"]: [("1", "2"), ("2", "3"), ("3", "4")],
        oid_by_key["vif_radio"]: [("1", "5GHz"), ("2", "5GHz"), ("3", "2GHz")],
        oid_by_key["vif_ssid"]: [("1", ""), ("2", "Corp"), ("3", "Guest")],
    }
    result = asyncio.run(wireless._probe_profile_wireless(
        "192.0.2.95", "test-only-community", 161,
        os_key="unifi", profile=profile, version="2c", software_version="",
        walk_func=_walk_from(rows),
    ))

    clients = [
        item for item in result["sensors"]
        if item["metadata"]["wireless_sensor_class"] == "clients"
    ]
    assert {(item["component_class"], item["index_labels"].get("radio"), item["index_labels"].get("ssid"), item["value"])
            for item in clients} == {
        ("wireless_radio", "5GHz", None, 5.0),
        ("wireless_radio", "2GHz", None, 4.0),
        ("wireless_ssid", None, "Corp", 3.0),
        ("wireless_ssid", None, "Guest", 4.0),
    }
    ccq = [item for item in result["sensors"] if item["metadata"]["wireless_sensor_class"] == "ccq"]
    assert [(item["index_labels"].get("ssid"), item["value"]) for item in ccq] == [("Corp", 70.0)]
    radio_5g = next(item for item in clients if item["index_labels"].get("radio") == "5GHz")
    assert radio_5g["metadata"]["poll_plan"] == {
        "kind": "table_group_sum", "oid": oid_by_key["vif_clients"],
        "label_oids": {"radio": oid_by_key["vif_radio"]},
        "group_labels": {"radio": "5GHz"}, "factor": 1.0,
    }


def test_mikrotik_zero_frequency_and_joint_zero_rows_follow_librenms_filters(monkeypatch):
    profile = wireless._PROFILE_WIRELESS_RULES["routeros"]
    oid_by_key = {key: f"1.3.6.1.4.1.55557.{index}" for index, key in enumerate(profile["symbols"], start=1)}
    monkeypatch.setattr(
        wireless,
        "_resolve_pinned_symbols",
        lambda requests, _mibs: ({key: oid_by_key[key] for key in requests if key in oid_by_key}, []),
    )
    monkeypatch.setattr(probe, "_get_many", lambda *_args: asyncio.sleep(0, result={}))
    rows = {
        oid_by_key["ap_clients"]: [("1", "2"), ("2", "0")],
        oid_by_key["ap_ssid"]: [("1", "AP-zero"), ("2", "AP-live")],
        oid_by_key["ap_frequency"]: [("1", "0"), ("2", "2412")],
        oid_by_key["ap_ccq"]: [("1", "0"), ("2", "0")],
        oid_by_key["ap_tx_rate"]: [("1", "0"), ("2", "0")],
        oid_by_key["ap_rx_rate"]: [("1", "0"), ("2", "100")],
        oid_by_key["stat_ssid"]: [("1", "STA-zero"), ("2", "STA-live")],
        oid_by_key["stat_frequency"]: [("1", "0"), ("2", "5180")],
        oid_by_key["stat_tx_ccq"]: [("1", "0"), ("2", "0")],
        oid_by_key["stat_rx_ccq"]: [("1", "0"), ("2", "30")],
        oid_by_key["stat_tx_rate"]: [("1", "0"), ("2", "0")],
        oid_by_key["stat_rx_rate"]: [("1", "0"), ("2", "10")],
    }
    result = asyncio.run(wireless._probe_profile_wireless(
        "192.0.2.96", "test-only-community", 161,
        os_key="routeros", profile=profile, version="2c", software_version="",
        walk_func=_walk_from(rows),
    ))

    by_class = {}
    for item in result["sensors"]:
        by_class.setdefault(item["metadata"]["wireless_sensor_class"], []).append(item)
    assert [item["index"] for item in by_class["frequency-ap"]] == [[2]]
    assert [item["index"] for item in by_class["frequency-station"]] == [[2]]
    assert [item["index"] for item in by_class["rate-ap-tx"]] == [[2]]
    assert [item["index"] for item in by_class["rate-ap-rx"]] == [[2]]
    assert [item["index"] for item in by_class["rate-station-tx"]] == [[2]]
    assert [item["index"] for item in by_class["rate-station-rx"]] == [[2]]
    assert [item["index"] for item in by_class["ccq-rx"]] == [[2]]
    assert [item["index"] for item in by_class["ccq-tx"]] == [[2]]


def test_ruckus_and_cisco_wlc_source_paths_are_explicit_and_iosxe_is_supported():
    for os_key in (
        "ciscowlc", "iosxe", "ruckuswireless", "ruckuswireless-hotzone",
        "ruckuswireless-sz", "ruckuswireless-unleashed", "ciscosat",
        "airos-af", "airos-af-ltu", "airos-af60", "timos",
    ):
        assert os_key in wireless.WIRELESS_RULE_OS_KEYS

    assert "wavence" in wireless._WIRELESS_RULELESS_UPSTREAM
    assert "ciscosat" not in wireless._WIRELESS_RULELESS_UPSTREAM
    assert wireless._PROFILE_WIRELESS_RULES["iosxe"]["alias_of"] == "ciscowlc"

    ewc_ap_counts = {
        item["oid"]: item["sensor_class"]
        for item in wireless._PROFILE_WIRELESS_RULES["ewc"]["scalars"]
        if item["sensor_class"].startswith("ap-count")
    }
    assert ewc_ap_counts == {
        "1.3.6.1.4.1.4329.15.3.5.2.1.0": "ap-count",
        "1.3.6.1.4.1.4329.15.3.5.1.1.0": "ap-count-configured",
    }
    ruckus_ap_counts = {
        item["oid"]: item["sensor_class"]
        for item in wireless._PROFILE_WIRELESS_RULES["ruckuswireless"]["scalars"]
        if item["sensor_class"].startswith("ap-count")
    }
    assert ruckus_ap_counts == {
        "1.3.6.1.4.1.25053.1.2.1.1.1.15.1.0": "ap-count",
        "1.3.6.1.4.1.25053.1.2.1.1.1.15.15.0": "ap-count",
    }


def test_stellar_profile_is_pinned_to_wireless_adapter_and_oaw_mibs():
    assert "stellar" in wireless.WIRELESS_RULE_OS_KEYS
    source_rule = wireless._PROFILE_WIRELESS_RULES["stellar"]["source_rule"]
    assert source_rule["rule_key"] == "wireless_stellar"
    assert source_rule["source_path"] == "LibreNMS/OS/Stellar.php"
    assert set(source_rule["adapter_source_files"]) == {
        "LibreNMS/Modules/Wireless.php",
        "LibreNMS/OS/Stellar.php",
    }
    assert len(source_rule["mib_source_files"]) == 19
    assert all(path.startswith("mibs/nokia/stellar/") for path in source_rule["mib_source_files"])
    assert set(wireless._STELLAR_MODEL_TO_MIB.values()) == set(wireless._STELLAR_OAW_MODULES)


def test_stellar_discovers_ssid_and_total_clients_with_live_poll_plans(monkeypatch):
    module = "OAW-AP1201"
    symbols = {
        "apWlanEssid": "1.3.6.1.4.1.55572.1",
        "apClientWlanService": "1.3.6.1.4.1.55572.2",
    }
    resolved = []

    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(wireless, "get_db_connection", Connection)

    def resolve(_conn, mib_path, symbol, *, cache=None):
        resolved.append((mib_path, symbol))
        return symbols.get(symbol)

    monkeypatch.setattr(probe, "_resolve_pinned_librenms_mib_symbol", resolve)
    ssid_oid = symbols["apWlanEssid"]
    clients_oid = symbols["apClientWlanService"]
    rows = {
        ssid_oid: [("1", "Corp"), ("2", "Guest"), ("3", "athmon2")],
        clients_oid: [
            ("1", "Corp"), ("2", "Corp"), ("3", "Guest"),
            ("4", "athmon2"), ("5", "Unlisted"),
        ],
    }
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.95", "test-only-community", 161,
        rule={"os_key": "stellar", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Alcatel-Lucent Enterprise", "model": module},
        walk_func=_walk_from(rows),
    ))

    per_ssid = {
        item["index_labels"]["ssid"]: item
        for item in result["sensors"]
        if item["component_class"] == "wireless_ssid"
    }
    assert set(per_ssid) == {"Corp", "Guest"}
    assert per_ssid["Corp"]["value"] == 2
    assert per_ssid["Guest"]["value"] == 1
    assert all(item["metadata"]["poll_plan"] == {
        "kind": "table_group_count", "oid": clients_oid, "group_value": ssid,
    } for ssid, item in per_ssid.items())
    total = next(item for item in result["sensors"] if item["component_class"] == "wireless_controller")
    assert total["value"] == 5
    assert total["metadata"]["poll_plan"] == {"kind": "table_count", "oid": clients_oid}
    assert all(path == f"mibs/nokia/stellar/{module}" for path, _symbol in resolved)
    assert {symbol for _path, symbol in resolved} == {"apWlanEssid", "apClientWlanService"}
    assert all(is_trusted_hardware_sensor(item) for item in result["sensors"])
    assert {item["component_class"] for item in result["category_results"]} == {
        "wireless_controller", "wireless_ssid",
    }
    assert all(item["status"] == "success" for item in result["category_results"])


def test_stellar_unknown_hardware_fails_closed_without_mib_or_snmp_reads(monkeypatch):
    def resolve(*_args, **_kwargs):
        raise AssertionError("unknown Stellar hardware must not resolve any MIB symbol")

    async def walk_many(*_args, **_kwargs):
        raise AssertionError("unknown Stellar hardware must not walk SNMP tables")

    monkeypatch.setattr(wireless, "_resolve_pinned_symbols", resolve)
    monkeypatch.setattr(probe, "_walk_many", walk_many)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.96", "test-only-community", 161,
        rule={"os_key": "stellar", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Alcatel-Lucent Enterprise", "model": "OAW-AP9999"},
    ))

    assert result["sensors"] == []
    assert {item["component_class"] for item in result["category_results"]} == {
        "wireless_controller", "wireless_ssid",
    }
    assert all(item["status"] == "unsupported" for item in result["category_results"])
    assert all(item["reason_code"] == "unsupported_stellar_hardware_mib" for item in result["category_results"])


def test_ruckus_zd_ap_counts_and_system_clients_follow_pinned_conditions(monkeypatch):
    symbols = {
        ("RUCKUS-ZD-WLAN-MIB", "ruckusZDWLANNumSta"): "1.3.6.1.4.1.55571.1",
        ("RUCKUS-ZD-WLAN-MIB", "ruckusZDWLANSSID"): "1.3.6.1.4.1.55571.2",
    }
    _install_mib_resolver(monkeypatch, symbols)
    connected_oid = "1.3.6.1.4.1.25053.1.2.1.1.1.15.1.0"
    registered_oid = "1.3.6.1.4.1.25053.1.2.1.1.1.15.15.0"
    total_clients_oid = "1.3.6.1.4.1.25053.1.2.1.1.1.15.2.0"
    requested_gets = []

    async def get_many(_ip, _community, oids, _port, _version):
        requested_gets.append(set(oids))
        return {oid: {connected_oid: "4", registered_oid: "8", total_clients_oid: "23"}[oid] for oid in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    client_oid = symbols[("RUCKUS-ZD-WLAN-MIB", "ruckusZDWLANNumSta")]
    ssid_oid = symbols[("RUCKUS-ZD-WLAN-MIB", "ruckusZDWLANSSID")]
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.96", "test-only-community", 161,
        rule={"os_key": "ruckuswireless", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ruckus", "model": "ZoneDirector"},
        walk_func=_walk_from({
            client_oid: [("1", "9"), ("2", "14")],
            ssid_oid: [("1", "Corp"), ("2", "Guest")],
        }),
    ))

    controller = [sensor for sensor in result["sensors"] if sensor["component_class"] == "wireless_controller"]
    ap_counts = [sensor for sensor in controller if sensor["metadata"]["wireless_sensor_class"] == "ap-count"]
    assert {sensor["sensor_name"]: sensor["value"] for sensor in ap_counts} == {
        "Connected APs": 4, "Total APs": 8,
    }
    assert {sensor["metadata"]["poll_plan"]["oid"] for sensor in ap_counts} == {
        connected_oid, registered_oid,
    }
    total_clients = next(sensor for sensor in controller if sensor["metadata"]["wireless_sensor_class"] == "clients")
    assert total_clients["value"] == 23
    assert total_clients["metadata"]["poll_plan"] == {"kind": "get", "oid": total_clients_oid}
    assert requested_gets == [{connected_oid, registered_oid}, {total_clients_oid}]
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])

    requested_gets.clear()
    single_ssid_result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.96", "test-only-community", 161,
        rule={"os_key": "ruckuswireless", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ruckus", "model": "ZoneDirector"},
        walk_func=_walk_from({client_oid: [("1", "9")], ssid_oid: [("1", "Corp")]}),
    ))
    assert not any(
        sensor["metadata"]["wireless_sensor_class"] == "clients"
        for sensor in single_ssid_result["sensors"]
        if sensor["component_class"] == "wireless_controller"
    )
    assert requested_gets == [{connected_oid, registered_oid}]


def test_ruckus_hotzone_scalar_oids_units_and_poll_samples(monkeypatch):
    values = {
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.1": "12",
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.2": "8",
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.50.1": "23",
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.50.2": "31",
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.2.1.8.1": "-96",
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.2.1.8.2": "-102",
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.21.1": "4",
        "1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.21.2": "5",
    }
    requested = []

    async def get_many(_ip, _community, oids, _port, _version):
        requested.append(set(oids))
        return {oid: values[oid] for oid in oids if oid in values}

    async def get_versioned(_ip, _community, oid, _port, _version):
        return values[oid]

    monkeypatch.setattr(probe, "_get_many", get_many)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.95", "test-only-community", 161,
        rule={"os_key": "ruckuswireless-hotzone", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ruckus", "model": "ZoneDirector"},
    ))

    by_oid = {
        sensor["metadata"]["poll_plan"]["oid"]: sensor
        for sensor in result["sensors"]
    }
    by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in result["sensors"]}
    assert requested == [set(values)]
    assert len(by_oid) == 8
    assert {sensor["metadata"]["poll_plan"]["oid"] for sensor in result["sensors"]} == set(values)
    assert {sensor["metadata"]["poll_plan"]["kind"] for sensor in result["sensors"]} == {"get"}
    assert by_oid["1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.1"]["value"] == 12
    assert by_oid["1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.2"]["value"] == 8
    assert by_oid["1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.1"]["unit"] == "count"
    assert by_oid["1.3.6.1.4.1.25053.1.1.12.1.1.1.3.1.2.2"]["unit"] == "count"
    assert by_class["utilization-2g"]["unit"] == "percent"
    assert by_class["utilization-5g"]["unit"] == "percent"
    assert by_class["noise-floor-2g"]["unit"] == "dBm"
    assert by_class["noise-floor-5g"]["unit"] == "dBm"
    assert by_class["errors-2g"]["unit"] == "count"
    assert by_class["errors-5g"]["unit"] == "count"
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])
    _assert_unique_inventory_identities(result["sensors"])

    # Client sensors share a class, so validate their separate OID/value pairs
    # through the keyed poll samples as well as the radio metric classes.
    poll_sensors = [
        _normalize_sensor(sensor, datetime.now(timezone.utc))
        for sensor in result["sensors"]
    ]
    persisted = []
    monkeypatch.setattr(snmp_service, "_snmp_get_versioned", get_versioned)
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))
    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.95", "test-only-community", 161, "2c", poll_sensors,
        walk_func=_walk_from({}),
    ))

    assert poll_result == {"good": 8, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    samples_by_key = {sample["sensor_key"]: sample for sample in persisted}
    sensors_by_key = {sensor["sensor_key"]: sensor for sensor in poll_sensors}
    assert {
        sensor["metadata"]["poll_plan"]["oid"]: samples_by_key[key]["value"]
        for key, sensor in sensors_by_key.items()
    } == {oid: float(raw) for oid, raw in values.items()}


def test_ruckus_sz_collects_node_ap_counts_and_omits_single_ap_cluster_total(monkeypatch):
    symbols = {
        ("RUCKUS-SZ-WLAN-MIB", "ruckusSZWLANNumSta"): "1.3.6.1.4.1.55572.1",
        ("RUCKUS-SZ-WLAN-MIB", "ruckusSZWLANSSID"): "1.3.6.1.4.1.55572.2",
        ("RUCKUS-CTRL-MIB", "ruckusCtrlSystemNodeNumApConnected"): "1.3.6.1.4.1.55572.3",
        ("RUCKUS-CTRL-MIB", "ruckusCtrlSystemNodeName"): "1.3.6.1.4.1.55572.4",
    }
    _install_mib_resolver(monkeypatch, symbols)
    total_aps_oid = "1.3.6.1.4.1.25053.1.4.1.1.1.15.1.0"
    total_clients_oid = "1.3.6.1.4.1.25053.1.4.1.1.1.15.2.0"
    ap_total = {"value": "2"}

    async def get_many(_ip, _community, oids, _port, _version):
        return {oid: ap_total["value"] if oid == total_aps_oid else "23" for oid in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    client_oid = symbols[("RUCKUS-SZ-WLAN-MIB", "ruckusSZWLANNumSta")]
    ssid_oid = symbols[("RUCKUS-SZ-WLAN-MIB", "ruckusSZWLANSSID")]
    node_ap_oid = symbols[("RUCKUS-CTRL-MIB", "ruckusCtrlSystemNodeNumApConnected")]
    node_name_oid = symbols[("RUCKUS-CTRL-MIB", "ruckusCtrlSystemNodeName")]
    node_one = "4.83.90.48.49"
    node_two = "4.83.90.48.50"
    reads = {
        client_oid: [("1", "7"), ("2", "8")],
        ssid_oid: [("1", "Corp"), ("2", "Guest")],
        node_ap_oid: [(node_one, "3"), (node_two, "4")],
        node_name_oid: [(node_one, "Node East"), (node_two, "Node West")],
    }
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.97", "test-only-community", 161,
        rule={"os_key": "ruckuswireless-sz", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ruckus", "model": "SmartZone"},
        walk_func=_walk_from(reads),
    ))

    controller = [sensor for sensor in result["sensors"] if sensor["component_class"] == "wireless_controller"]
    node_counts = [sensor for sensor in controller if sensor["metadata"]["wireless_sensor_class"] == "ap-count" and sensor["metadata"]["poll_plan"]["kind"] == "direct"]
    assert {sensor["index_labels"]["node"]: sensor["value"] for sensor in node_counts} == {
        "Node East": 3, "Node West": 4,
    }
    total_aps = next(sensor for sensor in controller if sensor["metadata"]["wireless_sensor_class"] == "ap-count" and sensor["metadata"]["poll_plan"]["kind"] == "get")
    assert total_aps["value"] == 2
    assert total_aps["sensor_name"] == "Total APs"
    assert total_aps["metadata"]["poll_plan"] == {"kind": "get", "oid": total_aps_oid}
    total_clients = next(sensor for sensor in controller if sensor["metadata"]["wireless_sensor_class"] == "clients")
    assert total_clients["value"] == 23
    assert total_clients["metadata"]["poll_plan"] == {"kind": "get", "oid": total_clients_oid}
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])

    ap_total["value"] = "1"
    single_ap_result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.97", "test-only-community", 161,
        rule={"os_key": "ruckuswireless-sz", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ruckus", "model": "SmartZone"},
        walk_func=_walk_from(reads),
    ))
    assert not any(
        sensor["sensor_name"] == "Total APs"
        for sensor in single_ap_result["sensors"]
    )


def test_ruckus_unleashed_resolves_pinned_wireless_scalar_symbols(monkeypatch):
    symbols = {
        ("RUCKUS-UNLEASHED-SYSTEM-MIB", "ruckusUnleashedSystemStatsNumAP"): "1.3.6.1.4.1.55573.1",
        ("RUCKUS-UNLEASHED-SYSTEM-MIB", "ruckusUnleashedSystemStatsNumSta"): "1.3.6.1.4.1.55573.2",
    }
    _install_mib_resolver(monkeypatch, symbols)
    expected = {
        "1.3.6.1.4.1.55573.1.0": "5",
        "1.3.6.1.4.1.55573.2.0": "31",
    }
    requested = []

    async def get_many(_ip, _community, oids, _port, _version):
        requested.append(set(oids))
        return {oid: expected[oid] for oid in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.98", "test-only-community", 161,
        rule={"os_key": "ruckuswireless-unleashed", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ruckus", "model": "Unleashed"},
    ))

    assert requested == [set(expected)]
    sensors_by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in result["sensors"]}
    assert sensors_by_class["ap-count"]["value"] == 5
    assert sensors_by_class["clients"]["value"] == 31
    assert sensors_by_class["ap-count"]["metadata"]["poll_plan"] == {"kind": "get", "oid": "1.3.6.1.4.1.55573.1.0"}
    assert sensors_by_class["clients"]["metadata"]["poll_plan"] == {"kind": "get", "oid": "1.3.6.1.4.1.55573.2.0"}
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])


def test_cisco_satellite_wireless_source_collects_signed_rssi_and_snr(monkeypatch):
    symbols = {
        ("CISCO-DMN-DSG-TUNING-MIB", "satSignalUncorErrCnt"): "1.3.6.1.4.1.55560.12",
        ("CISCO-DMN-DSG-TUNING-MIB", "satSignalLevel"): "1.3.6.1.4.1.55560.7",
        ("CISCO-DMN-DSG-TUNING-MIB", "satSignalCnMargin"): "1.3.6.1.4.1.55560.6",
        ("CISCO-DMN-DSG-TUNING-MIB", "satSignalCndisp"): "1.3.6.1.4.1.55560.5",
    }
    _install_mib_resolver(monkeypatch, symbols)
    rows = {
        symbols[("CISCO-DMN-DSG-TUNING-MIB", "satSignalUncorErrCnt")]: [("1", "17")],
        symbols[("CISCO-DMN-DSG-TUNING-MIB", "satSignalLevel")]: [("1", "-56.5")],
        symbols[("CISCO-DMN-DSG-TUNING-MIB", "satSignalCnMargin")]: [("1", "-2.4")],
        symbols[("CISCO-DMN-DSG-TUNING-MIB", "satSignalCndisp")]: [("1", "8.2")],
    }

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.95", "test-only-community", 161,
        rule={"os_key": "ciscosat", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Cisco", "model": "D9854"},
        walk_func=_walk_from(rows),
    ))

    by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in result["sensors"]}
    assert by_class["errors"]["value"] == 17
    assert by_class["rssi"]["value"] == -56.5
    assert by_class["snr-margin"]["value"] == -2.4
    assert by_class["snr-ratio"]["value"] == 8.2
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])
    _assert_unique_inventory_identities(result["sensors"])
    assert result["category_results"][0]["status"] == "success"


def test_airos_wireless_units_signed_values_and_poll_samples(monkeypatch):
    symbols = {
        ("UBNT-AirMAX-MIB", "ubntRadioRssi"): "1.3.6.1.4.1.41112.99.1",
    }
    _install_mib_resolver(monkeypatch, symbols)
    values = {
        "1.3.6.1.4.1.41112.1.4.1.1.4.1": "5800",
        "1.3.6.1.4.1.41112.1.4.6.1.4.1": "80",
        "1.3.6.1.4.1.41112.1.4.5.1.7.1": "96",
        "1.3.6.1.4.1.41112.1.4.5.1.15.1": "7",
        "1.3.6.1.4.1.41112.1.4.1.1.7.1": "12500",
        "1.3.6.1.4.1.41112.1.4.5.1.8.1": "-92",
        "1.3.6.1.4.1.41112.1.4.1.1.6.1": "-47",
        "1.3.6.1.4.1.41112.1.4.5.1.5.1": "-61",
        "1.3.6.1.4.1.41112.1.4.6.1.3.1": "83",
        "1.3.6.1.4.1.41112.1.4.5.1.9.1": "650",
        "1.3.6.1.4.1.41112.1.4.5.1.10.1": "610",
        "1.3.6.1.4.1.41112.1.4.5.1.6.1": "-58",
        "1.3.6.1.4.1.41112.1.4.6.1.7.1": "75",
    }
    rssi_chain_oid = symbols[("UBNT-AirMAX-MIB", "ubntRadioRssi")]
    table_rows = {rssi_chain_oid: [("1", "-54")]}

    async def get_many(_ip, _community, oids, _port, _version):
        return {oid: values[oid] for oid in oids if oid in values}

    async def get_versioned(_ip, _community, oid, _port, _version):
        return values[oid]

    monkeypatch.setattr(probe, "_get_many", get_many)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.99", "test-only-community", 161,
        rule={"os_key": "airos", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ubiquiti", "model": "NanoStation M5"},
        walk_func=_walk_from(table_rows),
    ))

    by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in result["sensors"]}
    assert len(result["sensors"]) == 14
    assert by_class["distance"]["value"] == 12.5
    assert by_class["distance"]["unit"] == "km"
    assert by_class["distance"]["metadata"]["poll_plan"]["oid"] == "1.3.6.1.4.1.41112.1.4.1.1.7.1"
    assert by_class["distance"]["metadata"]["poll_plan"]["factor"] == 0.001
    assert by_class["utilization"]["value"] == 7.5
    assert by_class["utilization"]["unit"] == "percent"
    assert by_class["utilization"]["metadata"]["poll_plan"]["oid"] == "1.3.6.1.4.1.41112.1.4.6.1.7.1"
    assert by_class["utilization"]["metadata"]["poll_plan"]["factor"] == 0.1
    assert by_class["noise-floor"]["value"] == -92
    assert by_class["tx-power"]["value"] == -47
    assert by_class["rx-power"]["value"] == -61
    assert by_class["rssi"]["value"] == -58
    assert by_class["rssi-chain"]["value"] == -54
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])

    poll_sensors = [
        _normalize_sensor(sensor, datetime.now(timezone.utc))
        for sensor in result["sensors"]
    ]
    persisted = []
    monkeypatch.setattr(snmp_service, "_snmp_get_versioned", get_versioned)
    monkeypatch.setattr(probe, "_persist_hardware_sensor_samples", lambda samples: persisted.extend(samples))
    poll_result = asyncio.run(probe.poll_hardware_inventory(
        "192.0.2.99", "test-only-community", 161, "2c", poll_sensors,
        walk_func=_walk_from(table_rows),
    ))

    assert poll_result == {"good": 14, "missing": 0, "invalid": 0, "unsupported_mapping": 0}
    samples_by_key = {sample["sensor_key"]: sample for sample in persisted}
    sensors_by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in poll_sensors}
    expected_samples = {
        "distance": ("12500", 12.5),
        "utilization": ("75", 7.5),
        "noise-floor": ("-92", -92),
        "tx-power": ("-47", -47),
        "rx-power": ("-61", -61),
        "rssi": ("-58", -58),
        "rssi-chain": ("-54", -54),
    }
    for sensor_class, (raw_value, value) in expected_samples.items():
        sample = samples_by_key[sensors_by_class[sensor_class]["sensor_key"]]
        assert sample["raw_value"] == raw_value
        assert sample["value"] == value


def test_airfiber_wireless_source_uses_pinned_scalar_oids_and_signed_power(monkeypatch):
    values = {
        "1.3.6.1.4.1.41112.1.3.1.1.5.1": "11.2",
        "1.3.6.1.4.1.41112.1.3.1.1.6.1": "11.8",
        "1.3.6.1.4.1.41112.1.3.2.1.4.1": "12500",
        "1.3.6.1.4.1.41112.1.3.1.1.9.1": "23",
        "1.3.6.1.4.1.41112.1.3.2.1.11.1": "-48",
        "1.3.6.1.4.1.41112.1.3.2.1.14.1": "-49",
        "1.3.6.1.4.1.41112.1.3.2.1.6.1": "650",
        "1.3.6.1.4.1.41112.1.3.2.1.5.1": "610",
    }

    async def get_many(_ip, _community, oids, _port, _version):
        return {oid: values[oid] for oid in oids if oid in values}

    monkeypatch.setattr(probe, "_get_many", get_many)
    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.99", "test-only-community", 161,
        rule={"os_key": "airos-af", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ubiquiti", "model": "AF-5XHD"},
    ))

    by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in result["sensors"]}
    assert by_class["distance"]["value"] == 12.5
    assert by_class["rx-power-chain-0"]["value"] == -48
    assert by_class["rx-power-chain-1"]["value"] == -49
    assert by_class["tx-rate"]["value"] == 650
    assert len(result["sensors"]) == 8
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])
    _assert_unique_inventory_identities(result["sensors"])


def test_airfiber_60_wireless_source_applies_units_and_keeps_negative_signal_values(monkeypatch):
    symbols = {
        ("UI-AF60-MIB", "af60StaRemoteDistance"): "1.3.6.1.4.1.55561.15",
        ("UI-AF60-MIB", "af60StaTxCapacity"): "1.3.6.1.4.1.55561.7",
        ("UI-AF60-MIB", "af60StaRxCapacity"): "1.3.6.1.4.1.55561.8",
        ("UI-AF60-MIB", "af60StaRSSI"): "1.3.6.1.4.1.55561.3",
        ("UI-AF60-MIB", "af60StaRemoteRSSI"): "1.3.6.1.4.1.55561.18",
        ("UI-AF60-MIB", "af60StaSNR"): "1.3.6.1.4.1.55561.4",
        ("UI-AF60-MIB", "af60StaRemoteSNR"): "1.3.6.1.4.1.55561.19",
    }
    _install_mib_resolver(monkeypatch, symbols)

    async def get_many(_ip, _community, oids, _port, _version):
        return {oid: "60" for oid in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    rows = {oid: [("1", value)] for (_, _), oid in symbols.items() for value in [
        "1200" if oid.endswith(".15") else "250" if oid.endswith(".7") else "175"
        if oid.endswith(".8") else "-61" if oid.endswith(".3") else "-63"
        if oid.endswith(".18") else "-8" if oid.endswith(".4") else "-10"
    ]}

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.96", "test-only-community", 161,
        rule={"os_key": "airos-af60", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ubiquiti", "model": "AF60"},
        walk_func=_walk_from(rows),
    ))

    by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in result["sensors"]}
    assert by_class["distance"]["value"] == 1.2
    assert by_class["tx-rate"]["value"] == 250000
    assert by_class["rx-rate"]["value"] == 175000
    assert by_class["rssi-local"]["value"] == -61
    assert by_class["rssi-remote"]["value"] == -63
    assert by_class["snr-local"]["value"] == -8
    assert by_class["snr-remote"]["value"] == -10
    assert len(result["sensors"]) == 8
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])
    _assert_unique_inventory_identities(result["sensors"])


def test_timos_cellular_wireless_source_uses_interface_names_and_snrs_scale(monkeypatch):
    symbols = {
        ("IF-MIB", "ifName"): "1.3.6.1.2.1.31.1.1.1.1",
        ("TIMETRA-CELLULAR-MIB", "tmnxCellPortSinr"): "1.3.6.1.4.1.55562.12",
        ("TIMETRA-CELLULAR-MIB", "tmnxCellPortRsrq"): "1.3.6.1.4.1.55562.11",
        ("TIMETRA-CELLULAR-MIB", "tmnxCellPortRssi"): "1.3.6.1.4.1.55562.8",
        ("TIMETRA-CELLULAR-MIB", "tmnxCellPortRsrp"): "1.3.6.1.4.1.55562.9",
        ("TIMETRA-CELLULAR-MIB", "tmnxCellPortChannelNumber"): "1.3.6.1.4.1.55562.5",
    }
    _install_mib_resolver(monkeypatch, symbols)
    rows = {
        symbols[("IF-MIB", "ifName")]: [("3", "cellular-1/1/1")],
        symbols[("TIMETRA-CELLULAR-MIB", "tmnxCellPortSinr")]: [("3", "135")],
        symbols[("TIMETRA-CELLULAR-MIB", "tmnxCellPortRsrq")]: [("3", "-9")],
        symbols[("TIMETRA-CELLULAR-MIB", "tmnxCellPortRssi")]: [("3", "-62")],
        symbols[("TIMETRA-CELLULAR-MIB", "tmnxCellPortRsrp")]: [("3", "-84")],
        symbols[("TIMETRA-CELLULAR-MIB", "tmnxCellPortChannelNumber")]: [("3", "78")],
    }

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.97", "test-only-community", 161,
        rule={"os_key": "timos", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Nokia", "model": "7750 SR"},
        walk_func=_walk_from(rows),
    ))

    by_class = {sensor["metadata"]["wireless_sensor_class"]: sensor for sensor in result["sensors"]}
    assert by_class["snr"]["value"] == 13.5
    assert by_class["rssi"]["value"] == -62
    assert by_class["rsrp"]["value"] == -84
    assert by_class["rsrq"]["value"] == -9
    assert by_class["channel"]["value"] == 78
    assert by_class["rssi"]["index_labels"]["interface"] == "cellular-1/1/1"
    assert all(is_trusted_hardware_sensor(sensor) for sensor in result["sensors"])
    _assert_unique_inventory_identities(result["sensors"])


def test_airfiber_ltu_adapter_respects_pinned_first_station_poll_targets(monkeypatch):
    symbols = {
        ("UBNT-AFLTU-MIB", "afLTUStaRemoteDistance"): "1.3.6.1.4.1.55563.23",
        ("UBNT-AFLTU-MIB", "afLTUStaRxPower0"): "1.3.6.1.4.1.55563.5",
        ("UBNT-AFLTU-MIB", "afLTUStaRxPower1"): "1.3.6.1.4.1.55563.6",
        ("UBNT-AFLTU-MIB", "afLTUStaIdealRxPower0"): "1.3.6.1.4.1.55563.7",
        ("UBNT-AFLTU-MIB", "afLTUStaIdealRxPower1"): "1.3.6.1.4.1.55563.8",
        ("UBNT-AFLTU-MIB", "afLTUStaRxPowerLevel0"): "1.3.6.1.4.1.55563.9",
        ("UBNT-AFLTU-MIB", "afLTUStaRxPowerLevel1"): "1.3.6.1.4.1.55563.10",
        ("UBNT-AFLTU-MIB", "afLTUStaTxCapacity"): "1.3.6.1.4.1.55563.3",
        ("UBNT-AFLTU-MIB", "afLTUStaRxCapacity"): "1.3.6.1.4.1.55563.4",
    }
    _install_mib_resolver(monkeypatch, symbols)

    async def get_many(_ip, _community, oids, _port, _version):
        return {oid: "5800000000" if oid.endswith(".2.2.0") else "30" for oid in oids}

    monkeypatch.setattr(probe, "_get_many", get_many)
    rows = {oid: [("1", "1000"), ("2", "2000")] for oid in symbols.values()}
    rows[symbols[("UBNT-AFLTU-MIB", "afLTUStaRxPower0")]] = [("1", "-58"), ("2", "-49")]

    result = asyncio.run(wireless.probe_librenms_wireless_hardware(
        "192.0.2.98", "test-only-community", 161,
        rule={"os_key": "airos-af-ltu", "source_commit": PINNED_LIBRENMS_COMMIT},
        identity={"vendor": "Ubiquiti", "model": "LTU Rocket"},
        walk_func=_walk_from(rows),
    ))

    distance = next(sensor for sensor in result["sensors"] if sensor["metadata"]["wireless_sensor_class"] == "distance")
    rx_power = next(sensor for sensor in result["sensors"] if sensor["metadata"]["wireless_sensor_class"] == "rx-power-chain-0")
    assert distance["value"] == 1
    assert rx_power["value"] == -58
    assert distance["metadata"]["poll_plan"]["index"] == "1"
    assert rx_power["metadata"]["poll_plan"]["index"] == "1"
    _assert_unique_inventory_identities(result["sensors"])
