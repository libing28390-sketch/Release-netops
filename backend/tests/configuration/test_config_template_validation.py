from services.config_template_validation_service import validate_template


def test_jinja_template_renders_dotted_variables_in_sandbox() -> None:
    result = validate_template(
        "interface {{ interface.name }}\n description {{ description | upper }}\n",
        variables={
            "interface.name": "GigabitEthernet1/0/1",
            "description": "uplink",
        },
        vendor="Cisco",
        platform="cisco_iosxe",
    )

    assert result["valid"] is True
    assert "interface GigabitEthernet1/0/1" in result["rendered"]
    assert "description UPLINK" in result["rendered"]
    assert result["official_references"][0]["url"].startswith("https://www.cisco.com/")


def test_invalid_jinja_is_rejected_with_line_number() -> None:
    result = validate_template(
        "{% if enabled %}\ninterface Loopback0\n",
        variables={"enabled": True},
        vendor="Huawei",
    )

    assert result["valid"] is False
    assert result["syntax_valid"] is False
    assert result["issues"][0]["code"] == "jinja_syntax"
    assert result["issues"][0]["line"] == 1


def test_missing_variables_fail_render_validation() -> None:
    result = validate_template(
        "router ospf {{ process_id }}",
        variables={},
        vendor="Cisco",
    )

    assert result["syntax_valid"] is True
    assert result["render_valid"] is False
    assert result["missing_variables"] == ["process_id"]


def test_default_filter_variables_render_without_explicit_values() -> None:
    result = validate_template(
        'interface {{ interface_name | default("GigabitEthernet1/0/1") }}\n'
        ' description {{ description | d("ACCESS") }}\n',
        variables={},
        vendor="Cisco",
    )

    assert result["valid"] is True
    assert result["missing_variables"] == []
    assert "interface GigabitEthernet1/0/1" in result["rendered"]
    assert "description ACCESS" in result["rendered"]


def test_invalid_rollback_jinja_is_rejected() -> None:
    result = validate_template(
        "interface Loopback0",
        variables={},
        vendor="Cisco",
        rollback="{% if remove %}\nno interface Loopback0",
    )

    assert result["valid"] is False
    assert result["syntax_valid"] is False
    assert result["issues"][0]["code"] == "rollback_jinja_syntax"


def test_risky_commands_require_rollback_and_are_reported() -> None:
    result = validate_template(
        "configure terminal\nwrite erase\nreload\n",
        variables={},
        vendor="Cisco",
        rollback="",
    )

    assert result["valid"] is True
    assert result["risk_level"] == "critical"
    assert [item["line"] for item in result["risk_items"]] == [2, 3]
    assert any(item["code"] == "missing_rollback" for item in result["warnings"])


def test_cross_vendor_command_family_is_flagged() -> None:
    result = validate_template(
        "system-view\ninterface GigabitEthernet1/0/1\n",
        variables={},
        vendor="Cisco",
    )

    assert any(
        item["code"] == "vendor_command_family_mismatch"
        for item in result["warnings"]
    )
