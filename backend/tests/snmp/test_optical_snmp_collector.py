import ast
import inspect

import pytest

from services import snmp_optical_service as optical


def _credentials(monkeypatch, *, configured=True):
    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device: {
            "snmp": {
                "version": "2c",
                "server": "192.0.2.10",
                "community": "unit-test-community",
                "port": 161,
                "configured": configured,
            }
        },
    )


def _walk_map(monkeypatch, values):
    calls = []

    async def fake_walk(server, community, oid, **kwargs):
        calls.append((server, community, oid, kwargs))
        return values.get(oid, [])

    monkeypatch.setattr(optical, "_snmp_walk", fake_walk)
    return calls


def test_h3c_optical_walk_normalizes_values_and_sentinels(monkeypatch):
    _credentials(monkeypatch)
    base = optical.H3C_OPTICAL_BASE_OID
    values = {
        optical.IF_NAME_OID: [("2", "Ten-GigabitEthernet1/0/49")],
        f"{base}.9": [("2", "-200")],
        f"{base}.12": [("2", "-1234")],
        f"{base}.15": [("2", "26")],
        f"{base}.16": [("2", "330")],
        f"{base}.17": [("2", "450")],
        # Unsupported by H3C: must not become a metric record.
        f"{base}.12": [("2", "-1234"), ("3", "2147483647")],
    }
    calls = _walk_map(monkeypatch, values)

    result = optical.collect_optical_snmp({"vendor": "H3C", "platform": "h3c_comware", "ip_address": "192.0.2.10"})

    assert result["success"] is True
    assert result["source"] == "snmp"
    assert result["count"] == 1
    record = result["records"][0]
    assert record["interface"] == "Ten-GigabitEthernet1/0/49"
    assert record["ifIndex"] == 2
    assert record["rx_power_dbm"] == pytest.approx(-12.34)
    assert record["tx_power_dbm"] == pytest.approx(-2.0)
    assert record["temperature_c"] == pytest.approx(26)
    assert record["voltage_v"] == pytest.approx(3.3)
    assert record["bias_ma"] == pytest.approx(4.5)
    assert all(item[1] == "unit-test-community" for item in calls)


def test_raisecom_filters_parameter_type_and_invalid_status(monkeypatch):
    _credentials(monkeypatch)
    base = optical.RAISECOM_ROS_DDM_BASE_OID
    values = {
        optical.IF_NAME_OID: [("7", "GigabitEthernet0/7")],
        f"{base}.2": [("7.3", "-21800"), ("7.4", "-24400"), ("7.5", "32000"), ("8.4", "-22000")],
        f"{base}.12": [("7.3", "1"), ("7.4", "1"), ("7.5", "1"), ("8.4", "2")],
    }
    _walk_map(monkeypatch, values)

    result = optical.collect_optical_snmp({"vendor": "Raisecom", "platform": "raisecom_ros", "ip_address": "192.0.2.10"})

    assert result["success"] is True
    assert result["count"] == 1
    assert result["records"] == [pytest.approx({
        "interface": "GigabitEthernet0/7",
        "ifIndex": 7,
        "vendor": "Raisecom",
        "tx_power_dbm": -21.8,
        "rx_power_dbm": -24.4,
        "collected_at": result["records"][0]["collected_at"],
        "source": "snmp",
    })]


def test_zte_uses_confirmed_an_optical_mib_oid_and_units(monkeypatch):
    _credentials(monkeypatch)
    base = optical.ZTE_OPTICAL_BASE_OID
    values = {
        optical.IF_NAME_OID: [("49", "Ten-GigabitEthernet1/0/49")],
        f"{base}.2": [("49", "-25678")],
        f"{base}.3": [("49", "-10000")],
        f"{base}.5": [("49", "7800")],
        f"{base}.6": [("49", "3300")],
        f"{base}.8": [("49", "42000")],
    }
    calls = _walk_map(monkeypatch, values)

    result = optical.collect_optical_snmp({"vendor": "ZTE", "platform": "zte_zxros", "ip_address": "192.0.2.10"})

    assert result["success"] is True
    assert result["count"] == 1
    record = result["records"][0]
    assert record["interface"] == "Ten-GigabitEthernet1/0/49"
    assert record["rx_power_dbm"] == pytest.approx(-25.678)
    assert record["tx_power_dbm"] == pytest.approx(-10)
    assert record["bias_ma"] == pytest.approx(7.8)
    assert record["voltage_v"] == pytest.approx(3.3)
    assert record["temperature_c"] == pytest.approx(42)
    assert f"{base}.2" in [call[2] for call in calls]
    assert not any("3902.3.103.11" in call[2] for call in calls)


def test_ruijie_requires_ddm_support_and_normalizes_all_confirmed_dom_fields(monkeypatch):
    _credentials(monkeypatch)
    base = optical.RUIJIE_OPTICAL_BASE_OID
    values = {
        optical.IF_NAME_OID: [("7", "GigabitEthernet0/7"), ("8", "GigabitEthernet0/8"), ("9", "GigabitEthernet0/9")],
        f"{base}.15": [("7", "1"), ("8", "2"), ("9", "1")],
        f"{base}.17": [("7", "38"), ("8", "39")],
        f"{base}.19": [("7", "3300"), ("8", "3300")],
        f"{base}.21": [("7", "4500"), ("8", "4500")],
        f"{base}.76": [("7", "-1942"), ("8", "-1700"), ("9", "-10000")],
        f"{base}.81": [("7", "-2801"), ("8", "-2700")],
    }
    _walk_map(monkeypatch, values)

    result = optical.collect_optical_snmp({"vendor": "Ruijie", "platform": "ruijie_rgos", "ip_address": "192.0.2.10"})

    assert result["count"] == 1
    assert result["records"][0]["ifIndex"] == 7
    assert result["records"][0]["rx_power_dbm"] == pytest.approx(-19.42)
    assert result["records"][0]["tx_power_dbm"] == pytest.approx(-28.01)
    assert result["records"][0]["temperature_c"] == pytest.approx(38)
    assert result["records"][0]["voltage_v"] == pytest.approx(3.3)
    assert result["records"][0]["bias_ma"] == pytest.approx(4.5)


