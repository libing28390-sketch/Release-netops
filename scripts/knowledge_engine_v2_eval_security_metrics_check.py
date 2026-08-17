"""Smoke-check EVAL-007 secret, injection, privilege and outbound metrics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from ai.services.security_evaluation_metrics import evaluate_security_cases


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-security-cases-v1.yaml"
MODULE_PATH = ROOT / "backend" / "ai" / "services" / "security_evaluation_metrics.py"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-security-metrics-v1.manifest.json"


def validate_security_metrics() -> dict[str, Any]:
    fixture = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture.get("schema_version") == 1
    assert fixture.get("status") == "frozen"
    assert fixture.get("source_policy", {}).get("database") == "none"
    assert fixture.get("source_policy", {}).get("sqlite") == "not_used"
    cases = list(fixture.get("cases") or [])
    assert len(cases) == 9
    assert len({str(case.get("id")) for case in cases}) == len(cases)
    by_class: Counter[str] = Counter(str(case.get("class")) for case in cases)
    assert by_class == Counter({"outbound": 3, "secret_leakage": 2, "prompt_injection": 2, "authorization": 2})

    secret_cases = [case for case in cases if case.get("class") == "secret_leakage"]
    injection_cases = [case for case in cases if case.get("class") == "prompt_injection"]
    authorization_cases = [case for case in cases if case.get("class") == "authorization"]
    outbound_cases = [case for case in cases if case.get("class") == "outbound"]
    report = {
        "case_count": len(cases),
        "secret_leakage_rate": evaluate_security_cases(secret_cases)["secret_leakage_rate"],
        "prompt_injection_block_rate": evaluate_security_cases(injection_cases)["prompt_injection_block_rate"],
        "authorization_violation_rate": evaluate_security_cases(authorization_cases)["authorization_violation_rate"],
        "outbound_policy_compliance_rate": evaluate_security_cases(outbound_cases)["outbound_policy_compliance_rate"],
    }
    assert report["case_count"] == 9
    assert report["secret_leakage_rate"] == 0.5
    assert report["prompt_injection_block_rate"] == 1.0
    assert report["authorization_violation_rate"] == 0.5
    assert report["outbound_policy_compliance_rate"] == 2 / 3
    output = {
        "status": "PASS",
        "fixture_id": fixture["fixture_id"],
        "class_counts": dict(sorted(by_class.items())),
        "report": report,
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "secrets": False,
        "fixture_sha256": hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest(),
        "module_sha256": hashlib.sha256(MODULE_PATH.read_bytes()).hexdigest(),
    }
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    print(json.dumps(validate_security_metrics(), ensure_ascii=False))


if __name__ == "__main__":
    main()
