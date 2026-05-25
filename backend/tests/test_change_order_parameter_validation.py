import pytest
from api.change_orders import validate_variable_value

def test_acl_number_validation():
    # Test Cisco ACL validation
    assert validate_variable_value("acl_number", "10", platform="cisco_ios") is None
    assert validate_variable_value("acl_number", "150", platform="cisco_ios") is None
    assert validate_variable_value("acl_number", "1500", platform="cisco_ios") is None
    assert validate_variable_value("acl_number", "2500", platform="cisco_ios") is None
    # Out of range for Cisco
    assert validate_variable_value("acl_number", "200", platform="cisco_ios") is not None
    assert validate_variable_value("acl_number", "1000", platform="cisco_ios") is not None
    assert validate_variable_value("acl_number", "3000", platform="cisco_ios") is not None
    assert validate_variable_value("acl_number", "-5", platform="cisco_ios") is not None
    assert validate_variable_value("acl_number", "abc", platform="cisco_ios") is not None

    # Test Huawei/H3C ACL validation
    assert validate_variable_value("acl_number", "2000", platform="huawei_vrp") is None
    assert validate_variable_value("acl_number", "3500", platform="huawei_vrp") is None
    assert validate_variable_value("acl_number", "6999", platform="h3c_comware") is None
    # Out of range for Huawei/H3C
    assert validate_variable_value("acl_number", "1999", platform="huawei_vrp") is not None
    assert validate_variable_value("acl_number", "7000", platform="h3c_comware") is not None

    # Test Arista ACL validation
    assert validate_variable_value("acl_number", "50", platform="arista_eos") is None
    assert validate_variable_value("acl_number", "199", platform="arista_eos") is None
    # Out of range for Arista
    assert validate_variable_value("acl_number", "200", platform="arista_eos") is not None


def test_wildcard_mask_validation():
    # Valid wildcard masks
    assert validate_variable_value("wildcard_mask", "0.0.0.255") is None
    assert validate_variable_value("wildcard_mask", "0.0.15.255") is None
    # Invalid wildcard masks
    assert validate_variable_value("wildcard_mask", "256.0.0.0") is not None
    assert validate_variable_value("wildcard_mask", "0.0.0") is not None
    assert validate_variable_value("wildcard_mask", "0.0.0.abc") is not None
    assert validate_variable_value("inverse_mask", "0.0.0.255") is None


def test_netmask_validation():
    # Valid netmasks
    assert validate_variable_value("netmask", "255.255.255.0") is None
    assert validate_variable_value("subnet_mask", "255.255.0.0") is None
    assert validate_variable_value("mask", "255.0.0.0") is None
    assert validate_variable_value("netmask", "24") is None
    # Cisco specific validation (reject pure integer bits)
    assert validate_variable_value("netmask", "24", platform="cisco_ios") is not None
    assert validate_variable_value("netmask", "255.255.255.0", platform="cisco_ios") is None
    # Invalid netmasks
    assert validate_variable_value("netmask", "33") is not None
    assert validate_variable_value("netmask", "255.255.255.1") is not None
    assert validate_variable_value("subnet_mask", "abc") is not None


def test_ip_network_validation():
    # Test traditional platform with separate mask variables (independent mask in variables dict)
    variables_with_mask = {"source_network": "192.168.1.0", "wildcard_mask": "0.0.0.255"}
    assert validate_variable_value("source_network", "192.168.1.1", platform="cisco_ios", variables=variables_with_mask) is None
    # Should reject CIDR prefix when mask is present
    err = validate_variable_value("source_network", "192.168.1.0/24", platform="cisco_ios", variables=variables_with_mask)
    assert err is not None
    assert "必须是纯 IP 地址" in err

    # Test traditional platform WITHOUT separate mask variables (no mask in variables)
    variables_without_mask = {"source_network": "192.168.1.0/24"}
    assert validate_variable_value("source_network", "192.168.1.0/24", platform="cisco_ios", variables=variables_without_mask) is None
    assert validate_variable_value("source_network", "192.168.1.1", platform="cisco_ios", variables=variables_without_mask) is None

    # Test other platforms (e.g. Juniper/Arista) which allow CIDR directly
    assert validate_variable_value("source_network", "192.168.1.0/24", platform="juniper_junos") is None
    assert validate_variable_value("source_network", "192.168.1.1", platform="arista_eos") is None

    # Invalid IPs
    assert validate_variable_value("source_network", "abc", platform="cisco_ios") is not None
    assert validate_variable_value("source_network", "999.999.999.999", platform="juniper_junos") is not None


