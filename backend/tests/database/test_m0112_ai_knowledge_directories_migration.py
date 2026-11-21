from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0112_ai_knowledge_directories


def test_knowledge_directory_migration_is_idempotent_on_postgresql():
    conn = postgresql_test_driver.connect()
    conn.execute("CREATE TABLE ai_knowledge_base (id TEXT PRIMARY KEY)")

    m0112_ai_knowledge_directories.upgrade(conn.cursor(), use_pg=True)
    m0112_ai_knowledge_directories.upgrade(conn.cursor(), use_pg=True)
    conn.commit()

    directory_columns = pg_catalog.table_columns(conn, "ai_knowledge_directory")
    assert {"knowledge_base_id", "tenant_id", "parent_id", "path", "is_system"}.issubset(directory_columns)
    state_columns = pg_catalog.table_columns(conn, "ai_knowledge_directory_state")
    assert {"knowledge_base_id", "tenant_id", "defaults_seeded"}.issubset(state_columns)
    indexes = pg_catalog.index_names(conn, "ai_knowledge_directory")
    assert "ix_ai_knowledge_directory_tree" in indexes
