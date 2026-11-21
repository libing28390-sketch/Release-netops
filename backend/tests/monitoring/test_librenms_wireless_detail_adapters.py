from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from services import librenms_wireless_detail_adapters as adapters
from services import librenms_wireless_rule_service as wireless_rules
from services import snmp_hardware_probe_service as probe
from services.librenms_source_policy import PINNED_LIBRENMS_COMMIT, is_trusted_hardware_sensor
from services.snmp_hardware_inventory_service import _normalize_sensor


def _source_rule(os_key: str) -> dict:
    return dict(wireless_rules._PROFILE_WIRELESS_RULES[os_key]["source_rule"])


def _install_resolver(monkeypatch, symbol_specs):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(adapters, "get_db_connection", lambda: connection)
    oids = {
        (path, symbol): f"1.3.6.1.4.1.55590.{position}"
        for position, (path, symbol) in enumerate(symbol_specs.values(), start=1)
    }
    calls = []

    def resolve(_conn, path, symbol, *, cache=None):
        calls.append((path, symbol))
        return oids.get((path, symbol), "")

    monkeypatch.setattr(probe, "_resolve_pinned_librenms_mib_symbol", resolve)
    return oids, calls, connection


def _walk_from(rows, *, failing_oids=()):
    class WalkRows(list):
        octet_values = {}

    async def walk(_ip, _community, oid, _port, _version):
        if oid in failing_oids:
            error = RuntimeError("fixture walk failed")
            error.partial_results = rows.get(oid, [])
            raise error
        return WalkRows(rows.get(oid, []))

    return walk


def _normalized(sensors):
    now = datetime.now(timezone.utc)
    return [_normalize_sensor(sensor, now) for sensor in sensors]


def _assert_unique_identities(sensors):
    normalized = _normalized(sensors)
    identities = [
        (
            item["source_type"],
            item["component_class"],
            item["measurement_type"],
            item["index_text"],
            item["series_variant"],
        )
        for item in normalized
    ]
    assert len(identities) == len(set(identities))


def _aruba_rows(oids):
    mac_indexes = (
        ("6.17.34.51.68.85", "06:11:22:33:44:55"),
        ("0.17.34.51.68.85", "00:11:22:33:44:55"),
    )
    rows = {
        oids[(adapters._ARUBA_MIB, "aiAccessPointTable")]: [
            (f"1.1.{suffix}", raw_mac) for suffix, raw_mac in mac_indexes
        ],
        oids[(adapters._ARUBA_MIB, "aiAPMACAddress")]: [
            (suffix, raw_mac) for suffix, raw_mac in mac_indexes
        ],
        oids[(adapters._ARUBA_MIB, "aiAPName")]: [
            (suffix, "duplicate-name") for suffix, _raw in mac_indexes
        ],
        oids[(adapters._ARUBA_MIB, "aiAPIPAddress")]: [
            (suffix, f"192.0.2.{position}") for position, (suffix, _raw) in enumerate(mac_indexes, start=61)
        ],
        oids[(adapters._ARUBA_MIB, "aiAPSerialNum")]: [
            (suffix, "duplicate-serial") for suffix, _raw in mac_indexes
        ],
        oids[(adapters._ARUBA_MIB, "aiAPModel")]: [
            (suffix, "1.3.6.1.4.1.14823.2.2.1") for suffix, _raw in mac_indexes
        ],
        oids[(adapters._ARUBA_MIB, "aiAPModelName")]: [
            (suffix, f"AP-Model-{position}") for position, (suffix, _raw) in enumerate(mac_indexes, start=1)
        ],
    }
    radio_rows = {
        "radio_clients": [("6.17.34.51.68.85.1", "12"), ("0.17.34.51.68.85.1", "8")],
        "radio_channel": [("6.17.34.51.68.85.1", "116e"), ("0.17.34.51.68.85.1", "36")],
        "radio_noise_floor": [("6.17.34.51.68.85.1", "96"), ("0.17.34.51.68.85.1", "91")],
        "radio_tx_power": [("6.17.34.51.68.85.1", "18"), ("0.17.34.51.68.85.1", "16")],
        "radio_utilization": [("6.17.34.51.68.85.1", "37"), ("0.17.34.51.68.85.1", "42")],
    }
    for key, symbol in (
        ("radio_clients", "aiRadioClientNum"),
        ("radio_channel", "aiRadioChannel"),
        ("radio_noise_floor", "aiRadioNoiseFloor"),
        ("radio_tx_power", "aiRadioTransmitPower"),
        ("radio_utilization", "aiRadioUtilization64"),
    ):
        rows[oids[(adapters._ARUBA_MIB, symbol)]] = radio_rows[key]
    return rows


