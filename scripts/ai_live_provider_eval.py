#!/usr/bin/env python3
"""Run an opt-in, metadata-only live Provider intent evaluation.

The evaluator deliberately keeps the live boundary narrow:

* it refuses to call a Provider without ``--allow-live-provider``;
* prompts come from a reviewed, non-sensitive dataset;
* only case IDs, intent labels, status, latency and aggregate token metrics
  are emitted; model response bodies are never written to the report;
* the persisted AI security policy is loaded before the first gateway call.

This is an exploratory measurement harness, not a production request path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "docs" / "knowledge-engine" / "eval" / "ai-dialog-live-provider-v1.json"
LLM_STATUSES = frozenset(
    {
        "llm_success",
        "schema_retry_succeeded",
        "schema_retry_failed",
        "schema_retry_provider_error",
        "provider_error",
    }
)
RETRY_STATUSES = frozenset(
    {"schema_retry_succeeded", "schema_retry_failed", "schema_retry_provider_error"}
)
FORBIDDEN_PROMPT_PATTERNS = (
    re.compile(r"\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|private key)\b", re.I),
    re.compile(r"\b(?:snmp\s+community|bearer\s+token|authorization\s*:)\b", re.I),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b", re.I),
)


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def load_evaluation_dataset(path: Path) -> dict[str, Any]:
    """Load and validate the reviewed dataset without importing application code."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("dataset must contain a cases list")
    if not payload.get("dataset_id"):
        raise ValueError("dataset_id is required")

    seen: set[str] = set()
    for item in payload["cases"]:
        if not isinstance(item, dict):
            raise ValueError("each dataset case must be an object")
        case_id = str(item.get("id") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        expected_intent = str(item.get("expected_intent") or "").strip()
        if not case_id or not prompt or not expected_intent:
            raise ValueError("each dataset case requires id, prompt and expected_intent")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        if any(pattern.search(prompt) for pattern in FORBIDDEN_PROMPT_PATTERNS):
            raise ValueError(f"unsafe live-evaluation prompt: {case_id}")
    return payload


def calculate_live_metrics(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate rates from case metadata, preserving unobserved denominators."""

    status_counts = Counter(str(item.get("parse_status") or "unknown") for item in case_results)
    provider_cases = [item for item in case_results if item.get("parse_status") in LLM_STATUSES]
    retry_cases = [item for item in provider_cases if item.get("parse_status") in RETRY_STATUSES]
    first_pass_success = sum(item.get("parse_status") == "llm_success" for item in provider_cases)
    correction_success = sum(item.get("parse_status") == "schema_retry_succeeded" for item in retry_cases)
    provider_correct = sum(bool(item.get("correct")) for item in provider_cases)
    all_correct = sum(bool(item.get("correct")) for item in case_results)

    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "case_count": len(case_results),
        "provider_backed_case_count": len(provider_cases),
        "deterministic_case_count": sum(item.get("parse_status") == "deterministic" for item in case_results),
        "status_counts": dict(sorted(status_counts.items())),
        "structured_first_pass_success_rate": rate(first_pass_success, len(provider_cases)),
        "structured_correction_success_rate": rate(correction_success, len(retry_cases)),
        "correction_observed_case_count": len(retry_cases),
        "provider_intent_accuracy": rate(provider_correct, len(provider_cases)),
        "overall_intent_accuracy": rate(all_correct, len(case_results)),
    }


def _configured_provider_matrix(get_db_connection: Any) -> list[dict[str, Any]]:
    """Return non-secret provider/model metadata for the report."""

    connection = get_db_connection()
    try:
        rows = connection.execute(
            """
            SELECT p.provider_type, p.health_status, p.enabled,
                   m.model_code, m.enabled
            FROM ai_provider p
            LEFT JOIN ai_model m ON m.provider_id = p.id
            ORDER BY p.provider_type, m.model_code
            """
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "provider_type": str(row[0] or "").lower(),
            "health_status": str(row[1] or "unknown").lower(),
            "enabled": bool(row[2]),
            "model_code": str(row[3] or ""),
            "model_enabled": bool(row[4]) if row[4] is not None else False,
        }
        for row in rows
    ]


def _policy_snapshot(policy: Any) -> dict[str, Any]:
    """Expose only the policy fields needed to audit why the run was allowed."""

    return {
        "external_ai_enabled": bool(getattr(policy, "external_ai_enabled", False)),
        "kill_switch": bool(getattr(policy, "kill_switch", True)),
        "allowed_provider_types": list(getattr(policy, "allowed_provider_types", ())),
        "allowed_classifications": list(getattr(policy, "allowed_classifications", ())),
        "allowed_data_regions": list(getattr(policy, "allowed_data_regions", ())),
        "policy_version": str(getattr(policy, "policy_version", ""))[:64],
    }


async def _run_live_evaluation(
    dataset: dict[str, Any],
    *,
    user_id_prefix: str,
    provider_matrix: list[dict[str, Any]],
    policy: Any,
) -> dict[str, Any]:
    """Run cases sequentially through the existing IntentParser/gateway path."""

    from ai.services.intent_parser import INTENT_PROMPT_VERSION, IntentParser
    from ai.services.metrics import ai_metrics

    parser = IntentParser()
    case_results: list[dict[str, Any]] = []
    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for case in dataset["cases"]:
        case_id = str(case["id"])
        expected_intent = str(case["expected_intent"])
        started = time.perf_counter()
        try:
            result = await parser.parse_intent(
                str(case["prompt"]),
                user_id=f"{user_id_prefix}:{case_id}",
            )
            parse_status = str(result.get("parse_status") or "unknown")
            predicted_intent = str(result.get("intent") or "unknown")
            case_results.append(
                {
                    "case_id": case_id,
                    "expected_intent": expected_intent,
                    "predicted_intent": predicted_intent,
                    "parse_status": parse_status,
                    "confidence": result.get("confidence"),
                    "risk_level": result.get("risk_level"),
                    "needs_clarification": bool(result.get("needs_clarification")),
                    "correct": predicted_intent == expected_intent,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        except Exception as error:  # pragma: no cover - parser normally degrades safely
            case_results.append(
                {
                    "case_id": case_id,
                    "expected_intent": expected_intent,
                    "predicted_intent": "unknown",
                    "parse_status": "runner_error",
                    "error_type": type(error).__name__,
                    "correct": False,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )

    metrics_snapshot = ai_metrics.snapshot()
    metrics = calculate_live_metrics(case_results)
    metrics["provider_observability"] = metrics_snapshot.get("providers", {})
    metrics["gateway_intent_observability"] = metrics_snapshot.get("intent", {})
    metrics["gateway_scope"] = "fresh evaluator process"

    return {
        "status": "measured",
        "report_version": 1,
        "dataset_id": str(dataset["dataset_id"]),
        "intent_prompt_version": INTENT_PROMPT_VERSION,
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "collection_mode": "opt_in_live_provider",
        "external_network": "enabled_by_explicit_flag_and_persisted_policy",
        "security_policy": _policy_snapshot(policy),
        "provider_matrix": provider_matrix,
        "metrics": metrics,
        "cases": case_results,
        "limitations": [
            "This is a reviewed exploratory sample, not the full 24-case offline contract suite.",
            "Correction success is null when no provider response required a schema retry.",
            "Provider token and latency totals are process-scoped gateway observations for this run.",
            "Qwen and Ollama remain unmeasured when no enabled model is configured.",
        ],
    }


def _error_report(reason: str, *, detail: str | None = None) -> int:
    payload: dict[str, Any] = {"status": "not_run", "reason": reason}
    if detail:
        payload["detail"] = detail
    print(_json_dump(payload))
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-live-provider",
        action="store_true",
        help="explicitly authorize the reviewed dataset to cross the configured Provider boundary",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--user-id-prefix", default="codex-live-provider-eval")
    args = parser.parse_args(argv)

    if not args.allow_live_provider:
        return _error_report("explicit_flag_required", detail="rerun with --allow-live-provider after reviewing the dataset")

    try:
        dataset = load_evaluation_dataset(args.dataset)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return _error_report("dataset_invalid", detail=type(error).__name__)

    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from ai.api.security import load_persisted_security_policy
        from ai.security.gateway import ai_security_gateway
        from database.core import get_db_connection

        load_persisted_security_policy()
        policy = ai_security_gateway.policy
        if not bool(getattr(policy, "external_ai_enabled", False)) or bool(getattr(policy, "kill_switch", True)):
            return _error_report("persisted_policy_blocks_external_ai")
        provider_matrix = _configured_provider_matrix(get_db_connection)
        active_models = [
            row
            for row in provider_matrix
            if row["enabled"] and row["model_enabled"] and row["health_status"] not in {"disabled", "unhealthy"}
        ]
        if not active_models:
            return _error_report("no_enabled_healthy_provider_model")
        report = asyncio.run(
            _run_live_evaluation(
                dataset,
                user_id_prefix=str(args.user_id_prefix)[:64],
                provider_matrix=provider_matrix,
                policy=policy,
            )
        )
    except Exception as error:
        # Never expose exception bodies: DB/provider errors can contain URLs or
        # adapter diagnostics. The type is sufficient for the operator to
        # locate the corresponding structured server log.
        return _error_report("live_evaluation_failed", detail=type(error).__name__)

    print(_json_dump(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
