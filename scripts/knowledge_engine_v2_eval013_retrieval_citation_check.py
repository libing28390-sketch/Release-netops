"""Run the PostgreSQL-only EVAL-013 retrieval and citation gate."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "EVAL-013-RETRIEVAL-CITATION-CONTRACT.yaml"
RET_PROBE = ROOT / "scripts" / "knowledge_engine_v2_ret_pg_probe.py"
V1_PROBE = ROOT / "scripts" / "knowledge_engine_v2_v1_baseline_pg.py"
RET_TESTS = (
    ROOT / "backend" / "tests" / "ai" / "test_ret_001_003_query_normalizer.py",
    ROOT / "backend" / "tests" / "ai" / "test_ret_004_007_product_resolution.py",
    ROOT / "backend" / "tests" / "ai" / "test_ret_011_020_retrieval_contract.py",
)
CIT_TEST = ROOT / "backend" / "tests" / "ai" / "test_cit_001_010_grounding.py"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "eval-retrieval-citation-v1.manifest.json"


def _read(path: Path) -> str:
    assert path.is_file(), f"missing EVAL-013 authority: {path}"
    return path.read_text(encoding="utf-8")


def _require(text: str, marker: str, label: str) -> None:
    assert marker in text, f"{label} missing marker: {marker}"


def validate_retrieval_citation_coverage() -> dict[str, Any]:
    contract = _read(CONTRACT_PATH)
    ret_probe = _read(RET_PROBE)
    v1_probe = _read(V1_PROBE)
    ret_tests = {path.name: _read(path) for path in RET_TESTS}
    citation_test = _read(CIT_TEST)

    for marker in ("authority: PostgreSQL", "sqlite: forbidden", "transaction_or_cleanup: required", "production_write: false"):
        _require(contract, marker, "EVAL-013 contract")
    for marker in ("_USE_PG", "pg_trgm", "embedding_vector", "tenant_status_scoped_ids", "rollback"):
        _require(ret_probe, marker, "RET PostgreSQL probe")
    for marker in ("_USE_PG", "CREATE TEMP TABLE", "transaction_rollback", "expected_ids"):
        _require(v1_probe, marker, "V1 PostgreSQL baseline")
    for marker in ("normalize_query", "query_hash", "sensitive_literal_redacted"):
        _require(ret_tests["test_ret_001_003_query_normalizer.py"], marker, "query normalizer tests")
    for marker in ("ambiguous", "match_method == \"prefix\"", "match_method == \"none\""):
        _require(ret_tests["test_ret_004_007_product_resolution.py"], marker, "product resolution tests")
    for marker in ("version_compatibility", "train_conflict", "retrieval_cache_key"):
        _require(ret_tests["test_ret_011_020_retrieval_contract.py"], marker, "retrieval contract tests")
    for marker in ("build_grounded_citations", "validate_citations", "refusal_for_missing_evidence", "version_conflict"):
        _require(citation_test, marker, "citation tests")

    return {
        "status": "PASS",
        "task_id": "EVAL-013",
        "database": "postgresql",
        "sqlite": "not_used",
        "coverage": {
            "retrieval": True,
            "citation": True,
            "no_match": True,
            "ambiguous": True,
            "version_conflict": True,
        },
        "persistent_probes": [str(RET_PROBE.relative_to(ROOT)).replace("\\", "/"), str(V1_PROBE.relative_to(ROOT)).replace("\\", "/")],
        "pure_contract_tests": [str(path.relative_to(ROOT)).replace("\\", "/") for path in (*RET_TESTS, CIT_TEST)],
        "production_write": False,
        "source_sha256": {
            "contract": hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            "ret_probe": hashlib.sha256(ret_probe.encode("utf-8")).hexdigest(),
            "v1_probe": hashlib.sha256(v1_probe.encode("utf-8")).hexdigest(),
        },
    }


def _postgres_environment() -> dict[str, str]:
    env = os.environ.copy()
    database_url = env.get("DATABASE_URL", "")
    if not database_url.lower().startswith(("postgresql://", "postgres://")):
        raise RuntimeError("EVAL-013 requires a PostgreSQL DATABASE_URL; SQLite is forbidden")
    env["PYTHONPATH"] = str(ROOT / "backend")
    return env


def _parse_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AssertionError("probe did not emit a JSON object")
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise AssertionError("probe JSON must be an object")
    return value


def _run_probe(path: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(f"{path.name} failed (exit {completed.returncode}): {completed.stdout[-800:]} {completed.stderr[-800:]}")
    report = _parse_json(completed.stdout)
    if str(report.get("database", "")).lower() not in {"postgresql", "postgres"}:
        raise AssertionError(f"{path.name} did not report PostgreSQL")
    if report.get("status") not in {None, "PASS"}:
        raise AssertionError(f"{path.name} did not report PASS")
    return report


def run_postgresql_retrieval_probes() -> dict[str, Any]:
    env = _postgres_environment()
    ret = _run_probe(RET_PROBE, env)
    v1 = _run_probe(V1_PROBE, env)
    retrieval = ret.get("retrieval") or {}
    if ret.get("rollback") != "PASS":
        raise AssertionError("RET probe did not roll back")
    if ret.get("explain", {}).get("captured") is not True:
        raise AssertionError("RET probe did not capture an EXPLAIN plan")
    if not retrieval.get("tenant_status_scoped_ids") or retrieval.get("vector_top_id") != "__ret_pg_probe_chunk_t1":
        raise AssertionError("RET tenant/vector boundary failed")
    cases = {str(case.get("id")): case for case in v1.get("cases", [])}
    if cases.get("Q07", {}).get("returned_ids") != []:
        raise AssertionError("V1 Q07 no-match case returned a result")
    if set(cases.get("Q05", {}).get("returned_ids", [])) != {"ospf-v300", "ospf-v600"}:
        raise AssertionError("V1 Q05 ambiguous broad query did not return bounded candidates")
    for case_id, expected in (("Q03", "ospf-v300"), ("Q04", "ospf-v600")):
        case = cases.get(case_id, {})
        if case.get("returned_ids") != [expected] or case.get("version_conflict") is not False:
            raise AssertionError(f"V1 {case_id} version-specific result is unsafe")
    metrics = v1.get("metrics") or {}
    for metric in ("retrieval_accuracy", "citation_accuracy"):
        if float(metrics.get(metric, -1)) != 1.0:
            raise AssertionError(f"V1 {metric} regressed: {metrics.get(metric)}")
    if float(metrics.get("version_conflict_rate", -1)) != 0.0:
        raise AssertionError("V1 version conflict rate is non-zero")
    return {
        "status": "PASS",
        "task_id": "EVAL-013",
        "database": "postgresql",
        "sqlite": "not_used",
        "retrieval_probe": ret,
        "v1_baseline": v1,
        "no_match": {"case": "Q07", "status": "PASS"},
        "ambiguous": {"case": "Q05", "candidate_count": len(cases["Q05"]["returned_ids"]), "status": "PASS"},
        "version_conflict": {"cases": ["Q03", "Q04"], "rate": metrics["version_conflict_rate"], "status": "PASS"},
        "production_write": False,
        "rollback_or_cleanup": True,
    }


def main() -> int:
    coverage = validate_retrieval_citation_coverage()
    probes = run_postgresql_retrieval_probes()
    output = {**coverage, "probe_results": probes, "rollback_or_cleanup": True}
    REPORT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
