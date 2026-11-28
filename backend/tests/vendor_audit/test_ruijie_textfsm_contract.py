import io
import sys
from pathlib import Path

import textfsm


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import get_template_content, list_templates, resolve_textfsm_platform, smart_parse_cli


def test_ruijie_rgos_v10_official_version_example_uses_scoped_template():
    fixture = BACKEND_ROOT / "tests" / "fixtures" / "cli" / "ruijie" / "ruijie_rgos" / "show_version" / "rgos_eg1000s.txt"
    output = fixture.read_text(encoding="utf-8")

    result = smart_parse_cli(output, "show version", platform="ruijie_rgos_v10")

    assert result["success"] is True
    assert result["template"] == "ruijie_rgos_v10_show_version.textfsm"
    assert result["matched_rows"] == 1
    record = result["data"][0]
    assert record["SYSTEM_DESCRIPTION"] == "Ruijie EASY GATEWAY(EG1000S) by Ruijie Networks."
    assert record["SYSTEM_HARDWARE_VERSION"] == "1.0"
    assert record["SYSTEM_SOFTWARE_VERSION"] == "RGOS 10.3(4b7), Release(83522)"
    assert record["SYSTEM_BOOT_VERSION"] == "10.3.83522"


def test_ruijie_platform_aliases_show_the_canonical_template_catalog():
    canonical = list_templates(platform_filter="ruijie_rgos")
    legacy = list_templates(platform_filter="ruijie_os")
    short = list_templates(platform_filter="ruijie")

    assert len(canonical) >= 20
    assert {item["filename"] for item in canonical} == {item["filename"] for item in legacy}
    assert {item["filename"] for item in canonical} == {item["filename"] for item in short}
    assert resolve_textfsm_platform("ruijie_os") == "ruijie_rgos"


def test_ruijie_templates_are_all_valid_textfsm_grammars():
    templates = list_templates(platform_filter="ruijie_rgos")
    assert templates

    for item in templates:
        content, source = get_template_content(item["filename"])
        assert source in {"custom", "builtin"}
        parser = textfsm.TextFSM(io.StringIO(content))
        assert parser.header
