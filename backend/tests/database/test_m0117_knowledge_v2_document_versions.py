from __future__ import annotations

import hashlib

import pytest


def test_m0117_creates_idempotent_document_version_shadow_tables(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name IN (?, ?) ",
                ("kb_document", "kb_document_version"),
            ).fetchall()
        }
        assert tables == {"kb_document", "kb_document_version"}
        applied = conn.execute("SELECT name FROM schema_migrations WHERE version = 117").fetchone()
        assert applied[0] == "knowledge_v2_document_versions"
    finally:
        conn.close()


def test_m0117_document_version_fact_guard_blocks_original_hash_mutation(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    digest = hashlib.sha256(b"immutable").hexdigest()
    try:
        conn.execute(
            """
            INSERT INTO kb_source_registry (
                id, tenant_id, source_type, source_kind, canonical_url, allowed_host,
                trust_level, collection_policy_json, created_at, updated_at, created_by, updated_by
            ) VALUES (?, ?, 'official_vendor', 'official_url', ?, ?, 'official', '{}', '2026-08-09T00:00:00+00:00', '2026-08-09T00:00:00+00:00', 'test', 'test')
            """,
            ("source-117", "tenant-117", "https://example.com/manual", "example.com"),
        )
        conn.execute(
            """
            INSERT INTO kb_source_version (
                id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size,
                parser_name, parser_version, status, created_at, updated_at, created_by, updated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'fetched', ?, ?, ?, ?)
            """,
            (
                "source-version-117", "tenant-117", "source-117", "2026-08-09T00:00:00+00:00",
                digest, 9, "html", "1.0.0", "2026-08-09T00:00:00+00:00",
                "2026-08-09T00:00:00+00:00", "test", "test",
            ),
        )
        conn.execute(
            """
            INSERT INTO kb_document (
                id, tenant_id, collection_id, source_registry_id, canonical_key,
                created_at, updated_at, created_by, updated_by
            ) VALUES ('document-117', 'tenant-117', 'legacy-default', 'source-117', ?, ?, ?, 'test', 'test')
            """,
            ("https://example.com/manual", "2026-08-09T00:00:00+00:00", "2026-08-09T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO kb_document_version (
                id, tenant_id, document_id, source_version_id, version_no,
                content_hash, parser_name, parser_version, fetched_at,
                created_at, updated_at, created_by, updated_by
            ) VALUES ('document-version-117', 'tenant-117', 'document-117', 'source-version-117', 1, ?, 'html', '1.0.0', ?, ?, ?, 'test', 'test')
            """,
            (digest, "2026-08-09T00:00:00+00:00", "2026-08-09T00:00:00+00:00", "2026-08-09T00:00:00+00:00"),
        )
        conn.commit()
        with pytest.raises(Exception, match="kb_document_version_fact_immutable"):
            conn.execute(
                "UPDATE kb_document_version SET content_hash = ? WHERE id = ?",
                (hashlib.sha256(b"changed").hexdigest(), "document-version-117"),
            )
        conn.rollback()
        assert conn.execute("SELECT content_hash FROM kb_document_version WHERE id = 'document-version-117'").fetchone()[0] == digest
    finally:
        conn.close()

