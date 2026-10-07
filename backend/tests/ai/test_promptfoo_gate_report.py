from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml


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


def test_promptfoo_provider_path_resolves_from_eval_config_directory() -> None:
    config_path = ROOT / "docs" / "knowledge-engine" / "eval" / "promptfoo-rag-gate.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    provider_id = config["providers"][0]["id"]
    scheme, relative_script = provider_id.split(":", 1)
    provider_path = (config_path.parent / relative_script).resolve()

    assert scheme == "python"
    assert provider_path == ROOT / "scripts" / "promptfoo_nexora_provider.py"
    assert provider_path.is_file()


def test_promptfoo_0118_numeric_failure_reason_does_not_hide_safe_error_category() -> None:
    from promptfoo_gate_report import build_redacted_report

    report = build_redacted_report(
        {
            "results": {
                "results": [
                    {
                        "success": False,
                        "failureReason": 2,
                        "error": "ENOENT: no such file provider secret-token-value",
                    },
                    {"success": False, "failureReason": 1, "error": ""},
                ]
            }
        }
    )

    assert report["cases"][0]["failure_reason"] == "provider_setup_error"
    assert report["cases"][1]["failure_reason"] == "assertion_failure"
    rendered = json.dumps(report, ensure_ascii=False).casefold()
    assert "secret-token-value" not in rendered
    assert "enoent" not in rendered
