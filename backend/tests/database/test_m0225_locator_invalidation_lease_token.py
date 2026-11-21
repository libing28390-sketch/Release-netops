from __future__ import annotations

from database import get_db_connection
from database.migrations import m0225_locator_invalidation_lease_token as migration


def test_m0225_adds_fencing_token_idempotently(isolated_db) -> None:
    conn = get_db_connection()
    try:
        conn.execute("ALTER TABLE locator_invalidation_outbox DROP COLUMN lease_token")
        conn.commit()
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        column = conn.execute(
            """SELECT column_name, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'locator_invalidation_outbox'
                  AND column_name = 'lease_token'"""
        ).fetchone()
        assert column is not None
        assert column[1] == "NO"
        assert column[2] is not None
    finally:
        conn.close()
