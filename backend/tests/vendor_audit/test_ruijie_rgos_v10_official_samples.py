from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import list_templates, smart_parse_cli  # noqa: E402


FIXTURE_ROOT = BACKEND_ROOT / "tests" / "fixtures" / "cli" / "ruijie" / "ruijie_rgos"
SAMPLE_PATHS = (
    FIXTURE_ROOT / "show_memory" / "rsr_rgos10_user_guide.meta.json",
    FIXTURE_ROOT / "show_ip_route" / "rsr_rgos10_ospf_r4.meta.json",
    FIXTURE_ROOT / "show_ip_route_vrf" / "rsr_rgos10_rip_vrf_abc.meta.json",
    FIXTURE_ROOT / "show_clock" / "rsr_rgos10_user_guide.meta.json",
)
RSR_TEMPLATE_NAMES = {
    "ruijie_rgos_rsr_v10_show_memory.textfsm",
    "ruijie_rgos_rsr_v10_show_ip_route.textfsm",
    "ruijie_rgos_rsr_v10_show_ip_route_vrf.textfsm",
    "ruijie_rgos_rsr_v10_show_clock.textfsm",
}


@pytest.mark.parametrize("metadata_path", SAMPLE_PATHS, ids=lambda path: path.parent.name)
def test_official_rsr_rgos_v10_sample_selects_its_template_and_matches_contract(metadata_path: Path):
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    output_path = metadata_path.with_suffix("").with_suffix(".txt")
    output = output_path.read_text(encoding="utf-8")

    assert metadata["source_type"] == "official_vendor_documentation"
    assert (urlparse(metadata["source_url"]).hostname or "").endswith(".ruijie.com.cn")
    assert metadata["source_command"] in output
    assert metadata["model_family"] == "RSR series"
    assert metadata["platform_version"] == "v10"
    assert metadata["software_version"] == "unknown"
    assert metadata["parser_platform"] == "ruijie_rgos_rsr_v10"

    result = smart_parse_cli(
        output=output,
        command=metadata["command"],
        platform=metadata["parser_platform"],
        version=metadata["software_version"],
    )

    assert result["success"] is True, result["message"]
    assert result["template"] == metadata["expected_template"]
    assert result["template_source"] in {"builtin", "custom"}
    records = result["data"]
    assert len(records) == metadata["expected_record_count"]
    expected_fields = {str(field).upper() for field in metadata["expected_fields"]}
    actual_fields = {str(field).upper() for record in records for field in record}
    assert expected_fields.issubset(actual_fields)
    index = int(metadata.get("expected_record_index", 0))
    for field, expected in metadata.get("expected_values", {}).items():
        assert str(records[index].get(str(field).upper()) or "") == str(expected)


def test_rsr_templates_are_discovered_only_in_the_rsr_v10_editor_namespace():
    rsr_templates = list_templates(platform_filter="ruijie_rgos_rsr_v10", exact_platform=True)
    assert {item["filename"] for item in rsr_templates} == RSR_TEMPLATE_NAMES
    assert {item["platform_family"] for item in rsr_templates} == {"ruijie_rgos_rsr"}
    assert {item["version"] for item in rsr_templates} == {"v10"}

    generic_v10 = list_templates(platform_filter="ruijie_rgos_v10", exact_platform=True)
    assert not (RSR_TEMPLATE_NAMES & {item["filename"] for item in generic_v10})


@pytest.mark.parametrize("metadata_path", SAMPLE_PATHS, ids=lambda path: path.parent.name)
def test_generic_rgos_v10_parser_never_selects_an_rsr_only_template(metadata_path: Path):
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    output_path = metadata_path.with_suffix("").with_suffix(".txt")
    result = smart_parse_cli(
        output=output_path.read_text(encoding="utf-8"),
        command=metadata["command"],
        platform="ruijie_rgos_v10",
        version="unknown",
    )

    assert result.get("template") not in RSR_TEMPLATE_NAMES
