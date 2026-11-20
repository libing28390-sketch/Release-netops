from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database import get_db_connection
from database.migrations import m0229_scheduler_lock_timestamptz as migration


def test_m0229_migrates_legacy_times_and_owner_tokens_and_is_idempotent(isolated_db):
    acquired_utc = datetime(2026, 9, 13, 6, 54, 30, tzinfo=timezone.utc)
    expires_utc = acquired_utc + timedelta(minutes=1)
    active_expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
    conn = get_db_connection()
    try:
        conn.execute("DROP TABLE scheduler_locks")
        conn.execute(
            """
            CREATE TABLE scheduler_locks (
                lock_name TEXT PRIMARY KEY,
                locked_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX idx_scheduler_locks_expires ON scheduler_locks(expires_at)"
        )
        conn.execute(
            "INSERT INTO scheduler_locks (lock_name, locked_at, expires_at) VALUES (?, ?, ?)",
            ("ip_locator_run_worker", acquired_utc.isoformat(), expires_utc.isoformat()),
        )
        conn.execute(
            "INSERT INTO scheduler_locks (lock_name, locked_at, expires_at) VALUES (?, ?, ?)",
            ("knowledge_reindex:job-229", "reindex-worker:opaque-token", active_expiry.isoformat()),
        )
        conn.execute(
            "INSERT INTO scheduler_locks (lock_name, locked_at, expires_at) VALUES (?, ?, ?)",
            ("knowledge_import:tenant:job-229", "opaque-import-token", active_expiry.isoformat()),
        )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        columns = {
            row[0]: row[1]
            for row in conn.execute(
                """
                SELECT column_name, data_type
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'scheduler_locks'
                """
            ).fetchall()
        }
        assert columns["owner_token"] == "text"
        assert columns["locked_at"] == "timestamp with time zone"
        assert columns["expires_at"] == "timestamp with time zone"

        conn.execute("SET TIME ZONE 'Asia/Shanghai'")
        rows = {
            row["lock_name"]: row
            for row in conn.execute(
                "SELECT lock_name, owner_token, locked_at, expires_at FROM scheduler_locks"
            ).fetchall()
        }
        core_lock = rows["ip_locator_run_worker"]
        assert core_lock["owner_token"]
        assert core_lock["locked_at"].utcoffset() == timedelta(hours=8)
        assert core_lock["locked_at"].astimezone(timezone.utc) == acquired_utc
        assert core_lock["expires_at"].astimezone(timezone.utc) == expires_utc
        assert rows["knowledge_reindex:job-229"]["owner_token"] == "reindex-worker:opaque-token"
        assert rows["knowledge_import:tenant:job-229"]["owner_token"] == "opaque-import-token"
    finally:
        try:
            conn.execute("RESET TIME ZONE")
            conn.commit()
        finally:
            conn.close()


def test_m0229_downgrade_restores_legacy_owner_values(isolated_db):
    token = "reindex-worker:rollback-token"
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO scheduler_locks (lock_name, owner_token, locked_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (
                "knowledge_reindex:rollback",
                token,
                datetime.now(timezone.utc),
                datetime.now(timezone.utc) + timedelta(minutes=5),
            ),
        )
        conn.commit()

        migration.downgrade(conn.cursor(), use_pg=True)
        conn.commit()

        columns = {
            row[0]: row[1]
            for row in conn.execute(
                """
                SELECT column_name, data_type
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'scheduler_locks'
                """
            ).fetchall()
        }
        assert "owner_token" not in columns
        assert columns["locked_at"] == "text"
        assert columns["expires_at"] == "text"
        row = conn.execute(
            "SELECT locked_at FROM scheduler_locks WHERE lock_name = ?",
            ("knowledge_reindex:rollback",),
        ).fetchone()
        assert row["locked_at"] == token
    finally:
        conn.close()
