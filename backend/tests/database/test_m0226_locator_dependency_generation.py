from __future__ import annotations

import uuid

from database import get_db_connection
from database.migrations import m0226_locator_dependency_generation as migration


def _generation(conn) -> int:
    row = conn.execute(
        "SELECT generation FROM locator_dependency_generations "
        "WHERE dependency_key = ?",
        ("topology:global",),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_m0226_upgrade_and_repeat_are_idempotent_on_postgresql(isolated_db) -> None:
    conn = get_db_connection()
    try:
        # Reconstruct the immediately preceding schema shape in this disposable
        # PostgreSQL database, then exercise the actual upgrade path twice.
        conn.execute("DROP TRIGGER IF EXISTS trg_locator_topology_generation ON topology_links")
        conn.execute("DROP FUNCTION IF EXISTS bump_locator_topology_generation()")
        conn.execute("DROP TABLE IF EXISTS locator_dependency_generations")
        conn.execute("ALTER TABLE locator_runs DROP COLUMN IF EXISTS dependency_manifest_json")
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        column = conn.execute(
            """SELECT data_type, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'locator_runs'
                  AND column_name = 'dependency_manifest_json'"""
        ).fetchone()
        assert column is not None
        assert column[0] == "jsonb"
        assert column[1] == "NO"
        assert "{}" in str(column[2])
        assert conn.execute(
            """SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_locator_topology_generation'
                  AND NOT tgisinternal"""
        ).fetchone() is not None
        row = conn.execute(
            "SELECT scope, generation FROM locator_dependency_generations "
            "WHERE dependency_key = ?",
            ("topology:global",),
        ).fetchone()
        assert tuple(row) == ("global", 1)
    finally:
        conn.close()


def test_topology_row_trigger_advances_generation_transactionally(isolated_db) -> None:
    conn = get_db_connection()
    link_id = f"locator-generation-test:{uuid.uuid4().hex}"
    try:
        before = _generation(conn)

        conn.execute("INSERT INTO topology_links (id) VALUES (?)", (link_id,))
        assert _generation(conn) == before + 1
        conn.rollback()
        assert _generation(conn) == before

        conn.execute("INSERT INTO topology_links (id) VALUES (?)", (link_id,))
        conn.commit()
        after_insert = _generation(conn)
        assert after_insert == before + 1

        conn.execute(
            "UPDATE topology_links SET status = ? WHERE id = ?",
            ("stale", link_id),
        )
        assert _generation(conn) == after_insert + 1
        conn.commit()
        after_update = _generation(conn)

        conn.execute("DELETE FROM topology_links WHERE id = ?", (link_id,))
        assert _generation(conn) == after_update + 1
        conn.commit()
    finally:
        conn.close()
