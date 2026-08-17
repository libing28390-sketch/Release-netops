"""MIG-001 PostgreSQL read-only migration-strategy gate.

This task freezes the strategy for four data layers; it does not migrate or
rewrite production data.  The live probe only reads PostgreSQL catalog/table
metadata and legacy row counts inside a READ ONLY transaction.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "MIG-001"
CONTRACT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "architecture" / "MIG-001-MIGRATION-STRATEGY-CONTRACT.yaml"
REPORT_PATH = ROOT / "docs" / "knowledge-engine-v2" / "eval" / "mig-001-strategy-v1.json"
REQUIRED_LAYERS = ("document", "metadata", "chunk", "embedding")
LEGACY_TABLES = ("ai_document", "ai_document_chunk", "ai_knowledge_base")
V2_TABLES = (
    "kb_document",
    "kb_document_version",
    "kb_chunk_version",
    "kb_chunk",
    "kb_chunk_edge",
    "kb_embedding_model",
    "kb_chunk_embedding",
    "kb_index_version",
)


def load_contract() -> dict[str, Any]:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("MIG-001 contract must be a mapping")
    if payload.get("task_id") != TASK_ID or payload.get("authority") != "PostgreSQL":
        raise AssertionError("MIG-001 contract authority/task mismatch")
    if payload.get("sqlite") != "forbidden_for_acceptance":
        raise AssertionError("MIG-001 must forbid SQLite acceptance evidence")
    layers = payload.get("layers") or {}
    missing = [name for name in REQUIRED_LAYERS if not isinstance(layers.get(name), dict)]
    if missing:
        raise AssertionError(f"MIG-001 layer strategy missing: {','.join(missing)}")
    for name in REQUIRED_LAYERS:
        layer = layers[name]
        for key in ("legacy_authority", "v2_target", "confidence_grade", "strategy", "rollback", "acceptance"):
            if not layer.get(key):
                raise AssertionError(f"MIG-001 {name} missing {key}")
    return payload


def _catalog_probe() -> dict[str, Any]:
    from database import core

    if not core._USE_PG:
        raise RuntimeError("MIG-001 requires PostgreSQL; SQLite is forbidden")
    conn = core.get_db_connection()
    tables = LEGACY_TABLES + V2_TABLES
    table_status: dict[str, dict[str, Any]] = {}
    try:
        conn.execute("BEGIN READ ONLY")
        read_only = str(conn.execute("SHOW transaction_read_only").fetchone()[0]).lower() == "on"
        database_name = str(conn.execute("SELECT current_database()").fetchone()[0])
        schema_name = str(conn.execute("SELECT current_schema()").fetchone()[0])
        server_version = str(conn.execute("SHOW server_version").fetchone()[0]).split()[0]
        for table in tables:
            exists = bool(
                conn.execute(
                    "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?",
                    (table,),
                ).fetchone()
            )
            row_count = None
            if exists:
                row_count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            table_status[table] = {"exists": exists, "row_count": row_count}
        conn.rollback()
    finally:
        conn.close()
    legacy_present = all(table_status[name]["exists"] for name in LEGACY_TABLES[:2])
    return {
        "status": "PASS" if read_only and legacy_present else "FAIL",
        "database": "PostgreSQL",
        "database_name_present": bool(database_name),
        "schema": schema_name,
        "server_version": server_version,
        "transaction_read_only": read_only,
        "tables": table_status,
        "production_database_write": False,
        "rollback": "read_only_transaction_rollback",
        "sqlite": "forbidden",
    }


def run_gate() -> dict[str, Any]:
    started = time.perf_counter()
    contract = load_contract()
    catalog = _catalog_probe()
    layers = contract["layers"]
    return {
        "status": "PASS" if catalog["status"] == "PASS" else "FAIL",
        "task_id": TASK_ID,
        "authority": "PostgreSQL",
        "sqlite": "forbidden",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "contract_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        "layers": {
            name: {
                "confidence_grade": layers[name]["confidence_grade"],
                "strategy": layers[name]["strategy"],
                "rollback": layers[name]["rollback"],
            }
            for name in REQUIRED_LAYERS
        },
        "execution_order": contract["execution_order"],
        "automatic_migration_allowed": False,
        "catalog_probe": catalog,
        "external_calls": False,
        "report_redacted": True,
    }


def main() -> int:
    try:
        report = run_gate()
    except Exception as exc:
        report = {"status": "ERROR", "task_id": TASK_ID, "error_type": type(exc).__name__}
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
