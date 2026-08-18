import sqlite3

from database.migrations import build_migration_plan, discover_migrations
from database.migrations.m0152_retrieval_rollout_flags import upgrade


def test_m0152_keeps_the_recorded_migration_identity() -> None:
    discovered = {module.VERSION: module.NAME for module in discover_migrations()}

    assert discovered[152] == "retrieval_rollout_flags"
    assert discovered[153] == "config_backup_tftp_and_startup"


def test_m0152_accepts_existing_history_and_leaves_new_feature_pending() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO schema_migrations VALUES (1, 'baseline', 'now')")
        conn.execute(
            "INSERT INTO schema_migrations VALUES (152, 'retrieval_rollout_flags', 'now')"
        )
        conn.commit()

        plan = build_migration_plan(conn, use_pg=False)
    finally:
        conn.close()

    assert plan.unknown_applied_versions == ()
    assert plan.name_drift == ()
    assert 153 in plan.pending_versions


def test_m0152_is_a_sqlite_compatibility_noop() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement: str) -> None:
            self.statements.append(statement)

    cursor = Cursor()
    upgrade(cursor, use_pg=False)

    assert cursor.statements == []