def test_aruba_instant_normalizes_fixed_mac_indexes_and_keeps_identity_unique(monkeypatch):
    oids, calls, connection = _install_resolver(monkeypatch, adapters._ARUBA_SYMBOLS)
    source_rule = _source_rule("aruba-instant")
    result = asyncio.run(adapters.probe_wireless_profile_details(
        "aruba-instant",
        "192.0.2.10",
        "test-only-community",
        161,
        source_rule=source_rule,
        version="2c",
        software_version="8.4.0.0",
        walk_func=_walk_from(_aruba_rows(oids)),
    ))

    sensors = result["sensors"]
    by_source = {sensor["source_id"]: sensor for sensor in sensors}
    first = by_source["wireless_aruba_instant:radio:clients:061122334455:1"]
    assert first["value"] == 12
    assert first["index_labels"]["ap_mac"] == "06:11:22:33:44:55"
    assert first["index_labels"]["ap_name"] == "duplicate-name"
    assert first["index_labels"]["ap_ip"] == "192.0.2.61"
    assert first["index_labels"]["ap_serial"] == "duplicate-serial"
    assert first["index_labels"]["ap_model"] == "AP-Model-1"
    assert by_source["wireless_aruba_instant:radio:frequency:061122334455:1"]["value"] == 5580
    assert by_source["wireless_aruba_instant:radio:frequency:061122334455:1"]["metadata"]["poll_plan"]["value_transform"] == "aruba_instant_channel_to_frequency"
    assert by_source["wireless_aruba_instant:radio:noise-floor:061122334455:1"]["value"] == -96
    assert by_source["wireless_aruba_instant:radio:power:061122334455:1"]["value"] == 18
    assert by_source["wireless_aruba_instant:radio:utilization:061122334455:1"]["value"] == 37
    assert by_source["wireless_aruba_instant:radio:clients:001122334455:1"]["value"] == 8
    assert len({sensor["source_id"] for sensor in sensors}) == len(sensors)
    _assert_unique_identities(sensors)

    categories = {item["component_class"]: item for item in result["category_results"]}
    assert categories["wireless_access_point"]["status"] == "success"
    assert categories["wireless_access_point"]["coverage_complete"] is True
    assert categories["wireless_radio"]["status"] == "success"
    assert all(call in calls for call in adapters._ARUBA_SYMBOLS.values())
    assert connection.closed is True

    normalized = _normalized(sensors)
    assert all(item["source_type"] == "librenms_mib_rule" for item in normalized)
    assert all(item["metadata"]["source_path"] == source_rule["source_path"] for item in normalized)
    assert all(item["metadata"]["source_commit"] == PINNED_LIBRENMS_COMMIT for item in normalized)
    assert all(is_trusted_hardware_sensor(sensor) for sensor in sensors)


def _ewc_rows(oids):
    rows = {
        oids[(adapters._EWC_MIB, "apName")]: [("42", "same-ap-name"), ("43", "same-ap-name")],
        oids[(adapters._EWC_MIB, "apStatsMuCounts")]: [("42", "9"), ("43", "4")],
        oids[(adapters._EWC_MIB, "apRadioStatusChannel")]: [("4202", "36"), ("4302", "44")],
        oids[(adapters._EWC_DOT11_MIB, "dot11ExtRadioMaxNfCount")]: [("4202", "-94"), ("4302", "-91")],
        oids[(adapters._EWC_MIB, "apPerfRadioCurrentRSS")]: [("42.2", "-61"), ("43.2", "-67")],
        oids[(adapters._EWC_MIB, "apPerfRadioCurrentSNR")]: [("42.2", "39"), ("43.2", "33")],
        oids[(adapters._EWC_MIB, "apPerfRadioCurrentChannelUtilization")]: [("42.2", "23"), ("43.2", "31")],
        oids[(adapters._EWC_MIB, "apPerfRadioPktRetx")]: [("42.2", "1234"), ("43.2", "456")],
    }
    return rows


