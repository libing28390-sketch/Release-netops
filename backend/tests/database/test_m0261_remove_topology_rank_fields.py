from __future__ import annotations

from database import get_db_connection
from database.migrations import m0261_remove_topology_rank_fields as migration


def test_m0261_removes_legacy_rank_columns_idempotently(isolated_db):
    conn = get_db_connection()
    try:
        # Reconstruct the immediately previous schema in this disposable DB.
        conn.execute("ALTER TABLE topology_nodes ADD COLUMN IF NOT EXISTS rank DOUBLE PRECISION")
        conn.execute("ALTER TABLE topology_edges ADD COLUMN IF NOT EXISTS rank_excluded INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE topology_relations ADD COLUMN IF NOT EXISTS rank_excluded INTEGER NOT NULL DEFAULT 0")
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        columns = {
            (str(row[0]), str(row[1]))
            for row in conn.execute(
                """SELECT table_name, column_name
                     FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name IN ('topology_nodes', 'topology_edges', 'topology_relations')"""
            ).fetchall()
        }
        assert ('topology_nodes', 'rank') not in columns
        assert ('topology_edges', 'rank_excluded') not in columns
        assert ('topology_relations', 'rank_excluded') not in columns
    finally:
        conn.close()
