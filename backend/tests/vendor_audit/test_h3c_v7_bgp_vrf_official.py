from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import list_templates, smart_parse_cli  # noqa: E402
from services.operational_data_service import resolve_textfsm_template_for_command  # noqa: E402
from services.platform_registry_service import (  # noqa: E402
    PARAMETERIZED_ACTION_DEFINITIONS,
    _coerce_field_types,
    _normalize_records,
    get_profile_action_commands,
)

FIXTURE_DIR = (
    BACKEND_ROOT
    / "tests"
    / "fixtures"
    / "cli"
    / "h3c"
    / "h3c_comware"
    / "display_bgp_peer_ipv4_vpn_instance"
)
FIXTURE_NAME = "comware_v7_s5820v2_s5830v2_vpn1"
EXPECTED_TEMPLATE = "h3c_comware_v7_display_bgp_peer_ipv4_unicast.textfsm"
PROFILE_COMMAND = "display bgp peer ipv4 vpn-instance {{vrf}}"


def _load_fixture() -> tuple[str, dict[str, object]]:
    output = (FIXTURE_DIR / f"{FIXTURE_NAME}.txt").read_text(encoding="utf-8")
    metadata = json.loads(
        (FIXTURE_DIR / f"{FIXTURE_NAME}.meta.json").read_text(encoding="utf-8")
    )
    return output, metadata


def test_official_s5820v2_s5830v2_vrf_bgp_sample_parses_as_comware_v7():
    output, metadata = _load_fixture()

    assert metadata["source_type"] == "official_vendor_documentation"
    assert metadata["source_url"] == "https://www.h3c.com/cn/d_202205/1613284_30005_0.htm"
    assert metadata["command"] == "display bgp peer ipv4 vpn-instance vpn1"
    assert metadata["model_family"] == "S5830V2/S5820V2"
    assert metadata["platform_version"] == "V7"
    assert metadata["software_version"] == "unknown"
    assert metadata["documentation_release"] == "Release 23xx-6W102"
    assert "CMW710" in str(metadata["platform_version_evidence_note"])

    parsed = smart_parse_cli(
        output,
        str(metadata["command"]),
        platform=str(metadata["parser_platform"]),
        version=str(metadata["software_version"]),
        model=str(metadata["model"]),
    )

    assert parsed["success"] is True, parsed.get("message")
    assert parsed["template"] == EXPECTED_TEMPLATE
    assert len(parsed["data"]) == 1
    raw_record = parsed["data"][int(metadata.get("expected_record_index", 0))]
    for field, expected_value in (metadata.get("expected_values") or {}).items():
        assert raw_record[str(field).upper()] == str(expected_value)

    action = next(
        item
        for item in PARAMETERIZED_ACTION_DEFINITIONS
        if item["action_code"] == "get_bgp_neighbors_vrf"
    )
    required_fields = set(action["fields"])
    assert required_fields == {"neighbor", "asn", "state"}
    records = _normalize_records(
        parsed["data"],
        int(action["max_records"]),
        expected_fields=(
            required_fields
            | set(action.get("optional_fields") or [])
            | set(action.get("field_types") or {})
        ),
    )
    _coerce_field_types(records, {"types": action.get("field_types") or {}})

    assert len(records) == 1
    record = records[0]
    assert required_fields <= record.keys()
    assert record["neighbor"] == "10.1.1.1"
    assert record["asn"] == 200
    assert record["state"] == "Established"


def test_v7_quick_ops_vrf_bgp_resolves_parser_without_rewriting_profile_command():
    output, metadata = _load_fixture()
    profile = {"platform_code": "h3c_comware_v7", "parser_platform": "h3c_comware"}
    commands = get_profile_action_commands(profile)

    assert commands["get_bgp_neighbors_vrf"] == PROFILE_COMMAND
    device = {
        "platform": "h3c_comware",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware_v7",
        "profile_parser_platform": "h3c_comware",
        "profile_connection_driver": "hp_comware",
    }
    resolved = resolve_textfsm_template_for_command(
        device,
        commands["get_bgp_neighbors_vrf"],
        action_code="get_bgp_neighbors_vrf",
        templates_catalog=list_templates(vendor_filter="h3c"),
    )

    assert resolved is not None
    assert resolved["textfsm_template"] == EXPECTED_TEMPLATE
    assert commands["get_bgp_neighbors_vrf"] == PROFILE_COMMAND

    # The literal manual command remains the parser input for this sample;
    # Quick Ops resolves the reusable template and leaves the profile command intact.
    parsed = smart_parse_cli(
        output,
        str(metadata["command"]),
        platform=str(metadata["parser_platform"]),
        version=str(metadata["software_version"]),
        model=str(metadata["model"]),
    )
    assert parsed["template"] == resolved["textfsm_template"]