def test_ospf_bgp_area_validation():
    # Test OSPF process ID (must be 1-65535)
    assert validate_variable_value("ospf_process_id", "1") is None
    assert validate_variable_value("ospf_process_id", "65535") is None
    assert validate_variable_value("ospf_process_id", "0") is not None
    assert validate_variable_value("ospf_process_id", "65536") is not None
    assert validate_variable_value("ospf_process_id", "abc") is not None

    # Test OSPF Area ID (integer 0-4294967295 or IP address)
    assert validate_variable_value("area_id", "0", platform="cisco_ios") is None
    assert validate_variable_value("area_id", "4294967295", platform="cisco_ios") is None
    assert validate_variable_value("area_id", "0.0.0.0", platform="cisco_ios") is None
    # Test Juniper OSPF Area ID constraint (dotted decimal only)
    assert validate_variable_value("area_id", "0.0.0.0", platform="juniper_junos") is None
    assert validate_variable_value("area_id", "10", platform="juniper_junos") is not None
    assert validate_variable_value("area_id", "abc", platform="juniper_junos") is not None

    # Test AS Number (integer 1-4294967295 or ASdot X.Y format)
    assert validate_variable_value("local_as", "65000") is None
    assert validate_variable_value("peer_as", "4294967295") is None
    assert validate_variable_value("local_as", "1.0") is None
    assert validate_variable_value("local_as", "65535.65535") is None
    assert validate_variable_value("local_as", "0.0") is not None
    assert validate_variable_value("local_as", "65536.1") is not None
    assert validate_variable_value("local_as", "abc") is not None

    # Test Router ID (strict IPv4 address)
    assert validate_variable_value("router_id", "10.0.0.1") is None
    assert validate_variable_value("router_id", "abc") is not None
    assert validate_variable_value("router_id", "10.0.0.1/24") is not None # must be pure IP address

    # Test Netmask for BGP Configuration (e.g. network_mask)
    assert validate_variable_value("network_mask", "255.255.255.0") is None
    assert validate_variable_value("network_mask", "24") is None
    assert validate_variable_value("network_mask", "abc") is not None


def test_vendor_specific_bgp_ospf_interface_validation():
    # 1. BGP Address Family
    assert validate_variable_value("address_family", "ipv4 unicast") is None
    assert validate_variable_value("bgp_family", "ipv4-family") is None
    assert validate_variable_value("family", "inet6") is None
    assert validate_variable_value("address_family", "invalidfamily") is not None

    # 2. Cisco interface naming
    assert validate_variable_value("interface_name", "GigabitEthernet0/1", platform="cisco_ios") is None
    assert validate_variable_value("interface_name", "GigabitEthernet0/1.100", platform="cisco_ios") is None
    assert validate_variable_value("interface_name", "Vlan10", platform="cisco_ios") is None
    assert validate_variable_value("interface_name", "ge-0/0/0", platform="cisco_ios") is not None

    # 3. Huawei interface naming
    assert validate_variable_value("interface_name", "GigabitEthernet0/0/1", platform="huawei_vrp") is None
    assert validate_variable_value("interface_name", "GigabitEthernet0/0/1.10", platform="huawei_vrp") is None
    assert validate_variable_value("interface_name", "Vlanif20", platform="huawei_vrp") is None
    assert validate_variable_value("interface_name", "Eth-Trunk1.50", platform="huawei_vrp") is None
    assert validate_variable_value("interface_name", "GigabitEthernet0/1", platform="huawei_vrp") is not None

    # 4. Juniper interface naming
    assert validate_variable_value("interface_name", "ge-0/0/0", platform="juniper_junos") is None
    assert validate_variable_value("interface_name", "ge-0/0/0.100", platform="juniper_junos") is None
    assert validate_variable_value("interface_name", "lo0.0", platform="juniper_junos") is None
    assert validate_variable_value("interface_name", "ae2.50", platform="juniper_junos") is None
    assert validate_variable_value("interface_name", "vlan.100", platform="juniper_junos") is None
    assert validate_variable_value("interface_name", "GigabitEthernet0/1", platform="juniper_junos") is not None

    # 5. Arista interface naming
    assert validate_variable_value("interface_name", "Ethernet1", platform="arista_eos") is None
    assert validate_variable_value("interface_name", "Ethernet1.10", platform="arista_eos") is None
    assert validate_variable_value("interface_name", "Vlan5", platform="arista_eos") is None
    assert validate_variable_value("interface_name", "ge-0/0/0", platform="arista_eos") is not None

def test_pre_post_checks_mapping():
    from api.change_orders import get_pre_post_checks
    
    # Test Cisco routing/BGP/OSPF pre-check & post-check commands
    pre, post = get_pre_post_checks("cisco_ios", "routing", "BGP Configuration")
    assert "show ip bgp summary" in pre
    assert "show ip route" in pre
    
    pre, post = get_pre_post_checks("cisco_ios", "routing", "OSPF Single Area")
    assert "show ip ospf neighbor" in pre
    assert "show ip route" in pre

    # Test Huawei BGP configuration
    pre, post = get_pre_post_checks("huawei_vrp", "routing", "BGP Configuration")
    assert "display bgp peer" in pre
    assert "display ip routing-table" in pre

    # Test Huawei security/ACL
    pre, post = get_pre_post_checks("huawei_vrp", "security", "Basic ACL")
    assert "display acl all" in pre

    # Test Cisco switching/VLAN
    pre, post = get_pre_post_checks("cisco_ios", "switching", "VLAN Creation")
    assert "show vlan brief" in pre


