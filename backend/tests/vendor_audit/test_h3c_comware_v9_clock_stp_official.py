from __future__ import annotations

import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import list_templates, smart_parse_cli  # noqa: E402
from services.operational_data_service import resolve_textfsm_template_for_command  # noqa: E402
from services.platform_registry_service import get_profile_action_commands  # noqa: E402

FIXTURE_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "cli" / "h3c" / "h3c_comware_v9"
CASES = (
    (
        "display_clock",
        "comware_v9_s9827_r932x_6w100",
        "get_clock",
        "display clock",
        "h3c_comware_v9_display_clock.textfsm",
    ),
    (
        "display_stp_brief",
        "comware_v9_s9855_r932x_6w102",
        "get_stp",
        "display stp brief",
        "h3c_comware_v9_display_stp_brief.textfsm",
    ),
)


def _load_case(directory: str, basename: str) -> tuple[str, dict]:
    sample_dir = FIXTURE_ROOT / directory
    output = (sample_dir / f"{basename}.txt").read_text(encoding="utf-8")
    metadata = json.loads(
        (sample_dir / f"{basename}.meta.json").read_text(encoding="utf-8")
    )
    return output, metadata


def test_official_clock_and_stp_examples_parse_with_version_specific_templates():
    for directory, basename, _action, command, template in CASES:
        output, metadata = _load_case(directory, basename)
        assert metadata["source_type"] == "official_vendor_documentation"
        assert metadata["source_url"].startswith("https://www.h3c.com/")
        assert metadata["command"] == command
        assert metadata["platform_version"] == "V9"
        assert metadata["software_version"] == "unknown"
        assert metadata["documentation_release"]
        assert metadata["expected_template"] == template

        parsed = smart_parse_cli(
            output,
            command,
            platform=metadata["parser_platform"],
            version=metadata["software_version"],
            model=metadata["model"],
        )
        assert parsed["success"] is True, parsed.get("message")
        assert parsed["template"] == template
        assert len(parsed["data"]) == metadata["expected_record_count"]
        actual_fields = {key for record in parsed["data"] for key in record}
        assert set(metadata["expected_fields"]).issubset(actual_fields)
        for field, expected_value in metadata["expected_values"].items():
            assert parsed["data"][metadata["expected_record_index"]][field] == expected_value
        for expected_record in metadata.get("expected_records", []):
            for field, expected_value in expected_record["values"].items():
                assert parsed["data"][expected_record["index"]][field] == expected_value


def test_v9_quick_ops_keeps_release_commands_and_resolves_v9_templates():
    catalog = list_templates(vendor_filter="h3c")
    device = {
        "platform": "h3c_comware_v9",
        "vendor": "H3C",
        "profile_platform_code": "h3c_comware_v9",
        "profile_parser_platform": "h3c_comware_v9",
        "profile_connection_driver": "hp_comware",
    }
    commands = get_profile_action_commands(
        {"platform_code": "h3c_comware_v9", "parser_platform": "h3c_comware"}
    )

    for _directory, _basename, action_code, command, template in CASES:
        assert commands[action_code] == command
        resolved = resolve_textfsm_template_for_command(
            device,
            command,
            action_code=action_code,
            templates_catalog=catalog,
        )
        assert resolved is not None
        assert resolved["textfsm_template"] == template
        assert resolved["template_action_code"] == action_code

    legacy_v9_commands = get_profile_action_commands(
        {"platform_code": "h3c_comware9", "parser_platform": "h3c_comware"}
    )
    assert legacy_v9_commands["get_clock"] == "display clock"
    assert legacy_v9_commands["get_stp"] == "display stp brief"
