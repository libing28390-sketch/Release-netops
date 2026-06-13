"""
Lightweight versioned schema-migration framework.

Why this exists
---------------
Historically all schema changes lived inside the ~3900-line monolithic
``schema._init_db_logic`` function. That bootstrap remains the *baseline*: it
creates every table idempotently (``CREATE TABLE IF NOT EXISTS`` + ``ensure_column``)
and seeds default data. It is intentionally left untouched.

From now on, **incremental schema changes go into ordered, tracked migration
modules** in this package instead of being appended to the monolith. Each
applied migration is recorded in the ``schema_migrations`` table so it runs
exactly once per database, on both SQLite and PostgreSQL.

Authoring a migration
---------------------
Create ``mNNNN_short_description.py`` in this directory exposing:

    VERSION = 3                      # unique, monotonically increasing int
    NAME = "short_description"       # human label stored in schema_migrations
    def upgrade(cursor, use_pg: bool) -> None:
        # Use '?' placeholders (auto-adapted to %s on PostgreSQL) and prefer
        # idempotent DDL (CREATE TABLE/INDEX IF NOT EXISTS) so re-runs are safe.
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_foo ON foo(bar)")

Migrations run inside ``init_db`` right after the baseline bootstrap. A failure
in one migration is logged and stops the remaining (higher-version) migrations
for that boot, without aborting an otherwise-successful initialization; because
migrations are idempotent, a corrected migration is retried on the next start.
"""

from __future__ import annotations

import importlib
import pkgutil
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TRACKING_TABLE = "schema_migrations"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_tracking_table(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def discover_migrations() -> list:
    """Import every ``mNNNN_*`` module in this package, sorted by VERSION."""
    found = []
    seen_versions: dict[int, str] = {}
    for mod_info in pkgutil.iter_modules(__path__):
        name = mod_info.name
        if not name.startswith("m") or "_" not in name:
            continue
        version_part = name[1:].split("_", 1)[0]
        if not version_part.isdigit():
            continue
        module = importlib.import_module(f"{__name__}.{name}")
        if not hasattr(module, "VERSION") or not hasattr(module, "upgrade"):
            logger.warning("Skipping malformed migration module: %s", name)
            continue
        version = int(module.VERSION)
        if version in seen_versions:
            raise RuntimeError(
                f"Duplicate migration VERSION {version} in '{name}' and "
                f"'{seen_versions[version]}'"
            )
        seen_versions[version] = name
        found.append(module)
    found.sort(key=lambda m: int(m.VERSION))
    return found


def get_applied_versions(conn) -> set[int]:
    cursor = conn.cursor()
    _ensure_tracking_table(cursor)
    conn.commit()
    rows = cursor.execute(f"SELECT version FROM {_TRACKING_TABLE}").fetchall()
    return {int(r[0]) for r in rows}


def run_migrations(conn, use_pg: bool | None = None) -> int:
    """
    Apply all pending migrations in version order.

    Returns the number of migrations applied. Never raises: a failing migration
    is logged and halts the remaining migrations for this run.
    """
    if use_pg is None:
        from ..core import _USE_PG as use_pg  # type: ignore

    cursor = conn.cursor()
    _ensure_tracking_table(cursor)
    conn.commit()

    try:
        applied = get_applied_versions(conn)
    except Exception as exc:
        logger.error("[migrations] Could not read %s: %s", _TRACKING_TABLE, exc)
        return 0

    try:
        migrations = discover_migrations()
    except Exception as exc:
        logger.error("[migrations] Discovery failed: %s", exc, exc_info=True)
        return 0

    count = 0
    for module in migrations:
        version = int(module.VERSION)
        name = getattr(module, "NAME", module.__name__)
        if version in applied:
            continue
        try:
            module.upgrade(cursor, use_pg)
            cursor.execute(
                f"INSERT INTO {_TRACKING_TABLE} (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, _utc_now_iso()),
            )
            conn.commit()
            count += 1
            logger.info("[migrations] Applied %04d_%s", version, name)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(
                "[migrations] FAILED %04d_%s: %s — halting further migrations.",
                version, name, exc, exc_info=True,
            )
            break

    return count