def test_ewc_uses_exact_ap_and_radio_indexes_and_pinned_source_provenance(monkeypatch):
    oids, _calls, _connection = _install_resolver(monkeypatch, adapters._EWC_SYMBOLS)
    source_rule = _source_rule("ewc")
    result = asyncio.run(adapters.probe_wireless_profile_details(
        "ewc",
        "192.0.2.11",
        "test-only-community",
        161,
        source_rule=source_rule,
        version="2c",
        walk_func=_walk_from(_ewc_rows(oids)),
    ))

    sensors = result["sensors"]
    by_source = {sensor["source_id"]: sensor for sensor in sensors}
    ap_client = by_source["wireless_ewc:ap:clients:42"]
    assert ap_client["value"] == 9
    assert ap_client["index_labels"]["ap_index"] == 42
    assert ap_client["index_labels"]["ap_name"] == "same-ap-name"

    rssi = by_source["wireless_ewc:radio:rssi:ap:42:radio:2"]
    assert rssi["index"] == [42, 2]
    assert rssi["oid"] == oids[(adapters._EWC_MIB, "apPerfRadioCurrentRSS")]
    assert rssi["index_labels"]["ap_index"] == 42
    assert rssi["index_labels"]["radio_index"] == 2
    assert rssi["index_labels"]["ap_name"] == "same-ap-name"
    assert by_source["wireless_ewc:radio:snr:ap:42:radio:2"]["value"] == 39
    assert by_source["wireless_ewc:radio:utilization:ap:42:radio:2"]["unit"] == "percent"
    assert by_source["wireless_ewc:radio:errors:ap:42:radio:2"]["unit"] == "count"
    # The two upstream tables use different indexes: ifIndex for channel and
    # noise, apIndex.radioIndex for performance. Preserve both forms verbatim.
    channel = by_source["wireless_ewc:radio:frequency:ifindex:4202"]
    noise = by_source["wireless_ewc:radio:noise-floor:ifindex:4202"]
    assert channel["index"] == [4202]
    assert channel["value"] == 36
    assert channel["unit"] == "channel"
    assert noise["index"] == [4202]
    assert noise["value"] == -94
    assert noise["unit"] == "dBm"

    assert by_source["wireless_ewc:radio:rssi:ap:43:radio:2"]["source_id"] != rssi["source_id"]
    assert len({sensor["source_id"] for sensor in sensors}) == len(sensors)
    _assert_unique_identities(sensors)
    categories = {item["component_class"]: item for item in result["category_results"]}
    assert categories["wireless_access_point"]["status"] == "success"
    assert categories["wireless_radio"]["status"] == "success"

    normalized = _normalized(sensors)
    assert all(item["metadata"]["source_commit"] == PINNED_LIBRENMS_COMMIT for item in normalized)
    assert all(item["metadata"]["source_path"] == source_rule["source_path"] for item in normalized)
    assert all(is_trusted_hardware_sensor(sensor) for sensor in sensors)


def test_ewc_preserves_upstream_sentinel_and_out_of_range_wireless_values(monkeypatch):
    oids, _calls, _connection = _install_resolver(monkeypatch, adapters._EWC_SYMBOLS)
    rows = _ewc_rows(oids)
    rows[oids[(adapters._EWC_MIB, "apPerfRadioCurrentRSS")]] = [
        ("42.2", "-100"), ("43.2", "-100"),
    ]
    rows[oids[(adapters._EWC_MIB, "apPerfRadioCurrentSNR")]] = [
        ("42.2", "-100"), ("43.2", "-100"),
    ]
    rows[oids[(adapters._EWC_MIB, "apPerfRadioCurrentChannelUtilization")]] = [
        ("42.2", "-1"), ("43.2", "101"),
    ]
    result = asyncio.run(adapters.probe_wireless_profile_details(
        "ewc", "192.0.2.11", "test-only-community", 161,
        source_rule=_source_rule("ewc"), version="2c", walk_func=_walk_from(rows),
    ))

    by_source = {sensor["source_id"]: sensor for sensor in result["sensors"]}
    assert by_source["wireless_ewc:radio:rssi:ap:42:radio:2"]["value"] == -100
    assert by_source["wireless_ewc:radio:snr:ap:42:radio:2"]["value"] == -100
    assert by_source["wireless_ewc:radio:utilization:ap:42:radio:2"]["value"] == -1
    assert by_source["wireless_ewc:radio:utilization:ap:43:radio:2"]["value"] == 101
    categories = {item["component_class"]: item for item in result["category_results"]}
    assert categories["wireless_radio"]["status"] == "success"


