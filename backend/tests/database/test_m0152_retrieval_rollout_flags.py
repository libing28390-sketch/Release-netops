import sqlite3

from database.migrations import build_migration_plan, discover_migrations, run_migrations
from database.migrations.m0156_retrieval_rollout_flags import upgrade


def test_migration_versions_keep_both_published_histories() -> None:
    discovered = {module.VERSION: module.NAME for module in discover_migrations()}

    assert discovered[152] == "config_backup_tftp_and_startup"
    assert discovered[153] == "config_backup_tftp_and_startup"
    assert discovered[156] == "retrieval_rollout_flags"


def _history_connection(*rows: tuple[int, str]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE schema_migrations "
        "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO schema_migrations VALUES (?, ?, 'now')",
        rows,
    )
    conn.commit()
    return conn


def test_pre_collision_history_is_safe_and_retrieval_is_pending() -> None:
    conn = _history_connection((1, "baseline"), (152, "config_backup_tftp_and_startup"))
    try:
        plan = build_migration_plan(conn, use_pg=False)
    finally:
        conn.close()

    assert plan.unknown_applied_versions == ()
    assert plan.name_drift == ()
    assert 153 in plan.pending_versions
    assert 156 in plan.pending_versions


def test_short_lived_collision_history_is_accepted_and_retrieval_is_replayed() -> None:
    conn = _history_connection(
        (1, "baseline"),
        (152, "retrieval_rollout_flags"),
        (153, "config_backup_tftp_and_startup"),
    )
    try:
        plan = build_migration_plan(conn, use_pg=False)
    finally:
        conn.close()

    assert plan.unknown_applied_versions == ()
    assert plan.name_drift == ()
    assert 156 in plan.pending_versions


def test_short_lived_collision_history_runs_the_repair_migration(monkeypatch) -> None:
    conn = _history_connection(
        (1, "baseline"),
        (152, "retrieval_rollout_flags"),
        (153, "config_backup_tftp_and_startup"),
    )
    import database.migrations as migrations

    discovered = [
        module
        for module in discover_migrations()
        if module.VERSION in {1, 152, 153, 156}
    ]
    monkeypatch.setattr(migrations, "discover_migrations", lambda: discovered)
    try:
        assert run_migrations(conn, use_pg=False, strict_history=True) == 1
        assert conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 156"
        ).fetchone() == ("retrieval_rollout_flags",)
    finally:
        conn.close()


def test_m0156_is_a_sqlite_compatibility_noop() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, statement: str) -> None:
            self.statements.append(statement)

    cursor = Cursor()
    upgrade(cursor, use_pg=False)

    assert cursor.statements == []
