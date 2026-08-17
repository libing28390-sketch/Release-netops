"""EVAL-011 PostgreSQL-only Provider/Model/Fallback/Security gate."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
_CHECK_SCRIPT = ROOT / "scripts" / "knowledge_engine_v2_eval011_provider_model_security_check.py"
_CHECK_SPEC = importlib.util.spec_from_file_location("eval011_coverage", _CHECK_SCRIPT)
assert _CHECK_SPEC and _CHECK_SPEC.loader
_CHECK_MODULE = importlib.util.module_from_spec(_CHECK_SPEC)
_CHECK_SPEC.loader.exec_module(_CHECK_MODULE)


def test_eval011_freezes_provider_model_security_coverage() -> None:
    report = _CHECK_MODULE.validate_provider_model_security_coverage()
    assert report["status"] == "PASS"
    assert report["task_id"] == "EVAL-011"
    assert report["database"] == "postgresql"
    assert report["sqlite"] == "not_used"
    assert report["rollback"] == "probe_transaction"
    assert report["production_write"] is False
    assert all(report["coverage"].values())


def test_eval011_postgresql_probe_is_required_and_rolls_back() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    assert database_url.startswith(("postgresql://", "postgres://")), (
        "EVAL-011 persistence evidence requires a PostgreSQL DATABASE_URL; SQLite is forbidden"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "knowledge_engine_v2_llm_pg_probe.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    report = json.loads(result.stdout)
    assert report["database"] == "postgresql"
    assert report["rollback"] is True
    assert report["multi_provider"] is True
    assert report["route_fallback"] is True
    assert report["acl_tenant_scoped"] is True
    assert report["key_rotation"] is True
    assert report["key_audit"] is True
    assert report["duplicate_model_rejected"] is True
    assert "postgres://" not in result.stderr.lower()