def test_huawei_vrp_converts_microwatts_and_maps_ent_physical_indices(monkeypatch):
    _credentials(monkeypatch)
    base = optical.HUAWEI_OPTICAL_BASE_OID
    values = {
        optical.ENTITY_PHYSICAL_NAME_OID: [
            ("68632782", "XGigabitEthernet0/0/1"),
            ("68632783", "XGigabitEthernet0/0/2"),
            ("68632784", "XGigabitEthernet0/0/3"),
        ],
        f"{base}.4": [("68632782", "MODULE-SERIAL-1")],
        f"{base}.8": [("68632782", "1000"), ("68632783", "-1234"), ("68632784", "1000")],
        f"{base}.9": [("68632782", "2000"), ("68632783", "-2345"), ("68632784", "1000")],
        f"{base}.12": [("68632782", "1"), ("68632783", "1"), ("68632784", "12")],
    }
    _walk_map(monkeypatch, values)

    result = optical.collect_optical_snmp({"vendor": "Huawei", "platform": "huawei_vrp", "ip_address": "192.0.2.10"})

    assert result["count"] == 2
    by_entity = {record["entityIndex"]: record for record in result["records"]}
    assert by_entity[68632782]["interface"] == "XGigabitEthernet0/0/1"
    assert by_entity[68632782]["rx_power_dbm"] == pytest.approx(0.0)
    assert by_entity[68632782]["tx_power_dbm"] == pytest.approx(3.0102999566)
    assert by_entity[68632782]["serial"] == "MODULE-SERIAL-1"
    assert "ifIndex" not in by_entity[68632782]
    assert by_entity[68632783]["interface"] == "XGigabitEthernet0/0/2"
    assert by_entity[68632783]["rx_power_dbm"] == pytest.approx(-12.34)
    assert by_entity[68632783]["tx_power_dbm"] == pytest.approx(-23.45)


def test_optical_walk_uses_large_row_limit_and_surfaces_all_metric_walk_failures(monkeypatch):
    _credentials(monkeypatch)
    base = optical.H3C_OPTICAL_BASE_OID
    seen = []

    async def fake_walk(_server, _community, oid, **kwargs):
        seen.append((oid, kwargs))
        if oid.startswith(base):
            raise TimeoutError("device diagnostic contains secret")
        return [(str(index), f"GigabitEthernet1/0/{index}") for index in range(701)]

    monkeypatch.setattr(optical, "_snmp_walk", fake_walk)
    result = optical.collect_optical_snmp({"vendor": "H3C", "platform": "h3c_comware", "ip_address": "192.0.2.10"})

    assert result["success"] is False
    assert result["error_code"] == "SNMP_COLLECTION_ERROR"
    assert "secret" not in result["error"]
    assert len(seen) > 0
    assert all(call[1]["max_rows"] == optical.MAX_OPTICAL_WALK_ROWS for call in seen)
    assert all(call[1]["raise_on_error"] is True for call in seen)


def test_juniper_zero_optical_power_is_skipped(monkeypatch):
    _credentials(monkeypatch)
    base = optical.JUNIPER_OPTICAL_BASE_OID
    values = {
        optical.IF_NAME_OID: [("11", "xe-0/0/1"), ("12", "xe-0/0/2")],
        f"{base}.5": [("11", "0"), ("12", "-1234")],
        f"{base}.7": [("11", "-200"), ("12", "0")],
    }
    _walk_map(monkeypatch, values)

    result = optical.collect_optical_snmp({"vendor": "Juniper", "platform": "juniper_junos", "ip_address": "192.0.2.10"})

    assert result["success"] is True
    assert result["count"] == 2
    records = {record["ifIndex"]: record for record in result["records"]}
    assert "rx_power_dbm" not in records[11]
    assert records[11]["tx_power_dbm"] == pytest.approx(-2)
    assert records[12]["rx_power_dbm"] == pytest.approx(-12.34)
    assert "tx_power_dbm" not in records[12]


def test_missing_credentials_and_unknown_vendor_are_structured(monkeypatch):
    _credentials(monkeypatch, configured=False)
    calls = _walk_map(monkeypatch, {})
    missing = optical.collect_optical_snmp({"vendor": "H3C", "platform": "h3c_comware"})
    assert missing["success"] is False
    assert missing["error_code"] == "SNMP_CREDENTIALS_MISSING"
    assert calls == []

    unsupported = optical.collect_optical_snmp({"vendor": "Cisco", "platform": "cisco_ios"})
    assert unsupported["success"] is False
    assert unsupported["error_code"] == "UNSUPPORTED_VENDOR"


def test_collector_module_has_no_cli_or_netmiko_imports():
    tree = ast.parse(inspect.getsource(optical))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any("netmiko" in name.lower() or "cli" in name.lower() for name in imported)
