from services.config_template_center_service import (
    infer_variable_schema,
    render_template_center,
    validate_parameters,
)
from services.config_template_validation_service import validate_template


def test_common_template_parameters_use_semantic_types_and_descriptions() -> None:
    source = """
interface {{ interface_name | default("GigabitEthernet1/0/1") }}
 description {{ interface_description | default("ACCESS") }}
 switchport trunk allowed vlan {{ allowed_vlans | default("10,20,30") }}
 ip address {{ network_ip | default("192.0.2.0") }} {{ netmask | default("255.255.255.0") }}
 router-id {{ router_id | default("10.0.0.1") }}
 area {{ area_id | default("0.0.0.0") }}
 network {{ network_ip | default("192.0.2.0") }} {{ wildcard_mask | default("0.0.0.255") }}
"""

    schema = {item["name"]: item for item in infer_variable_schema(source)}

    assert schema["interface_description"]["type"] == "text"
    assert "单行文本" in schema["interface_description"]["description"]
    assert schema["netmask"]["type"] == "ipv4_netmask"
    assert schema["wildcard_mask"]["type"] == "ipv4_wildcard_mask"
    assert schema["router_id"]["type"] == "ipv4_address"
    assert schema["area_id"]["type"] == "ospf_area"
    assert schema["allowed_vlans"]["type"] == "vlan_list"
    assert schema["network_ip"]["type"] == "ipv4_address"


def test_common_template_parameters_validate_and_render_vendor_formats() -> None:
    source = (
        "interface {{ interface_name }}\n"
        " description {{ interface_description }}\n"
        " switchport trunk allowed vlan {{ allowed_vlans }}\n"
        " ip address {{ network_ip }} {{ netmask }}\n"
    )
    schema = infer_variable_schema(source)
    values = {
        "interface_name": "GigabitEthernet1/0/1",
        "interface_description": "USER_ACCESS",
        "allowed_vlans": "10 20 30",
        "network_ip": "192.0.2.0",
        "netmask": "255.255.255.0",
    }

    parameters = validate_parameters(schema, values, vendor="Cisco", platform="cisco_iosxe")
    assert parameters["valid"] is True
    assert parameters["normalized_values"]["allowed_vlans"] == "10,20,30"
    assert parameters["normalized_values"]["interface_description"] == "USER_ACCESS"
    assert parameters["normalized_values"]["netmask"] == "255.255.255.0"

    cidr_parameters = validate_parameters(
        schema,
        {**values, "netmask": "24"},
        vendor="Cisco",
        platform="cisco_iosxe",
    )
    assert cidr_parameters["valid"] is True
    assert cidr_parameters["normalized_values"]["netmask"] == "255.255.255.0"

    rendered = validate_template(
        source,
        variables=parameters["normalized_values"],
        vendor="Cisco",
        platform="cisco_iosxe",
    )
    assert rendered["render_valid"] is True
    assert "switchport trunk allowed vlan 10,20,30" in rendered["rendered"]
    assert "['10', '20', '30']" not in rendered["rendered"]


def test_invalid_netmask_and_wildcard_mask_are_rejected() -> None:
    schema = infer_variable_schema(
        "ip address {{ network_ip }} {{ netmask }}\n"
        "network {{ network_ip }} {{ wildcard_mask }} area {{ area_id }}"
    )
    result = validate_parameters(
        schema,
        {
            "network_ip": "192.0.2.0",
            "netmask": "255.0.255.0",
            "wildcard_mask": "0.255.0.255",
            "area_id": "0.0.0.0",
        },
        vendor="Cisco",
        platform="cisco_iosxe",
    )
    assert result["valid"] is False
    assert {item["field"] for item in result["errors"]} == {"netmask", "wildcard_mask"}


def test_secret_key_and_token_names_are_inferred_and_rendered_safely() -> None:
    source = (
        'key {{ tacacs_key | default("secret123") }}\n'
        'radius key {{ radius_key | default("radius-secret") }}\n'
        'token {{ api_token | default("token-value") }}\n'
        'public {{ public_key | default("ssh-rsa AAAA") }}\n'
    )
    schema = infer_variable_schema(source)
    by_name = {item["name"]: item for item in schema}

    assert by_name["tacacs_key"]["type"] == "password"
    assert by_name["radius_key"]["is_secret"] is True
    assert by_name["api_token"]["is_secret"] is True
    assert by_name["public_key"]["type"] != "password"

    result = render_template_center(
        content=source,
        rollback="",
        schema=schema,
        values={},
        vendor="Cisco",
        platform="cisco_iosxe",
        software_version="17.x",
    )

    assert result["success"] is True
    assert "secret123" not in result["rendered_output"]
    assert "radius-secret" not in result["rendered_output"]
    assert "token-value" not in result["rendered_output"]
    assert result["parameter_validation"]["normalized_values"]["tacacs_key"] == "***"
    assert {item["variable"] for item in result["source_map"]}.isdisjoint(
        {"tacacs_key", "radius_key", "api_token"}
    )
