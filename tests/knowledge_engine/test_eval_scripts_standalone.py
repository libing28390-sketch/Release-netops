"""The deterministic evaluation scripts must run from the repository root."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPTS = (
    ROOT / "scripts" / "knowledge_eval_metrics_check.py",
    ROOT / "scripts" / "knowledge_eval_quality_metrics_check.py",
    ROOT / "scripts" / "knowledge_eval_security_metrics_check.py",
)


def test_metric_gate_scripts_do_not_require_external_pythonpath() -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    for script in SCRIPTS:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"{script.name} failed without PYTHONPATH:\n"
            f"stdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
