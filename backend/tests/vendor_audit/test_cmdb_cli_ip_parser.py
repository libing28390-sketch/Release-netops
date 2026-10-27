from __future__ import annotations

from pathlib import Path

from core.textfsm import list_templates, template_action_code
from services.operational_data_service import (
    parse_device_cli_output,
    resolve_device_platform_context,
    resolve_textfsm_template_for_command,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = (
    ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "cli"
    / "h3c"
    / "h3c_comware"
    / "display_ip_interface_brief"
)
TEMPLATE_FILENAME = "h3c_comware_v7_display_ip_interface_brief.textfsm"
TEMPLATE_PATH = ROOT / "data" / "textfsm_templates" / TEMPLATE_FILENAME
ACTION_CODE = "get_ip_interfaces"
COMMAND = "display ip interface brief"


def _v7_device() -> dict[str, str]:
    return {
        "id": "cmdb-h3c-v7-device",
        "vendor": "h3c",
        "platform": "h3c_comware",
        "profile_platform_code": "h3c_comware",
        "profile_parser_platform": "h3c_comware",
        "profile_connection_driver": "hp_comware",
    }


def _parse_output(output: str) -> dict:
    return parse_device_cli_output(_v7_device(), COMMAND, output)


def _parse_fixture(filename: str) -> dict:
    return _parse_output((FIXTURE_DIR / filename).read_text(encoding="utf-8"))


def test_shared_v7_template_resolves_action_and_keeps_cidr_rows():
    device = _v7_device()
    context = resolve_device_platform_context(device)
    resolved = resolve_textfsm_template_for_command(
        device, COMMAND, action_code=ACTION_CODE,
    )
    catalog_entry = next(
        item for item in list_templates(vendor_filter="h3c", version_filter="v7")
        if item["filename"] == TEMPLATE_FILENAME
    )

    assert context["parser_platform"] == "h3c_comware_v7"
    assert resolved == {
        "textfsm_template": TEMPLATE_FILENAME,
        "textfsm_source": catalog_entry["source"],
        "template_action_code": ACTION_CODE,
    }
    assert catalog_entry["action_code"] == ACTION_CODE
    assert template_action_code(TEMPLATE_PATH.read_text(encoding="utf-8")) == ACTION_CODE

    result = _parse_fixture("comware_v7_cidr.txt")
    assert result["parse_status"] == "matched"
    assert result["parser"] == f"textfsm:{TEMPLATE_FILENAME}"
    assert result["template"] == TEMPLATE_FILENAME
    assert result["template_action_code"] == ACTION_CODE
    assert result["parser_platform"] == "h3c_comware_v7"
    assert [record["interface"] for record in result["records"]] == [
        "Loop0", "MGE0/0/0", "XGE1/0/49", "Vlan7",
    ]
    assert result["records"][0]["ip_address"] == "192.0.2.1/32"
    assert result["records"][2]["ip_address"] == "198.51.100.1/30"
    assert result["records"][3]["ip_address"] == "203.0.113.1/24"


def test_shared_template_handles_vpn_description_prompt_case_and_spacing_variants():
    result = _parse_fixture("comware_v7_vpn.txt")

    assert result["parse_status"] == "matched"
    records = result["records"]
    assert [record["interface"] for record in records] == [
        "Loop0", "XGE1/0/50", "Vlan7", "Vlan8",
    ]
    assert records[0]["vpn_instance"] == "CORE-VPN"
    assert records[1]["description"] == "Core uplink to aggregation switch"
    assert records[2]["description"] == ""
    assert records[2]["ip_address"] == "203.0.113.2/24"
    assert records[3]["vpn_instance"] == "management-vrf"


def test_shared_template_ignores_prefixed_h3c_prompt_after_table():
    output = (FIXTURE_DIR / "comware_v7_cidr.txt").read_text(encoding="utf-8")
    output += "RBM_S<EDGE-01.\n"

    result = _parse_output(output)

    assert result["parse_status"] == "matched"
    assert len(result["records"]) == 4


def test_header_without_ip_address_mask_is_unmatched():
    output = """Interface Physical Protocol IP VPN instance Description
Loop0 up up 192.0.2.1 -- ROUTER-ID
"""

    result = _parse_output(output)

    assert result["parse_status"] == "unmatched"
    assert result["records"] == []
    assert output not in repr(result)


def test_invalid_data_row_fails_closed_without_partial_records():
    output = (FIXTURE_DIR / "comware_v7_cidr.txt").read_text(encoding="utf-8")
    output += "Not a valid interface row\n"

    result = _parse_output(output)

    assert result["parse_status"] == "unmatched"
    assert result["records"] == []
    assert "Not a valid interface row" not in repr(result)


def test_exact_resolver_isolated_by_action_command_version_and_vendor():
    device = _v7_device()
    assert resolve_textfsm_template_for_command(
        device, " DISPLAY   IP INTERFACE BRIEF ", action_code=ACTION_CODE,
    )["textfsm_template"] == TEMPLATE_FILENAME
    assert resolve_textfsm_template_for_command(
        device, COMMAND, action_code="get_interfaces",
    ) is None
    assert resolve_textfsm_template_for_command(
        device, "display ip interface", action_code=ACTION_CODE,
    ) is None

    v9_device = dict(device, profile_platform_code="h3c_comware9")
    assert resolve_textfsm_template_for_command(
        v9_device, COMMAND, action_code=ACTION_CODE,
    ) is None

    cisco_device = {
        "id": "cmdb-cisco-device",
        "vendor": "cisco",
        "platform": "cisco_ios",
    }
    assert resolve_textfsm_template_for_command(
        cisco_device, COMMAND, action_code=ACTION_CODE,
    ) is None

    other_command_result = parse_device_cli_output(
        device,
        "display ip interface",
        (FIXTURE_DIR / "comware_v7_cidr.txt").read_text(encoding="utf-8"),
    )
    assert other_command_result["template"] != TEMPLATE_FILENAME
