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
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TRACKING_TABLE = "schema_migrations"


class MigrationHistoryError(RuntimeError):
    """Raised when the recorded migration history cannot be reconciled safely."""


@dataclass(frozen=True)
class MigrationPlan:
    """Read-only plan used by fresh installs and repeatable upgrades.

    The plan deliberately contains versions/names rather than SQL.  Callers can
    inspect it before applying anything, and a history mismatch fails closed
    instead of silently skipping a removed or renamed migration.
    """

    fresh_install: bool
    discovered_versions: tuple[int, ...]
    applied_versions: tuple[int, ...]
    pending_versions: tuple[int, ...]
    unknown_applied_versions: tuple[int, ...]
    name_drift: tuple[tuple[int, str, str], ...]

    @property
    def safe(self) -> bool:
        return not self.unknown_applied_versions and not self.name_drift

    def safe_for(self, *, strict_history: bool) -> bool:
        """Return whether this plan may run under the requested history mode."""
        return not self.name_drift and (not strict_history or not self.unknown_applied_versions)


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


def get_applied_records(conn) -> dict[int, str]:
    """Return the tracked version/name map without mutating migration state."""
    cursor = conn.cursor()
    _ensure_tracking_table(cursor)
    conn.commit()
    rows = cursor.execute(f"SELECT version, name FROM {_TRACKING_TABLE}").fetchall()
    return {int(row[0]): str(row[1]) for row in rows}


def build_migration_plan(conn, use_pg: bool | None = None) -> MigrationPlan:
    """Build a deterministic fresh/upgrade plan before executing any module."""
    if use_pg is None:
        from ..core import _USE_PG as use_pg  # type: ignore

    migrations = discover_migrations()
    discovered = {int(module.VERSION): module for module in migrations}
    if len(discovered) != len(migrations):
        raise MigrationHistoryError("Duplicate migration versions discovered")

    records = get_applied_records(conn)
    unknown = tuple(sorted(set(records) - set(discovered)))
    drift_entries = []
    for version in sorted(set(records) & set(discovered)):
        module = discovered[version]
        expected_name = str(getattr(module, "NAME", ""))
        legacy_names = getattr(module, "LEGACY_NAMES", ())
        if isinstance(legacy_names, str):
            legacy_names = (legacy_names,)
        accepted_names = {expected_name, *(str(name) for name in legacy_names)}
        if records[version] not in accepted_names:
            drift_entries.append((version, records[version], expected_name))
    drift = tuple(drift_entries)
    if records and 1 not in records:
        # A non-empty history without the immutable baseline marker is not a
        # fresh install and cannot be safely auto-repaired.
        drift = drift + ((1, "<missing>", str(getattr(discovered.get(1), "NAME", "baseline"))),)
    pending = tuple(sorted(set(discovered) - set(records)))
    return MigrationPlan(
        fresh_install=not records,
        discovered_versions=tuple(sorted(discovered)),
        applied_versions=tuple(sorted(records)),
        pending_versions=pending,
        unknown_applied_versions=unknown,
        name_drift=drift,
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
    return set(get_applied_records(conn))


def run_migrations(
    conn,
    use_pg: bool | None = None,
    *,
    strict_history: bool = False,
) -> int:
    """
    Apply all pending migrations in version order.

    Returns the number of migrations applied. Never raises: a failing migration
    is logged and halts the remaining migrations for this run.
    """
    if use_pg is None:
        from ..core import _USE_PG as use_pg  # type: ignore

    try:
        plan = build_migration_plan(conn, use_pg)
    except Exception as exc:
        logger.error("[migrations] Planning failed: %s", exc, exc_info=True)
        return 0

    if not plan.safe_for(strict_history=strict_history):
        logger.error(
            "[migrations] Unsafe history (strict=%s): unknown=%s name_drift=%s; no migration applied",
            strict_history,
            plan.unknown_applied_versions,
            plan.name_drift,
        )
        return 0

    logger.info(
        "[migrations] Plan fresh=%s applied=%s pending=%s",
        plan.fresh_install,
        plan.applied_versions,
        plan.pending_versions,
    )

    migrations_by_version = {int(module.VERSION): module for module in discover_migrations()}
    cursor = conn.cursor()
    applied = set(plan.applied_versions)

    count = 0
    for version in plan.pending_versions:
        module = migrations_by_version[version]
        version = int(module.VERSION)
        name = getattr(module, "NAME", getattr(module, "__name__", "<migration>"))
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
