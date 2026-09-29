from __future__ import annotations

from services import operational_data_service


def test_transceiver_category_uses_snmp_and_skips_cli_setup(monkeypatch):
    device = {
        "id": "device-optical",
        "hostname": "edge-optical",
        "ip_address": "192.0.2.15",
        "vendor": "H3C",
        "platform": "h3c_comware",
    }
    monkeypatch.setattr(
        operational_data_service,
        "_resolve_categories",
        lambda categories, **_kwargs: list(categories or []),
    )
    monkeypatch.setattr(
        operational_data_service,
        "_resolve_commands",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI command resolution was called")),
    )
    monkeypatch.setattr(
        operational_data_service,
        "_build_connection_params",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("CLI credentials were resolved")),
    )

    def collect(target):
        assert target is device
        return {
            "success": True,
            "source": "snmp",
            "adapter": {"vendor": "H3C", "supported": True},
            "count": 1,
            "records": [{"interface": "Ten-GigabitEthernet1/0/49", "rx_power_dbm": -0.15}],
        }

    monkeypatch.setattr("services.snmp_librenms_optical_service.collect_librenms_optical", collect)

    result = operational_data_service.collect_operational_data(device, categories=["transceiver"])

    category = result["categories"][0]
    assert category["key"] == "transceiver"
    assert category["source"] == "snmp"
    assert category["parser"] == "snmp-optical"
    assert category["commands"] == []
    assert category["raw_outputs"] == []
    assert category["records"][0]["rx_power_dbm"] == -0.15
    assert result["summary"] == {
        "requested_categories": ["transceiver"],
        "successful_categories": 1,
        "failed_categories": 0,
        "total_records": 1,
    }


def test_unsupported_transceiver_vendor_is_reported_without_cli_fallback(monkeypatch):
    device = {
        "id": "device-unsupported-optical",
        "hostname": "edge-unsupported",
        "ip_address": "192.0.2.16",
        "vendor": "Cisco",
        "platform": "cisco_ios",
    }
    monkeypatch.setattr(
        operational_data_service,
        "_resolve_categories",
        lambda categories, **_kwargs: list(categories or []),
    )
    monkeypatch.setattr(
        operational_data_service,
        "_resolve_commands",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported optics must not resolve CLI commands")),
    )
    monkeypatch.setattr(
        operational_data_service,
        "_build_connection_params",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unsupported optics must not resolve CLI credentials")),
    )
    monkeypatch.setattr(
        "services.snmp_librenms_optical_service.collect_librenms_optical",
        lambda _target: {
            "success": False,
            "source": "snmp",
            "adapter": {"vendor": "Cisco", "supported": False, "reason": "not confirmed"},
            "count": 0,
            "records": [],
            "error_code": "UNSUPPORTED_VENDOR",
            "error": "optical SNMP collection is unsupported for this vendor/platform",
        },
    )

    result = operational_data_service.collect_operational_data(device, categories=["transceiver"])

    category = result["categories"][0]
    assert category["success"] is False
    assert category["source"] == "snmp"
    assert category["parse_status"] == "unsupported_by_platform"
    assert category["error_code"] == "UNSUPPORTED_VENDOR"
    assert category["commands"] == []
    assert result["summary"]["failed_categories"] == 1
