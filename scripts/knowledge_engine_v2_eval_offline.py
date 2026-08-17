"""Run the frozen KB V2 evaluation gates and emit a deterministic JSON report."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-offline-report-v1.json"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

CHECKS = (
    ("EVAL-001", "scripts/knowledge_engine_v2_eval_dataset_check.py", "validate_dataset"),
    ("EVAL-002", "scripts/knowledge_engine_v2_eval_intent_coverage_check.py", "validate_coverage"),
    ("EVAL-003", "scripts/knowledge_engine_v2_eval_query_type_coverage_check.py", "validate_query_types"),
    ("EVAL-004", "scripts/knowledge_engine_v2_eval_version_coverage_check.py", "validate_versions"),
    ("EVAL-005", "scripts/knowledge_engine_v2_eval_metrics_check.py", "validate_metrics"),
    ("EVAL-006", "scripts/knowledge_engine_v2_eval_quality_metrics_check.py", "validate_quality_metrics"),
    ("EVAL-007", "scripts/knowledge_engine_v2_eval_security_metrics_check.py", "validate_security_metrics"),
    ("EVAL-008", "scripts/knowledge_engine_v2_eval_golden_annotation_check.py", "validate_annotations"),
)


def _load_callable(task_id: str, relative_path: str, function_name: str):
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(f"offline_{task_id.lower()}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {task_id}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, function_name)


def run_offline_evaluation() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for task_id, path, function_name in CHECKS:
        report = _load_callable(task_id, path, function_name)()
        results.append({"task_id": task_id, "status": report.get("status"), "report": report})
    statuses = {str(item["status"]) for item in results}
    status = "PASS" if statuses == {"PASS"} else "FAIL"
    payload: dict[str, Any] = {
        "report_schema_version": 1,
        "evaluation_run": "nexora-kb-v2-offline-eval-v1",
        "status": status,
        "component_count": len(results),
        "components": results,
        "database": "none",
        "sqlite": "not_used",
        "external_network": "not_used",
        "production_write": False,
        "reproducibility": {
            "deterministic_inputs": True,
            "generated_at": None,
            "random_seed": None,
            "command_version": "knowledge_engine_v2_eval_offline_v1",
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--strict", action="store_true", help="exit non-zero unless every component passes")
    args = parser.parse_args()
    report = run_offline_evaluation()
    output = (ROOT / args.output).resolve() if not args.output.is_absolute() else args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "component_count": report["component_count"], "report_sha256": report["report_sha256"]}, ensure_ascii=False))
    return 0 if not args.strict or report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
