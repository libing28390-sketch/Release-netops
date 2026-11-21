from database import get_db_connection
from database.migrations import m0223_locator_query_task_retention as migration


def test_m0223_retention_index_is_idempotent_on_postgresql(isolated_db):
    conn = get_db_connection()
    try:
        migration.upgrade(conn.cursor(), use_pg=True)
        migration.upgrade(conn.cursor(), use_pg=True)
        row = conn.execute(
            """
            SELECT indexdef FROM pg_indexes
             WHERE schemaname = current_schema()
               AND indexname = 'ix_locator_tasks_terminal_retention'
            """
        ).fetchone()
        assert row is not None
        assert "locator_query_tasks" in row[0]
        assert "completed_at" in row[0]
    finally:
        conn.close()
