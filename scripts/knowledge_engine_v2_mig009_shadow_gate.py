"""MIG-009 V1-primary/V2-shadow retrieval gate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-009"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-009-V1-V2-SHADOW-CONTRACT.yaml"
RETRIEVER_PATH = ROOT / "backend" / "ai" / "services" / "rag_retriever.py"
ASSISTANT_PATH = ROOT / "backend" / "ai" / "services" / "assistant.py"
TRACE_PATH = ROOT / "backend" / "ai" / "services" / "retrieval_trace_store.py"
CONFIG_PATH = ROOT / "backend" / "core" / "config.py"
DB_INDEX_PATH = ROOT / "backend" / "database" / "migrations" / "m0150_retrieval_shadow_generations.py"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-009-shadow-v1.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(_read(CONTRACT_PATH))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("MIG-009 contract task mismatch")
    return payload


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _postgres_probe() -> dict[str, Any]:
    """Read generation inventory in PostgreSQL READ ONLY mode."""
    try:
        from database.core import _USE_PG, get_db_connection
    except Exception as exc:  # pragma: no cover - runner dependency
        return {"status": "BLOCKED", "reason": "DATABASE_MODULE_IMPORT_FAILED", "detail": type(exc).__name__}
    if not _USE_PG or not str(os.environ.get("DATABASE_URL", "")).lower().startswith(("postgresql://", "postgres://")):
        return {"status": "BLOCKED", "reason": "DATABASE_URL_NOT_POSTGRESQL"}
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("BEGIN TRANSACTION READ ONLY")
        exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'ai_retrieval_index_generation'"
        ).fetchone()
        if not exists or int(exists[0] or 0) != 1:
            conn.rollback()
            return {"status": "BLOCKED", "reason": "SHADOW_GENERATION_TABLE_MISSING", "transaction_read_only": True}
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM ai_retrieval_index_generation GROUP BY status ORDER BY status"
        ).fetchall()
        counts = {str(row[0]): int(row[1] or 0) for row in rows}
        tenant_rows = conn.execute(
            "SELECT COUNT(*) FROM ai_retrieval_index_generation WHERE status = 'active' AND tenant_id IS NOT NULL"
        ).fetchone()
        conn.rollback()
        return {
            "status": "PASS",
            "status_counts": counts,
            "active_tenant_scoped_generations": int(tenant_rows[0] or 0),
            "transaction_read_only": True,
        }
    except Exception as exc:  # pragma: no cover - live operator database
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"status": "BLOCKED", "reason": "POSTGRES_SHADOW_PROBE_FAILED", "detail": type(exc).__name__}
    finally:
        if conn is not None:
            conn.close()


def run_gate(*, pg_probe: bool = False) -> dict[str, Any]:
    contract = load_contract()
    retriever = _read(RETRIEVER_PATH)
    assistant = _read(ASSISTANT_PATH)
    trace = _read(TRACE_PATH)
    config = _read(CONFIG_PATH)
    index = _read(DB_INDEX_PATH)
    checks = {
        "contract_postgresql_authority": contract.get("authority") == "PostgreSQL",
        "v1_primary_shadow_seam": _contains(retriever, "def _search_once", "def search", "user_answer_source", "v1_primary_v2_shadow"),
        "shadow_flag_and_v1_default": _contains(retriever, "KNOWLEDGE_V2_SHADOW_READ", "KNOWLEDGE_V2_ENABLED", "active_generation=None") and _contains(config, "KNOWLEDGE_V2_SHADOW_READ", "KNOWLEDGE_V2_ENABLED"),
        "no_double_answer": _contains(retriever, "v1[\"debug\"] = debug", "return v1") and _contains(assistant, "retrieval.get(\"results\")"),
        "tenant_scoped_shadow": _contains(retriever, "generation_tenant != str(request.tenant_id)", "d.tenant_id = ?") and _contains(index, "tenant_id TEXT NOT NULL"),
        "failure_fallback_stable_code": _contains(retriever, "RETRIEVAL_V2_SHADOW_FAILED", "RETRIEVAL_EXECUTION_FAILED"),
        "redacted_comparison": _contains(retriever, "sha256", "v1_top_hashes", "v2_top_hashes") and not _contains(retriever, '"error": str(exc)'),
        "trace_projection": _contains(assistant, '"shadow": debug.get("shadow") or {}') and _contains(trace, '"shadow": {', "v2_only_count", "error_code"),
        "v1_rows_preserved": _contains(index, "V1", "not destructive DDL") and _contains(contract.get("rollback", {}).__str__(), "no_source_or_V1_row_is_deleted_or_replaced"),
        "no_external_or_write": contract.get("security", {}).get("provider_call") is False and contract.get("security", {}).get("database_write") is False,
        "sqlite_not_acceptance": contract.get("security", {}).get("sqlite_acceptance") == "forbidden",
    }
    probe = _postgres_probe() if pg_probe else {"status": "NOT_RUN", "reason": "static_gate_only"}
    static_pass = all(checks.values())
    live_pass = probe.get("status") in {"PASS", "NOT_RUN"}
    report = {
        "task_id": TASK_ID,
        "status": "PASS" if static_pass and live_pass else ("BLOCKED" if probe.get("status") == "BLOCKED" else "FAIL"),
        "reason_codes": [] if static_pass and live_pass else [*(key.upper() for key, value in checks.items() if not value), *([] if probe.get("status") in {"PASS", "NOT_RUN"} else [str(probe.get("reason", "POSTGRES_SHADOW_PROBE_FAILED"))])],
        "checks": checks,
        "postgres_shadow_probe": probe,
        "production_database_write": False,
        "shadow_retrieval_executed_by_gate": False,
        "external_provider_request": False,
        "network_device_write": False,
        "sqlite": "forbidden_for_acceptance",
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-probe", action="store_true", help="run a PostgreSQL READ ONLY shadow-generation inventory")
    args = parser.parse_args()
    print(json.dumps(run_gate(pg_probe=args.pg_probe), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