def test_empty_wireless_tables_are_complete_not_found_and_other_os_is_empty(monkeypatch):
    for os_key, symbols in (("aruba-instant", adapters._ARUBA_SYMBOLS), ("ewc", adapters._EWC_SYMBOLS)):
        oids, _calls, _connection = _install_resolver(monkeypatch, symbols)
        result = asyncio.run(adapters.probe_wireless_profile_details(
            os_key,
            "192.0.2.12",
            "test-only-community",
            161,
            source_rule=_source_rule(os_key),
            version="2c",
            software_version="8.4.0.0" if os_key == "aruba-instant" else "",
            walk_func=_walk_from({}),
        ))
        assert result["sensors"] == []
        assert result["category_results"]
        assert all(item["status"] == "not_found" for item in result["category_results"])
        assert all(item["coverage_complete"] is True for item in result["category_results"])


def test_aruba_instant_omits_per_radio_client_counter_before_840(monkeypatch):
    oids, calls, _connection = _install_resolver(monkeypatch, adapters._ARUBA_SYMBOLS)
    result = asyncio.run(adapters.probe_wireless_profile_details(
        "aruba-instant",
        "192.0.2.15",
        "test-only-community",
        161,
        source_rule=_source_rule("aruba-instant"),
        version="2c",
        software_version="8.3.0.0",
        walk_func=_walk_from(_aruba_rows(oids)),
    ))

    assert not any(call == adapters._ARUBA_SYMBOLS["radio_clients"] for call in calls)
    assert not any(sensor["metadata"]["wireless_sensor_class"] == "clients" for sensor in result["sensors"])
    radio = next(item for item in result["category_results"] if item["component_class"] == "wireless_radio")
    assert radio["status"] == "success"
    assert radio["coverage_complete"] is True


def test_aruba_instant_requires_software_version_for_version_gated_radio_clients(monkeypatch):
    oids, _calls, _connection = _install_resolver(monkeypatch, adapters._ARUBA_SYMBOLS)
    result = asyncio.run(adapters.probe_wireless_profile_details(
        "aruba-instant",
        "192.0.2.16",
        "test-only-community",
        161,
        source_rule=_source_rule("aruba-instant"),
        version="2c",
        walk_func=_walk_from(_aruba_rows(oids)),
    ))

    assert not any(sensor["metadata"]["wireless_sensor_class"] == "clients" for sensor in result["sensors"])
    radio = next(item for item in result["category_results"] if item["component_class"] == "wireless_radio")
    assert radio["coverage_complete"] is False
    assert radio["reason_code"] == "aruba_instant_software_version_unknown"

    assert asyncio.run(adapters.probe_wireless_profile_details(
        "unifi",
        "192.0.2.13",
        "test-only-community",
        161,
        source_rule={},
        version="2c",
    )) == {"sensors": [], "category_results": []}


def test_ewc_partial_walk_and_invalid_radio_index_do_not_report_complete(monkeypatch):
    oids, _calls, _connection = _install_resolver(monkeypatch, adapters._EWC_SYMBOLS)
    source_rule = _source_rule("ewc")
    rows = _ewc_rows(oids)
    rows[oids[(adapters._EWC_MIB, "apPerfRadioCurrentSNR")]].append(("42.2.9", "8"))
    failing_oid = oids[(adapters._EWC_MIB, "apPerfRadioCurrentChannelUtilization")]
    result = asyncio.run(adapters.probe_wireless_profile_details(
        "ewc",
        "192.0.2.14",
        "test-only-community",
        161,
        source_rule=source_rule,
        version="2c",
        walk_func=_walk_from(rows, failing_oids={failing_oid}),
    ))

    categories = {item["component_class"]: item for item in result["category_results"]}
    assert categories["wireless_access_point"]["status"] == "success"
    assert categories["wireless_radio"]["status"] == "partial"
    assert categories["wireless_radio"]["coverage_complete"] is False
    assert categories["wireless_radio"]["reason_code"] == "invalid_ewc_radio_row"
