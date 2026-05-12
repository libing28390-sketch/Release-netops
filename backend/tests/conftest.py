"""
Shared pytest fixtures for change-order-management bugfix spec tests.

Strategy:
  - Point `database.DB_PATH` at an isolated per-test temp SQLite file before
    `init_db()` runs so we never touch the real `data/netops.db`.
  - Reset the `_db_initialized` guard so each test gets a fresh schema
    identical to production.
  - Call handler functions in `backend/api/change_orders.py` DIRECTLY,
    bypassing FastAPI routing / license middleware / auth middleware. This
    lets us assert the exact business-logic behavior that the bugfix tasks
    target, without fighting the platform layer.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
import sqlite3
import queue
from datetime import datetime, timezone

import pytest

# ── CRITICAL: Force SQLite mode BEFORE any import of `database` module ──
# The database module conditionally imports sqlite3 and defines pool classes
# only when _USE_PG is False at import time. We must ensure DATABASE_URL is
# empty before the module is first loaded.
# NOTE: database.py uses load_dotenv(override=True) which would re-read .env
# and override our setting. We patch dotenv.load_dotenv to be a no-op.
os.environ["DATABASE_URL"] = ""
import dotenv
dotenv.load_dotenv = lambda *a, **kw: None  # type: ignore[assignment]

# Make `backend/` importable as top-level package root.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Now import database — it will see DATABASE_URL="" and use SQLite path,
# defining _pool, _PooledConnection, etc.
import database  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """
    Create a temp SQLite DB and wire it into `database` module as DB_PATH.
    Returns a dict with `db_path` and helper accessors.
    """
    # Ensure SQLite backend regardless of inherited env.
    monkeypatch.setenv("DATABASE_URL", "")
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = str(data_dir / "netops.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    monkeypatch.setattr(database, "DB_PATH", db_path, raising=True)
    # Reset the init-once guard so init_db can re-create the schema in our DB.
    monkeypatch.setattr(database, "_db_initialized", False, raising=True)
    # Force SQLite code path (should already be False from module load).
    monkeypatch.setattr(database, "_USE_PG", False, raising=True)
    # Clear the SQLite connection pool so it does not hand us connections
    # to a previous test's DB.
    try:
        while True:
            database._pool.get_nowait().close()
    except Exception:
        pass

    database.init_db()

    yield {"db_path": db_path, "module": database}

    # Cleanup: close any pooled connections
    try:
        while True:
            database._pool.get_nowait().close()
    except Exception:
        pass


def _make_user(conn, *, username: str, role: str = "Operator",
               change_groups: list[str] | None = None) -> dict:
    user_id = str(uuid.uuid4())
    now = _utc_now_iso()
    conn.execute(
        """
        INSERT INTO users (id, username, password, role, status, created_at,
                           group_name, change_groups_json, notification_channels,
                           preferred_language, fixed_pin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            username,
            "x",  # placeholder password hash, never validated in these tests
            role,
            "active",
            now,
            "",
            json.dumps(change_groups if change_groups is not None else []),
            "{}",
            "zh",
            "",
        ),
    )
    conn.commit()
    return {"user_id": user_id, "username": username, "role": role}


@pytest.fixture()
def make_user(isolated_db):
    """Factory to insert users into the isolated DB."""
    from database import get_db_connection

    created: list[dict] = []

    def _factory(username: str, *, role: str = "Operator",
                 change_groups: list[str] | None = None) -> dict:
        conn = get_db_connection()
        try:
            user = _make_user(
                conn,
                username=username,
                role=role,
                change_groups=change_groups,
            )
            created.append(user)
            return user
        finally:
            conn.close()

    return _factory


@pytest.fixture()
def requester(make_user):
    return make_user("alice_requester", role="Operator",
                     change_groups=["initial_reviewer"])


@pytest.fixture()
def initial_reviewer(make_user):
    return make_user("bob_initial", role="Operator",
                     change_groups=["initial_reviewer"])


@pytest.fixture()
def final_approver(make_user):
    return make_user("carol_final", role="Administrator",
                     change_groups=["final_approver"])
