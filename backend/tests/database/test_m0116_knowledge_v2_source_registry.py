from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog

from backend.tests.pg_test_utils import postgresql_test_driver
import pytest

from database.migrations.m0116_knowledge_v2_source_registry import upgrade


def test_m0116_is_idempotent_and_has_composite_source_version_boundary():
    conn = postgresql_test_driver.connect()
    try:
        upgrade(conn.cursor(), True)
        conn.commit()
        upgrade(conn.cursor(), True)
        conn.commit()
        tables = pg_catalog.table_names(conn)
        assert {"kb_source_registry", "kb_source_version"}.issubset(tables)
        indexes = pg_catalog.index_names(conn, "kb_source_registry")
        assert any("canonical" in name for name in indexes)
    finally:
        conn.close()


def test_m0116_blocks_mutation_of_source_version_facts():
    conn = postgresql_test_driver.connect()
    try:
        upgrade(conn.cursor(), True)
        conn.execute(
            "INSERT INTO kb_source_registry (id, tenant_id, source_type, source_kind, canonical_url, allowed_host, trust_level, collection_policy_json, created_at, updated_at, created_by, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("source-1", "tenant-1", "internal", "internal", "https://internal.example/", "internal.example", "internal", "{}", "2026-01-01", "2026-01-01", "actor", "actor"),
        )
        conn.execute(
            "INSERT INTO kb_source_version (id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size, parser_name, parser_version, status, created_at, updated_at, created_by, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("version-1", "tenant-1", "source-1", "2026-01-01", "a" * 64, 1, "plain", "1", "fetched", "2026-01-01", "2026-01-01", "actor", "actor"),
        )
        conn.commit()
        with pytest.raises(postgresql_test_driver.DatabaseError, match="immutable"):
            conn.execute("UPDATE kb_source_version SET content_hash = ? WHERE id = ?", ("b" * 64, "version-1"))
        conn.rollback()
    finally:
        conn.close()
