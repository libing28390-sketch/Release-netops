from __future__ import annotations

import json
from pathlib import Path

from core.textfsm import list_templates, smart_parse_cli
from services.operational_data_service import resolve_textfsm_template_for_command


FIXTURE_DIR = (
    Path(__file__).parents[1]
    / "fixtures"
    / "cli"
    / "h3c"
    / "h3c_comware"
    / "display_lldp_neighbor_information_list"
)
FIXTURE_NAME = "comware_v7_s6850_release_655x"
COMMAND = "display lldp neighbor-information list"
TEMPLATE = "h3c_comware_v7_display_lldp_neighbor_information_list.textfsm"
SOURCE_URL = (
    "https://www.h3c.com/en/Support/Resource_Center/HK/Home/Switches/00-Public/"
    "Reference_Guides/Command_References/H3C_S6850_S9850_CR-Release_655x-6W100/"
    "03/201910/1234788_294551_0.htm"
)


def test_official_s6850_release_655x_lldp_list_replays_one_neighbor():
    metadata = json.loads(
        (FIXTURE_DIR / f"{FIXTURE_NAME}.meta.json").read_text(encoding="utf-8")
    )
    output = (FIXTURE_DIR / f"{FIXTURE_NAME}.txt").read_text(encoding="utf-8")

    assert metadata["source_type"] == "official_vendor_documentation"
    assert metadata["source_url"] == SOURCE_URL
    assert metadata["command"] == COMMAND
    assert metadata["parser_platform"] == "h3c_comware_v7"
    assert metadata["software_version"] == "unknown"
    assert metadata["running_build"] == "unknown"

    result = smart_parse_cli(output, COMMAND, platform="h3c_comware_v7")

    assert result["success"] is True
    assert result["template"] == TEMPLATE
    assert result["data"] == [
        {
            "NEIGHBOR_NAME": "System1",
            "INTERFACE": "WGE1/0/1",
            "CHASSIS_ID": "000f-e25d-ee91",
            "NEIGHBOR_INTERFACE": "Twenty-FiveGigE1/0/1",
        }
    ]


def test_h3c_v7_lldp_action_resolves_to_the_same_template():
    resolved = resolve_textfsm_template_for_command(
        {
            "platform": "h3c_comware",
            "vendor": "H3C",
            "profile_platform_code": "h3c_comware_v7",
            "profile_parser_platform": "h3c_comware_v7",
            "profile_connection_driver": "hp_comware",
        },
        COMMAND,
        action_code="get_lldp_neighbors",
        templates_catalog=list_templates(vendor_filter="h3c"),
    )

    assert resolved is not None
    assert resolved["textfsm_template"] == TEMPLATE
