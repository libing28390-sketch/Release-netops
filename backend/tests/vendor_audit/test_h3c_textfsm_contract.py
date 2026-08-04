from pathlib import Path

from core.textfsm import (
    _find_template,
    list_templates,
    resolve_textfsm_platform,
    smart_parse_cli,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli" / "h3c"


def test_all_h3c_parser_aliases_resolve_to_ntc_comware_family():
    for platform in ("h3c", "comware7", "h3c_comware", "h3c_comware9", "hp_comware"):
        assert resolve_textfsm_platform(platform) == "hp_comware"


def test_h3c_template_lookup_prefers_canonical_hp_comware_filename():
    template = _find_template("h3c_comware", "display interface brief")
    assert template is not None
    assert template.name == "hp_comware_display_interface_brief.textfsm"


def test_h3c_comware9_fixture_uses_hp_parser_namespace_without_losing_records():
    output = (
        FIXTURES
        / "h3c_comware9"
        / "display_interface_brief"
        / "comware_v9_cr16000.txt"
    ).read_text(encoding="utf-8")

    result = smart_parse_cli(output, "display interface brief", platform="h3c_comware9")

    assert result["success"] is True
    assert result["template"] == "hp_comware_display_interface_brief.textfsm"
    assert {item["INTERFACE"] for item in result["data"]} == {
        "InLoop0",
        "MGE0/0/0",
        "NULL0",
        "REG0",
        "GE1/0/1",
    }


def test_textfsm_catalog_can_filter_one_netmiko_platform_without_alias_duplicates():
    v5 = list_templates(platform_filter="hp_comware", search="bgp", exact_platform=True)
    v7 = list_templates(platform_filter="h3c_comware", search="bgp", exact_platform=True)
    v9 = list_templates(platform_filter="h3c_comware9", search="bgp", exact_platform=True)

    assert v5 and all(item["platform"] == "hp_comware" for item in v5)
    assert v7 and all(item["platform"] == "h3c_comware" for item in v7)
    assert v9 and all(item["platform"] == "h3c_comware9" for item in v9)
