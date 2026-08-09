import sqlite3

from database.migrations import m0112_ai_knowledge_directories


def test_knowledge_directory_migration_is_idempotent_on_sqlite():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ai_knowledge_base (id TEXT PRIMARY KEY)")

    m0112_ai_knowledge_directories.upgrade(conn.cursor(), use_pg=False)
    m0112_ai_knowledge_directories.upgrade(conn.cursor(), use_pg=False)
    conn.commit()

    directory_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_knowledge_directory)").fetchall()}
    assert {"knowledge_base_id", "tenant_id", "parent_id", "path", "is_system"}.issubset(directory_columns)
    state_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_knowledge_directory_state)").fetchall()}
    assert {"knowledge_base_id", "tenant_id", "defaults_seeded"}.issubset(state_columns)
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(ai_knowledge_directory)").fetchall()}
    assert "ix_ai_knowledge_directory_tree" in indexes
