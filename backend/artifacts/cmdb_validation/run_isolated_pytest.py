"""Run pytest with DATABASE_URL pointed at a disposable local source database.

Usage from the repository root:

    .venv/Scripts/python.exe backend/artifacts/cmdb_validation/run_isolated_pytest.py -q backend/tests

The shared pytest fixtures create and drop their own schema-template and
per-test databases. This wrapper supplies a fresh, empty source database so
the session fixture never initializes the developer's configured application
database. Only loopback PostgreSQL servers are accepted. Credentials stay in
the subprocess environment and are never printed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = _REPO_ROOT / "backend"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: run_isolated_pytest.py <pytest arguments>", file=sys.stderr)
        return 2

    sys.path.insert(0, str(_BACKEND_ROOT))
    sys.path.insert(0, str(_REPO_ROOT))

    import database.core as database_core
    from backend.tests.pg_test_utils import create_test_database, drop_test_database

    source_url = database_core._DATABASE_URL
    parsed = urlparse(source_url)
    if parsed.hostname not in _LOOPBACK_HOSTS:
        print("refusing isolated pytest: configured PostgreSQL host is not loopback", file=sys.stderr)
        return 2

    temporary_source = create_test_database(source_url, purpose="isolated_runner_source")
    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = temporary_source.url
    child_env["NEXORA_ALLOW_REMOTE_TEST_POSTGRES"] = "0"
    existing_pythonpath = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(_BACKEND_ROOT), str(_REPO_ROOT), existing_pythonpath) if part
    )

    print(
        f"isolated_pytest_source={temporary_source.name} "
        f"host={parsed.hostname}:{parsed.port or 5432} "
        "configured application database was not opened"
    )
    result: subprocess.CompletedProcess[bytes] | None = None
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *argv],
            cwd=_REPO_ROOT,
            env=child_env,
            check=False,
        )
    finally:
        drop_test_database(temporary_source)
        print(f"isolated_pytest_source_dropped={temporary_source.name}")

    return result.returncode if result is not None else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
