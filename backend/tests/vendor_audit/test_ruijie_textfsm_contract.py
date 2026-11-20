import io
import sys
from pathlib import Path

import textfsm


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import get_template_content, list_templates, resolve_textfsm_platform


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
