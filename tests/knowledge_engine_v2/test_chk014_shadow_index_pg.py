"""CHK-014 acceptance wrapper: PostgreSQL only, never SQLite."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_chk014_postgresql_shadow_index_probe() -> None:
    # This is intentionally an explicit PostgreSQL gate.  A local SQLite
    # compatibility database must not turn this acceptance test green.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "backend")
    probe = Path(__file__).parents[2] / "scripts" / "knowledge_engine_v2_chk014_pg_probe.py"
    result = subprocess.run(
        [sys.executable, str(probe)],
        cwd=str(probe.parents[1]),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"PostgreSQL CHK-014 probe failed; SQLite is not accepted:\n{result.stdout}\n{result.stderr}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS"
    assert payload["database"] == "PostgreSQL"
    assert payload["dual_index"] is True
    assert payload["atomic_cutover"] is True
    assert payload["not_ready_rejected"] is True
    assert payload["tenant_isolation"] is True
    assert payload["rollback"] is True

