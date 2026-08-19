from __future__ import annotations


def test_alert_metric_catalog_uses_snmp_templates_for_hardware_and_interface_metrics() -> None:
    from services.snmp_metric_profile_service import list_alert_metric_collections

    catalog = list_alert_metric_collections()

    template_metrics = {
        "cpu",
        "memory",
        "temperature_high",
        "fan_failure",
        "power_supply_failure",
        "interface_util",
        "interface_down",
        "interconnect_down",
        "interface_flap",
        "interface_error_rate_high",
    }
    assert {key for key, value in catalog.items() if value["template_linked"]} == template_metrics
    assert catalog["interface_util"]["default_oids"]["if_hc_in_octets_oid"] == "1.3.6.1.2.1.31.1.1.1.6"
    assert catalog["interface_error_rate_high"]["default_oids"]["if_in_errors_oid"] == "1.3.6.1.2.1.2.2.1.14"
    assert catalog["temperature_high"]["oid_paths"] == ["metric_definitions.temperature.oid"]


def test_alert_rule_normalization_exposes_collection_without_storing_an_oid() -> None:
    from services.alert_rule_service import _normalize_rule_row

    rule = _normalize_rule_row({"id": "rule-1", "metric_type": "cpu", "enabled": 1})

    assert rule["collection"]["collection_source"] == "snmp_template"
    assert rule["collection"]["template_metric"] == "cpu"
    assert "oid" not in rule


def test_non_snmp_alerts_are_not_mislabeled_as_template_metrics() -> None:
    from services.snmp_metric_profile_service import list_alert_metric_collections

    catalog = list_alert_metric_collections()

    assert catalog["lldp_neighbor_lost"]["collection_source"] == "ssh_cli"
    assert catalog["bgp_neighbor_down"]["collection_source"] == "ssh_cli"
    assert catalog["ping_unreachable"]["collection_source"] == "icmp"
    assert catalog["snmp_unreachable"]["collection_source"] == "snmp_probe"
    assert catalog["snmp_unreachable"]["default_oids"]["sys_uptime_oid"] == "1.3.6.1.2.1.1.3.0"
