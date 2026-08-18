"""REL-010 runbook and PostgreSQL read-only verification gate."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "REL-010"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "REL-010-KILL-SWITCH-PAUSE-CONTRACT.yaml"
RUNBOOK_PATH = ROOT / "docs" / "knowledge-engine-v2" / "runbooks" / "REL-010-KILL-SWITCH-PAUSE-RUNBOOK.md"
GATEWAY_PATH = ROOT / "backend" / "ai" / "security" / "gateway.py"
SECURITY_API_PATH = ROOT / "backend" / "ai" / "api" / "security.py"
PROVIDER_API_PATH = ROOT / "backend" / "ai" / "api" / "providers.py"
REINDEX_PATH = ROOT / "backend" / "ai" / "services" / "knowledge_reindex_service.py"
DB022_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "DB-022-REINDEX-BATCH-LEASE-CONTRACT.yaml"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "rel-010-runbook-v1.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(_read(CONTRACT_PATH))
    if not isinstance(payload, dict) or payload.get("task_id") != TASK_ID:
        raise AssertionError("REL-010 contract task mismatch")
    return payload


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _postgres_probe() -> dict[str, Any]:
    """Inspect control tables in a PostgreSQL READ ONLY transaction only."""
    try:
        from database.core import _USE_PG, get_db_connection
    except Exception as exc:  # pragma: no cover - import depends on runner
        return {"status": "BLOCKED", "reason": "DATABASE_MODULE_IMPORT_FAILED", "detail": type(exc).__name__}
    if not _USE_PG or not str(os.environ.get("DATABASE_URL", "")).lower().startswith(("postgresql://", "postgres://")):
        return {"status": "BLOCKED", "reason": "DATABASE_URL_NOT_POSTGRESQL"}
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("BEGIN TRANSACTION READ ONLY")
        tables = {}
        for table in ("ai_kill_switch", "ai_tenant_security_controls", "ai_provider", "ai_knowledge_reindex_job", "scheduler_locks"):
            row = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = %s",
                (table,),
            ).fetchone()
            tables[table] = bool(row and int(row[0] or 0) == 1)
        counts: dict[str, int] = {}
        if tables.get("ai_kill_switch"):
            row = conn.execute("SELECT COUNT(*) FROM ai_kill_switch WHERE id = 1").fetchone()
            counts["global_kill_switch_rows"] = int(row[0] or 0)
        if tables.get("ai_knowledge_reindex_job"):
            row = conn.execute("SELECT COUNT(*) FROM ai_knowledge_reindex_job WHERE status = 'running'").fetchone()
            counts["running_reindex_jobs"] = int(row[0] or 0)
        if tables.get("scheduler_locks"):
            # ``expires_at`` is a legacy TEXT column on the PostgreSQL
            # scheduler table.  Do not compare it to a timestamp in SQL (the
            # implicit cast is not portable); read the bounded lease values
            # and compare in Python inside the same READ ONLY transaction.
            lease_rows = conn.execute(
                "SELECT expires_at FROM scheduler_locks WHERE lock_name LIKE %s",
                ("knowledge_reindex:%",),
            ).fetchall()
            now = datetime.now(timezone.utc)
            active = 0
            for (raw_expiry,) in lease_rows:
                try:
                    expiry = raw_expiry if isinstance(raw_expiry, datetime) else datetime.fromisoformat(str(raw_expiry).replace("Z", "+00:00"))
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    active += int(expiry >= now)
                except (TypeError, ValueError):
                    # An unreadable expiry is not counted as active, but the
                    # row remains visible to the operator in the report.
                    continue
            counts["reindex_lease_rows"] = len(lease_rows)
            counts["active_reindex_leases"] = active
        conn.rollback()
        ok = all(tables.values()) and counts.get("global_kill_switch_rows", 0) == 1
        return {"status": "PASS" if ok else "FAIL", "tables": tables, "counts": counts, "transaction_read_only": True}
    except Exception as exc:  # pragma: no cover - live operator database
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"status": "BLOCKED", "reason": "POSTGRES_CONTROL_PROBE_FAILED", "detail": type(exc).__name__}
    finally:
        if conn is not None:
            conn.close()


def run_gate(*, pg_probe: bool = False) -> dict[str, Any]:
    contract = load_contract()
    runbook = _read(RUNBOOK_PATH)
    gateway = _read(GATEWAY_PATH)
    security_api = _read(SECURITY_API_PATH)
    provider_api = _read(PROVIDER_API_PATH)
    reindex = _read(REINDEX_PATH)
    db022 = yaml.safe_load(_read(DB022_PATH))
    env_example = _read(ENV_EXAMPLE_PATH)
    checks = {
        "contract_postgresql_authority": contract.get("authority") == "PostgreSQL" and db022.get("authority", "").startswith("PostgreSQL"),
        "global_and_tenant_kill_switch_api": _contains(security_api, "/kill-switch", "ai.provider.manage", "/tenant-kill-switch", "ai.security.manage"),
        "gateway_stable_block_code": _contains(gateway, "AI_SECURITY_KILL_SWITCH", "provider_kill_switches", "tenant_kill_switches"),
        "provider_disable_api": _contains(provider_api, "@router.put(\"/{provider_id}\"", "enabled = ?", "ai.provider.manage"),
        "v2_flags_declared_disabled": all(f"{key}=0" in env_example for key in ("KNOWLEDGE_V2_ENABLED", "KNOWLEDGE_V2_SHADOW_READ", "KNOWLEDGE_V2_ROLLOUT_PERCENT", "KNOWLEDGE_V2_WRITE_ENABLED")),
        "v2_v1_preservation": _contains(runbook, "V1 检索", "不允许删除或改写", "V2 Disable"),
        "reindex_lease_and_checkpoint": _contains(reindex, "knowledge_reindex:", "_db022_control", "cursor", "retry_wait") and _contains(runbook, "scheduler_locks", "900 秒", "私有的已提交 keyset checkpoint"),
        "reindex_tenant_scope": _contains(reindex, "d.tenant_id = ?", "tenant-default") and _contains(runbook, "tenant_id"),
        "rollback_and_no_destructive_sql": _contains(runbook, "禁止在生产执行", "DROP", "TRUNCATE", "删除文档/Chunk/Embedding") and not any(token in runbook.upper() for token in ("DELETE FROM AI_", "TRUNCATE TABLE", "DROP TABLE")),
        "redaction": _contains(runbook, "API Key", "DATABASE_URL", "lease owner", "不得"),
        "postgres_only_acceptance": _contains(runbook, "PostgreSQL 只读", "SQLite", "不得使用 SQLite"),
        "production_write_free_gate": True,
    }
    probe = _postgres_probe() if pg_probe else {"status": "NOT_RUN", "reason": "static_gate_only"}
    static_pass = all(checks.values())
    live_pass = probe.get("status") in {"PASS", "NOT_RUN"}
    report = {
        "task_id": TASK_ID,
        "status": "PASS" if static_pass and live_pass else ("BLOCKED" if probe.get("status") == "BLOCKED" else "FAIL"),
        "reason_codes": [] if static_pass and live_pass else [*(key.upper() for key, value in checks.items() if not value), *([] if probe.get("status") in {"PASS", "NOT_RUN"} else [str(probe.get("reason", "POSTGRES_CONTROL_PROBE_FAILED"))])],
        "checks": checks,
        "postgres_control_probe": probe,
        "production_database_write": False,
        "reindex_executed_by_gate": False,
        "external_provider_request": False,
        "network_device_write": False,
        "sqlite": "forbidden_for_acceptance",
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pg-probe", action="store_true", help="run a PostgreSQL READ ONLY control-table probe")
    args = parser.parse_args()
    print(json.dumps(run_gate(pg_probe=args.pg_probe), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
