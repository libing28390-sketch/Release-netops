from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_promptfoo_report_redacts_variables_and_error_bodies(tmp_path: Path) -> None:
    from promptfoo_gate_report import build_redacted_report, write_junit

    report = build_redacted_report(
        {
            "results": {
                "results": [
                    {
                        "success": True,
                        "testCase": {"description": "ANCHOR-046: secret test", "vars": {"query": "password=fixture"}},
                        "gradingResult": {"componentResults": [{"pass": True}]},
                        "output": "a provider output with a secret",
                    },
                    {
                        "success": False,
                        "testCase": {"description": "ANCHOR-047", "vars": {"query": "tenant-beta"}},
                        "error": "provider returned https://internal.example/key?token=secret",
                        "metadata": {"error_type": "OperationalError", "error_stage": "retrieve_knowledge"},
                        "gradingResult": {"componentResults": [{"pass": False}]},
                    },
                ]
            }
        }
    )
    assert report["case_count"] == 2
    assert report["passed_cases"] == 1
    rendered = json.dumps(report, ensure_ascii=False).casefold()
    assert "password=fixture" not in rendered
    assert "internal.example" not in rendered
    assert "secret test" not in rendered
    assert report["cases"][1]["error_type"] == "OperationalError"
    assert report["cases"][1]["error_stage"] == "retrieve_knowledge"

    junit = tmp_path / "promptfoo.xml"
    write_junit(report, junit)
    assert junit.read_text(encoding="utf-8").startswith("<?xml")
