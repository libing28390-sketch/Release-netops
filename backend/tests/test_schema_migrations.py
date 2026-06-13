"""
Tests for the versioned schema-migration framework.

Validates: discovery/order, baseline tracking after init_db, idempotency
(re-running applies nothing), and that migration 0002's indexes exist.
"""

from database import get_db_connection
from database.migrations import (
    run_migrations, discover_migrations, get_applied_versions, _TRACKING_TABLE,
)


def _index_names(conn) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    return {r[0] for r in rows}


def test_discovery_is_ordered_and_unique():
    mods = discover_migrations()
    versions = [int(m.VERSION) for m in mods]
    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    # baseline + cmdb indexes are present
    assert 1 in versions
    assert 2 in versions


def test_tracking_table_populated_after_init(isolated_db):
    conn = get_db_connection()
    try:
        # init_db (run by the fixture) should have created + populated the table
        applied = get_applied_versions(conn)
        assert 1 in applied
        assert 2 in applied
    finally:
        conn.close()


def test_migration_0002_indexes_exist(isolated_db):
    conn = get_db_connection()
    try:
        idx = _index_names(conn)
        for expected in (
            "idx_sites_tenant", "idx_vrfs_tenant", "idx_vlans_tenant", "idx_devices_credential",
        ):
            assert expected in idx, f"missing index {expected}"
    finally:
        conn.close()


def test_rerun_is_idempotent(isolated_db):
    conn = get_db_connection()
    try:
        before = get_applied_versions(conn)
        applied_count = run_migrations(conn, use_pg=False)
        after = get_applied_versions(conn)
        assert applied_count == 0, "no migrations should re-apply"
        assert before == after
    finally:
        conn.close()


def test_pending_migration_applies_once(isolated_db):
    """A freshly-registered version applies exactly once, then is skipped."""
    import database.migrations as mig

    class _FakeModule:
        VERSION = 99001
        NAME = "unit_test_probe"
        applied_times = 0

        @staticmethod
        def upgrade(cursor, use_pg):
            _FakeModule.applied_times += 1
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS _mig_probe (id INTEGER PRIMARY KEY)"
            )

    original = mig.discover_migrations
    mig.discover_migrations = lambda: [_FakeModule]  # type: ignore
    try:
        conn = get_db_connection()
        try:
            assert run_migrations(conn, use_pg=False) == 1
            assert _FakeModule.applied_times == 1
            # second run: already recorded → skipped
            assert run_migrations(conn, use_pg=False) == 0
            assert _FakeModule.applied_times == 1
            # the probe table was created
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='_mig_probe'"
            ).fetchone()
            assert row is not None
            # tracking row recorded
            rec = conn.execute(
                f"SELECT name FROM {_TRACKING_TABLE} WHERE version = 99001"
            ).fetchone()
            assert rec is not None
        finally:
            conn.close()
    finally:
        mig.discover_migrations = original  # type: ignore
