#!/usr/bin/env python3
"""Convert a Promptfoo result into redacted JSON and JUnit artifacts.

Promptfoo's native JSON contains the test variables and provider output.  The
CI artifact should remain useful for a gate without copying prompts, answers,
document text or provider diagnostics into a durable report, so this adapter
keeps only case names, boolean outcomes, assertion counts and bounded error
categories.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree


def _result_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw: Any = payload.get("results")
    if isinstance(raw, Mapping):
        raw = raw.get("results")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _safe_name(value: Any, fallback: str) -> str:
    text = re.sub(
        r"(?i)(password|passwd|secret|token|community|private[_ -]?key|api[_ -]?key)",
        "redacted",
        str(value or "").strip(),
    )
    text = re.sub(r"[^A-Za-z0-9_.:-]+", "_", text)
    return text[:160] or fallback


def _safe_error(value: Any) -> str | None:
    # Error bodies can contain provider URLs, keys or response fragments.  A
    # stable class is enough to locate the server-side diagnostic.
    if value in (None, ""):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        # Promptfoo 0.118.0 uses ResultFailureReason numeric enum values.
        return {0: None, 1: "assertion_failure", 2: "evaluation_error"}.get(value, "evaluation_error")
    text = str(value).casefold()
    if "assert" in text:
        return "assertion_failure"
    if "timeout" in text:
        return "timeout"
    if "enoent" in text or "no such file" in text or "cannot find module" in text:
        return "provider_setup_error"
    if "provider" in text:
        return "provider_error"
    return "evaluation_error"


def _safe_error_type(value: Any) -> str | None:
    """Keep only a Python exception class name in the durable report."""
    if value in (None, ""):
        return None
    text = re.sub(r"[^A-Za-z0-9_.]+", "", str(value))
    return text[:80] or None


def build_redacted_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = _result_rows(payload)
    cases: list[dict[str, Any]] = []
    for index, item in enumerate(rows, start=1):
        grading = item.get("gradingResult") if isinstance(item.get("gradingResult"), Mapping) else {}
        components = grading.get("componentResults") if isinstance(grading.get("componentResults"), list) else []
        metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
        error_text = item.get("error")
        failure_reason = error_text if isinstance(error_text, str) and error_text.strip() else item.get("failureReason")
        cases.append(
            {
                "case": _safe_name(
                    (item.get("testCase") or {}).get("description")
                    if isinstance(item.get("testCase"), Mapping)
                    else None,
                    f"case-{index}",
                ),
                "passed": bool(item.get("success", item.get("pass", False))),
                "failure_reason": _safe_error(failure_reason),
                "error_type": _safe_error_type(metadata.get("error_type")),
                "error_stage": _safe_error_type(metadata.get("error_stage")),
                "assertion_count": len(components),
                "assertion_failed_count": sum(
                    1 for component in components if isinstance(component, Mapping) and not bool(component.get("pass"))
                ),
            }
        )
    passed = sum(bool(item["passed"]) for item in cases)
    return {
        "schema_version": 1,
        "source": "promptfoo",
        "status": "PASS" if cases and passed == len(cases) else "FAIL",
        "case_count": len(cases),
        "passed_cases": passed,
        "failed_cases": len(cases) - passed,
        "cases": cases,
        "redaction": {
            "prompts": False,
            "answers": False,
            "provider_error_bodies": False,
            "secrets": False,
        },
    }


def write_junit(report: Mapping[str, Any], path: Path) -> None:
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": "nexora-promptfoo-gate",
            "tests": str(len(cases)),
            "failures": str(sum(not bool(case.get("passed")) for case in cases if isinstance(case, Mapping))),
        },
    )
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        node = ElementTree.SubElement(suite, "testcase", {"name": str(case.get("case") or "case")})
        if not bool(case.get("passed")):
            failure = ElementTree.SubElement(node, "failure", {"type": str(case.get("failure_reason") or "gate_failure")})
            failure.text = "Promptfoo case failed; inspect the redacted JSON and server-side logs."
    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("Promptfoo result must be a JSON object")
        report = build_redacted_report(payload)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_junit(report, args.junit)
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        print(f"Promptfoo report conversion failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(
        f"Promptfoo redacted report: {report['passed_cases']}/{report['case_count']} passed; "
        f"status={report['status']}"
    )
    if report["failed_cases"]:
        categories = Counter(
            case.get("error_type") or case.get("failure_reason") or "unknown"
            for case in report["cases"]
            if not case.get("passed")
        )
        print(f"Promptfoo failure categories: {dict(categories)}")
    return 1 if args.strict and report["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
