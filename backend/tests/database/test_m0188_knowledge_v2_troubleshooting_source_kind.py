from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0116_knowledge_v2_source_registry as m0116
from database.migrations import m0188_knowledge_v2_troubleshooting_source_kind as m0188


def _create_legacy_registry(conn: postgresql_test_driver.Connection) -> None:
    old_kinds = m0116._SOURCE_KINDS
    m0116._SOURCE_KINDS = (
        "'official_url','product_page','configuration_guide','command_reference',"
        "'release_note','product_support','enterprise','internal','user_upload','api'"
    )
    try:
        m0116._create_registry_table(conn.cursor(), True)
    finally:
        m0116._SOURCE_KINDS = old_kinds


def test_m0188_updates_legacy_postgresql_registry_and_preserves_children() -> None:
    conn = postgresql_test_driver.connect()
    try:
        _create_legacy_registry(conn)
        conn.execute(
            "CREATE TABLE kb_source_version_child "
            "(source_registry_id TEXT REFERENCES kb_source_registry(id))"
        )
        conn.execute(
            "INSERT INTO kb_source_registry "
            "(id, tenant_id, source_type, source_kind, canonical_url, allowed_host, "
            "trust_level, collection_policy_json, created_at, updated_at, created_by, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "source-1", "tenant-1", "internal", "internal",
                "https://internal.example/", "internal.example", "internal", "{}",
                "2026-01-01", "2026-01-01", "actor", "actor",
            ),
        )
        conn.execute(
            "INSERT INTO kb_source_version_child VALUES (?)",
            ("source-1",),
        )
        conn.commit()

        m0188.upgrade(conn.cursor(), True)
        conn.commit()
        m0188.upgrade(conn.cursor(), True)
        conn.commit()

        conn.execute(
            "INSERT INTO kb_source_registry "
            "(id, tenant_id, source_type, source_kind, canonical_url, allowed_host, "
            "trust_level, collection_policy_json, created_at, updated_at, created_by, updated_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "source-2", "tenant-1", "official_product", "troubleshooting_guide",
                "https://www.h3c.com/cn/d_202603/2776299_30005_0.htm", "www.h3c.com", "official", "{}",
                "2026-01-01", "2026-01-01", "actor", "actor",
            ),
        )
        assert conn.execute("SELECT source_kind FROM kb_source_registry WHERE id = ?", ("source-1",)).fetchone()[0] == "internal"
        assert conn.execute("SELECT source_registry_id FROM kb_source_version_child").fetchone()[0] == "source-1"
        assert "kb_source_registry" in pg_catalog.foreign_key_targets(
            conn, "kb_source_version_child"
        )
    finally:
        conn.close()


def test_m0188_postgres_sql_contains_named_constraint_replacement() -> None:
    assert any(
        "DROP CONSTRAINT IF EXISTS kb_source_registry_source_kind_check" in str(item)
        for item in m0188._upgrade_postgres.__code__.co_consts
    )
    assert "troubleshooting_guide" in m0188._SOURCE_KINDS
