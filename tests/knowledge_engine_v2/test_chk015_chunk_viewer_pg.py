"""CHK-015 acceptance wrapper; PostgreSQL is the only database backend."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_chk015_postgresql_chunk_viewer_probe() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "backend")
    probe = Path(__file__).parents[2] / "scripts" / "knowledge_engine_v2_chk015_pg_probe.py"
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
        pytest.fail(f"PostgreSQL CHK-015 probe failed; SQLite is not accepted:\n{result.stdout}\n{result.stderr}")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["status"] == "PASS"
    assert payload["database"] == "PostgreSQL"
    assert payload["parent_relation"] is True
    assert payload["neighbor_relation"] is True
    assert payload["metadata_redacted"] is True
    assert payload["tenant_isolation"] is True
    assert payload["rollback"] is True