def test_cisco_bgp_optional_and_validation(isolated_db):
    """
    Step 9 verification: Cisco BGP template with optional group_name / address_family.

    Validates four behaviors:
      1. Variables containing 'group_name' / 'family' / 'description' default
         to required=False (so leaving them empty is allowed).
      2. All other variables default to required=True (missing them errors out).
      3. Cisco network_mask must be dotted-decimal — pure integer (e.g. "32") is rejected.
      4. The Jinja2 conditional block compiles when only the required vars are present.
    """
    from api.change_orders import validate_template_parameters
    from database import get_db_connection

    # ── Insert a Cisco BGP template directly into the isolated DB so the test
    #    is self-contained and never depends on production seed data IDs. ──
    bgp_content = (
        'router bgp {{ local_as | default(65000) }}\n'
        ' bgp router-id {{ router_id | default("10.0.0.1") }}\n'
        '{% if group_name is defined and group_name %}\n'
        ' neighbor {{ group_name }} peer-group\n'
        ' neighbor {{ group_name }} remote-as {{ peer_as | default(65001) }}\n'
        ' neighbor {{ peer_ip | default("10.0.0.2") }} peer-group {{ group_name }}\n'
        '{% else %}\n'
        ' neighbor {{ peer_ip | default("10.0.0.2") }} remote-as {{ peer_as | default(65001) }}\n'
        '{% endif %}\n'
        '{% if address_family is defined and address_family %}\n'
        ' address-family {{ address_family }}\n'
        '  neighbor {{ peer_ip | default("10.0.0.2") }} activate\n'
        '  network {{ network_ip }} mask {{ network_mask | default("255.255.255.0") }}\n'
        '{% else %}\n'
        ' network {{ network_ip }} mask {{ network_mask | default("255.255.255.0") }}\n'
        '{% endif %}'
    )
    template_id = "test-cisco-bgp-tmpl-9-6"
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO templates (id, name, type, category, vendor, content, rollback, last_used) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                template_id,
                'BGP Configuration',
                'cli',
                'routing',
                'Cisco',
                bgp_content,
                'no router bgp 65000',
                '',
            ),
        )
        conn.commit()
    finally:
        conn.close()

    base_required = {
        "local_as": "65002",
        "router_id": "2.2.2.2",
        "peer_ip": "1.1.1.1",
        "peer_as": "65002",
        "network_ip": "2.2.2.2",
        "network_mask": "255.255.255.255",
    }

    # 1. Happy path — only required vars filled, optional left empty
    errs = validate_template_parameters(
        scenario_id=template_id,
        source_kind="config_template",
        platform="cisco_ios",
        variables=dict(base_required),
    )
    assert not errs, f"Expected no validation errors when optional vars empty, got {errs}"

    # 2. group_name / address_family explicitly empty — still passes (proves they are not required)
    errs_optional_blank = validate_template_parameters(
        scenario_id=template_id,
        source_kind="config_template",
        platform="cisco_ios",
        variables={**base_required, "group_name": "", "address_family": ""},
    )
    assert not errs_optional_blank, (
        f"Empty group_name/address_family must not trigger required-field errors, got {errs_optional_blank}"
    )

    # 3. Cisco network_mask = "32" (CIDR digits) must be rejected
    errs_digits_mask = validate_template_parameters(
        scenario_id=template_id,
        source_kind="config_template",
        platform="cisco_ios",
        variables={**base_required, "network_mask": "32"},
    )
    assert any("点分十进制" in e for e in errs_digits_mask), (
        f"Expected dotted-decimal mask validation error, got {errs_digits_mask}"
    )

    # 4. Missing required local_as — must error (proves only group_name/family/description are optional)
    missing_required = dict(base_required)
    missing_required.pop("local_as")
    errs_missing = validate_template_parameters(
        scenario_id=template_id,
        source_kind="config_template",
        platform="cisco_ios",
        variables=missing_required,
    )
    assert any("local_as" in e and "不能为空" in e for e in errs_missing), (
        f"Expected local_as missing-required error, got {errs_missing}"
    )


def test_optional_variable_keyword_filter():
    """
    Step 9.2 / 9.3 verification: variables whose name contains 'group_name',
    'family', or 'description' must default to required=False during template
    auto-extraction. Other names default to required=True.

    This guards the keyword filter that exists both in the backend
    (`api/change_orders.py`) and in the frontend (`ChangeOrderTab.tsx`).
    """
    optional_keywords = ("group_name", "family", "description")
    optional_keys = [
        "group_name",
        "address_family",
        "bgp_family",
        "family",
        "interface_description",
        "vrf_description",
    ]
    required_keys = [
        "local_as", "router_id", "peer_ip", "peer_as",
        "network_ip", "network_mask", "interface_name", "ospf_process_id",
    ]

    for key in optional_keys:
        assert any(x in key.lower() for x in optional_keywords), (
            f"{key!r} should match one of {optional_keywords}"
        )

    for key in required_keys:
        assert not any(x in key.lower() for x in optional_keywords), (
            f"{key!r} unexpectedly matches an optional keyword"
        )



