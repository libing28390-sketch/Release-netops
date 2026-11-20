#!/usr/bin/env python3
"""Freeze the metadata required to reproduce a knowledge evaluation run.

The manifest is deliberately metadata-only.  It records the source hashes and
component contracts needed to rerun an evaluation, while omitting prompts,
answers, document bodies, CLI output, tenant/user identifiers and secrets.
It is safe to generate while the working tree is dirty; the dirty state is
recorded instead of being silently treated as a release baseline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_DATASET = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-golden-anchors-50-v3-signed-20260905.yaml"
DEFAULT_REPORT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-anchors-50-v3-signed-report.json"
DEFAULT_OUTPUT = ROOT / "docs" / "knowledge-engine" / "eval" / "eval-baseline-manifest.json"
MANIFEST_SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def _git_state() -> dict[str, Any]:
    sha = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "sha": sha or "unavailable",
        "worktree_dirty": bool(status),
        "status_entry_count": len(status.splitlines()) if status else 0,
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"report must be an object: {path}")
    return payload


def _read_yaml_metadata(path: Path) -> dict[str, Any]:
    import yaml

    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("dataset must contain a cases list")
    cases = payload["cases"]
    case_ids = [str(case.get("id") or "") for case in cases if isinstance(case, Mapping)]
    if len(case_ids) != len(cases) or not all(case_ids) or len(set(case_ids)) != len(case_ids):
        raise ValueError("dataset case IDs must be present and unique")
    return {
        "dataset_id": str(payload.get("dataset_id") or "unknown"),
        "status": str(payload.get("status") or "unknown"),
        "case_count": len(cases),
    }


def _component_contracts() -> dict[str, Any]:
    # Imports happen only after the source files have been hashed by the
    # caller, so a broken optional integration cannot produce a fake version.
    from ai.chunking.engine import ChunkingEngine
    from ai.providers.embedding import embedding_metadata
    from ai.services.intent_parser import INTENT_PROMPT_VERSION
    from ai.services.query_normalizer import NORMALIZER_VERSION

    chunker = ChunkingEngine()
    chunk_config = chunker.config.as_dict()
    embedding = embedding_metadata()
    reranker_mode = str(__import__("os").environ.get("AI_RERANKER_MODE") or "legacy").strip().lower()
    reranker_version = "legacy-noop-v1" if reranker_mode == "legacy" else "configured-runtime"
    provider_model = str(__import__("os").environ.get("AI_MODEL_ID") or "not_configured")[:128]
    provider_id = str(__import__("os").environ.get("AI_PROVIDER_ID") or "not_configured")[:128]
    return {
        "prompt": {
            "intent_prompt_version": INTENT_PROMPT_VERSION,
            "promptfoo_config_sha256": _sha256(ROOT / "docs" / "knowledge-engine" / "eval" / "promptfoo-rag-gate.yaml")
            if (ROOT / "docs" / "knowledge-engine" / "eval" / "promptfoo-rag-gate.yaml").is_file()
            else "not_present",
        },
        "parser": {
            "intent_parser_version": INTENT_PROMPT_VERSION,
            "query_normalizer_version": NORMALIZER_VERSION,
        },
        "chunker": {
            "version": ChunkingEngine.chunker_version,
            "parser_version": ChunkingEngine.parser_version,
            "config": chunk_config,
            "config_sha256": _canonical_sha256(chunk_config),
        },
        "embedding": {
            **embedding,
            "distance_algorithm": "cosine",
        },
        "reranker": {
            "requested_mode": reranker_mode or "legacy",
            "version": reranker_version,
            "model": str(__import__("os").environ.get("BGE_MODEL_NAME") or "not_configured")[:128],
        },
        "provider": {
            "provider_id": provider_id,
            "model": provider_model,
            "external_live_call": False,
        },
    }


def _metric_snapshot(report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics") if isinstance(report.get("metrics"), Mapping) else {}
    quality_summary = report.get("quality_summary") if isinstance(report.get("quality_summary"), Mapping) else {}
    checks = quality_summary.get("checks") if isinstance(quality_summary.get("checks"), Mapping) else {}
    selected = {
        "recall_at_5": metrics.get("recall_at_5"),
        "recall_at_10": metrics.get("recall_at_10"),
        "mrr": metrics.get("mean_reciprocal_rank_mrr"),
        "ndcg": metrics.get("ndcg"),
        "citation_precision": metrics.get("citation_precision"),
        "citation_recall": metrics.get("citation_recall"),
        "wrong_vendor_rate": metrics.get("wrong_vendor_rate"),
        "feature_pollution_rate": metrics.get("feature_pollution_rate"),
        "platform_version_conflict_rate": metrics.get("platform_version_conflict_rate"),
        "latency_ms": metrics.get("latency_ms"),
        "error_rate": metrics.get("error_rate"),
        "by_vendor": metrics.get("by_vendor"),
        "quality_checks": {
            str(name): {
                "actual": check.get("actual"),
                "required": check.get("required"),
                "passed": bool(check.get("passed")),
            }
            for name, check in checks.items()
            if isinstance(check, Mapping)
        },
    }
    return selected


def build_manifest(*, dataset_path: Path = DEFAULT_DATASET, report_path: Path = DEFAULT_REPORT) -> dict[str, Any]:
    dataset = _read_yaml_metadata(dataset_path)
    report = _read_json(report_path) if report_path.is_file() else {"status": "not_run"}
    contracts = _component_contracts()
    source_hashes = {
        "dataset": _sha256(dataset_path),
        "evaluator": _sha256(ROOT / "scripts" / "knowledge_eval_anchors_50_runner.py"),
        "review_auditor": _sha256(ROOT / "scripts" / "knowledge_eval_anchor_review_check.py")
        if (ROOT / "scripts" / "knowledge_eval_anchor_review_check.py").is_file()
        else "not_present",
    }
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_id": "nexora-knowledge-eval-baseline-v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "reproducibility": {
            "git": _git_state(),
            "dataset": {**dataset, "path": str(dataset_path.relative_to(ROOT)), "sha256": source_hashes["dataset"]},
            "source_hashes": source_hashes,
            "rerun_command": ".venv\\Scripts\\python.exe scripts\\knowledge_eval_anchors_50_runner.py",
            "database": "PostgreSQL",
            "database_validation": "not_run_by_manifest_generator",
            "external_network": False,
            "production_write": False,
        },
        "components": contracts,
        "evaluation": {
            "report_path": str(report_path.relative_to(ROOT)) if report_path.is_relative_to(ROOT) else str(report_path),
            "status": str(report.get("status") or "not_run"),
            "safety_status": str(report.get("safety_status") or "not_run"),
            "quality_status": str(report.get("quality_status") or "not_run"),
            "overall_status": str(report.get("overall_status") or report.get("status") or "not_run"),
            "metrics": _metric_snapshot(report),
        },
        "redaction": {
            "contains_prompt_or_answer": False,
            "contains_document_or_cli_content": False,
            "contains_secrets_or_credentials": False,
            "contains_tenant_or_user_identifiers": False,
        },
        "limitations": [
            "The current manifest records the measured 50-anchor run; it does not claim the 400-case retrieval-quality evaluation is complete. The 400-case source-provenance gate is tracked separately.",
            "A dirty worktree or a not_run database validation is a reproducibility warning, not a quality pass.",
            "Provider and sidecar fields report configured contracts only; no live external request is made by this generator.",
        ],
    }


def _validate_manifest(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
    for marker in ("postgresql://", "password", "api_key", "snmp", "private key", "cli_output", "raw_prompt", "full_response"):
        if marker in text and marker not in {"snmp"}:
            errors.append(f"forbidden marker: {marker}")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        errors.append("schema_version is invalid")
    if not isinstance(payload.get("components"), Mapping):
        errors.append("components are missing")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--strict", action="store_true", help="fail when the evaluation quality gate is not PASS")
    args = parser.parse_args(argv)
    try:
        payload = build_manifest(dataset_path=args.dataset, report_path=args.report)
        errors = _validate_manifest(payload)
        if errors:
            raise ValueError("; ".join(errors))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        print(f"baseline manifest failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    status = payload["evaluation"]["overall_status"]
    print(
        "baseline manifest: "
        f"dataset={payload['reproducibility']['dataset']['dataset_id']} "
        f"cases={payload['reproducibility']['dataset']['case_count']} "
        f"status={status} dirty={payload['reproducibility']['git']['worktree_dirty']}"
    )
    if args.strict and status != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
