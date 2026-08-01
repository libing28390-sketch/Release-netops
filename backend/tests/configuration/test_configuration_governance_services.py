from services.config_diff_analysis_service import compare_structured_configs, evaluate_compliance
from services.config_search_service import classify_query, parse_config_objects, redact_config_line
from services.config_template_validation_service import validate_template


def test_search_classifier_keeps_bare_numbers_ambiguous():
    assert classify_query("10.10.1.1").search_type == "IPV4"
    assert classify_query("10.10.1.0/24").search_type == "CIDR"
    assert classify_query("VLAN 100").search_type == "VLAN"
    assert classify_query("AS 65000").search_type == "ASN"
    numeric = classify_query("253")
    assert numeric.search_type == "EXACT_TEXT"
    assert numeric.warnings


def test_search_parser_finds_vendor_neutral_leaf_objects():
    content = """interface GigabitEthernet0/0/1
 ip address 10.10.1.1 255.255.255.0
 port default vlan 100
!
router bgp 65000
 neighbor 10.10.1.2 remote-as 65001
 network 10.10.1.0 mask 255.255.255.0
!
ip route 0.0.0.0 0.0.0.0 10.10.1.254
"""
    objects = parse_config_objects(content, vendor="Huawei")
    object_types = {item.object_type for item in objects}
    assert {"interface", "interface_ip", "bgp", "bgp_peer", "bgp_network", "default_route"} <= object_types
    assert any(item.attributes.get("parent_type") == "interface" for item in objects if item.object_type == "interface_ip")


def test_search_redaction_is_safe_for_common_secret_forms():
    assert "public-secret" not in redact_config_line("snmp-agent community read public-secret")
    assert "radius-key" not in redact_config_line("radius authentication-key radius-key")
    assert "description public-secret" == redact_config_line("description public-secret")


def test_template_validation_strict_sandbox_and_network_filters():
    valid = validate_template(
        "interface {{ interface | normalize_interface }}\n ip address {{ address | ipaddr('address') }} {{ address | netmask }}\n",
        variables={"interface": "gi0/0/1", "address": "10.10.1.1/24"},
        vendor="Cisco",
        platform="cisco_iosxe",
    )
    assert valid["valid"] is True
    assert "GigabitEthernet0/0/1" in valid["rendered"]
    assert "255.255.255.0" in valid["rendered"]

    missing = validate_template("hostname {{ hostname }}\n", variables={})
    assert missing["valid"] is False
    assert missing["missing_variables"] == ["hostname"]

    blocked = validate_template("{{ cycler.__init__.__globals__ }}", variables={})
    assert blocked["valid"] is False
    assert blocked["issues"]


def test_structured_diff_returns_risk_and_compliance_evidence():
    before = """interface Vlanif10
 ip address 10.0.0.1 255.255.255.0
!
ip route-static 0.0.0.0 0.0.0.0 10.0.0.254
"""
    after = """interface Vlanif10
 shutdown
!
"""
    result = compare_structured_configs(
        before,
        after,
        vendor="Huawei",
        device={"id": "d1", "vendor": "Huawei", "role": "core"},
    )
    rule_ids = {risk["rule_id"] for risk in result["risks"]}
    assert "IFACE_SHUTDOWN" in rule_ids
    assert "DEFAULT_ROUTE_DELETE" in rule_ids
    compliance = evaluate_compliance(
        after,
        [{
            "id": "SSH", "name": "SSH required", "scope": {},
            "rule_type": "require", "pattern": r"(?im)^ssh", "minimum_count": 1,
            "severity": "high", "remediation": "enable SSH",
        }],
        {"vendor": "Huawei", "role": "core"},
    )
    assert compliance["noncompliant_count"] == 1
    assert compliance["compliance_rate"] == 0
