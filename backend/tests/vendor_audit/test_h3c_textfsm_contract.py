from pathlib import Path

from core.textfsm import (
    _find_template,
    list_templates,
    resolve_textfsm_platform,
    smart_parse_cli,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli" / "h3c"


def test_all_h3c_parser_inputs_resolve_to_one_public_comware_family():
    for platform in ("h3c", "comware", "h3c_comware", "h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9"):
        assert resolve_textfsm_platform(platform) == "h3c_comware"
    # hp_comware is a Netmiko implementation name, not a TextFSM platform
    # alias in the Nexora catalog.
    assert resolve_textfsm_platform("hp_comware") != "h3c_comware"


def test_h3c_template_lookup_uses_the_canonical_h3c_filename():
    template = _find_template("h3c_comware", "display interface brief")
    assert template is not None
    assert template.name == "h3c_comware_display_interface_brief.textfsm"


def test_internal_h3c_profile_selectors_route_to_explicit_grammar_variants():
    v5_template = _find_template("hp_comware", "display cpu-usage")
    v9_template = _find_template("h3c_comware9", "display interface brief")

    assert v5_template is not None
    assert v5_template.name == "h3c_comware_v5_display_cpu_usage.textfsm"
    assert v9_template is not None
    assert v9_template.name == "h3c_comware_v9_display_interface_brief.textfsm"


def test_h3c_comware_v9_fixture_uses_an_explicit_v9_template_without_losing_records():
    output = (
        FIXTURES
        / "h3c_comware_v9"
        / "display_interface_brief"
        / "comware_v9_cr16000.txt"
    ).read_text(encoding="utf-8")

    result = smart_parse_cli(output, "display interface brief", platform="h3c_comware_v9")

    assert result["success"] is True
    assert result["template"] == "h3c_comware_v9_display_interface_brief.textfsm"
    assert {item["INTERFACE"] for item in result["data"]} == {
        "InLoop0",
        "MGE0/0/0",
        "NULL0",
        "REG0",
        "GE1/0/1",
    }


def test_textfsm_catalog_exposes_one_public_h3c_family_with_explicit_variants():
    h3c = list_templates(platform_filter="h3c_comware", search="bgp", exact_platform=True)

    assert h3c and all(item["platform"] == "h3c_comware" for item in h3c)
    assert {item.get("template_variant") for item in h3c} >= {"v5", "v9", None}
