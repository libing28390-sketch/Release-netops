from __future__ import annotations

import hashlib
import json
from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0189_knowledge_v1_provenance as migration


def _create_fixture() -> postgresql_test_driver.Connection:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.executescript(
        """
        CREATE TABLE ai_knowledge_base (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
            enabled INTEGER DEFAULT 1, created_by TEXT, created_at TEXT NOT NULL,
            tenant_id TEXT DEFAULT 'tenant-default', acl_json TEXT DEFAULT '{}'
        );
        CREATE TABLE ai_document (
            id TEXT PRIMARY KEY, knowledge_base_id TEXT NOT NULL,
            name TEXT NOT NULL, source TEXT, vendor TEXT DEFAULT 'all',
            platform TEXT DEFAULT 'all', version TEXT, status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            tenant_id TEXT DEFAULT 'tenant-default', acl_json TEXT DEFAULT '{}',
            source_trust_level TEXT DEFAULT 'internal',
            knowledge_source_type TEXT DEFAULT 'user_document',
            metadata_json TEXT DEFAULT '{}', normalized_content TEXT,
            content_hash TEXT, document_id TEXT, original_content TEXT
        );
        CREATE TABLE kb_source_registry (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_kind TEXT,
            canonical_url TEXT, trust_level TEXT, validation_status TEXT,
            metadata_json TEXT, created_at TEXT, created_by TEXT
        );
        CREATE TABLE kb_source_version (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_registry_id TEXT,
            fetched_at TEXT, content_hash TEXT, byte_size INTEGER,
            parser_name TEXT, parser_version TEXT, source_etag TEXT,
            source_last_modified TEXT, http_status INTEGER, raw_content_ref TEXT,
            response_content_type TEXT, error_code TEXT, error_json TEXT,
            verification_method TEXT, fetch_url TEXT, created_at TEXT, created_by TEXT
        );
        CREATE TABLE kb_document (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, collection_id TEXT,
            source_registry_id TEXT, canonical_key TEXT, title TEXT,
            description TEXT, source_uri TEXT, trust_level TEXT, acl_json TEXT,
            metadata_json TEXT, current_version_id TEXT, source_kind TEXT,
            status TEXT, lifecycle_status TEXT, lifecycle_revision INTEGER,
            lifecycle_reason TEXT, created_at TEXT, updated_at TEXT, created_by TEXT
        );
        CREATE TABLE kb_document_version (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, document_id TEXT,
            source_version_id TEXT, version_no INTEGER, original_content TEXT,
            normalized_content TEXT, content_hash TEXT, normalized_content_hash TEXT,
            metadata_json TEXT, parser_name TEXT, parser_version TEXT,
            trust_level TEXT, status TEXT, mime_type TEXT, byte_size INTEGER,
            fetched_at TEXT, lifecycle_status TEXT, lifecycle_reason TEXT,
            created_at TEXT, created_by TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO ai_knowledge_base (id, name, created_at, tenant_id) VALUES (?, ?, ?, ?)",
        ("kb-1", "Default", "2026-01-01T00:00:00+00:00", "tenant-1"),
    )
    conn.execute(
        """
        INSERT INTO ai_document
        (id, knowledge_base_id, name, source, vendor, status, created_at, updated_at,
         tenant_id, metadata_json, normalized_content, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "v1-doc-1", "kb-1", "OSPF Guide", "https://vendor.example/ospf",
            "Vendor", "active", "2026-01-01", "2026-01-01", "tenant-1",
            json.dumps({"document_category": "configuration"}),
            "interface Ethernet1\n ip ospf 1 area 0",
            hashlib.sha256(b"interface Ethernet1\n ip ospf 1 area 0").hexdigest(),
        ),
    )
    conn.execute(
        """
        INSERT INTO ai_document
        (id, knowledge_base_id, name, source, status, created_at, updated_at,
         tenant_id, metadata_json, normalized_content)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "v1-doc-2", "kb-1", "Internal Note", "",
            "active", "2026-01-02", "2026-01-02", "tenant-1", "{}", "local note",
        ),
    )
    conn.execute(
        """
        INSERT INTO kb_source_registry
        (id, tenant_id, source_kind, canonical_url, trust_level, validation_status,
         metadata_json, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "source-1", "tenant-1", "configuration_guide", "https://vendor.example/ospf",
            "official", "valid", json.dumps({"vendor": "Vendor"}), "2026-01-01", "seed",
        ),
    )
    conn.execute(
        """
        INSERT INTO kb_source_version
        (id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size,
         parser_name, parser_version, source_etag, source_last_modified,
         http_status, raw_content_ref, response_content_type, error_code,
         error_json, verification_method, fetch_url, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "source-version-1", "tenant-1", "source-1", "2026-01-03", "a" * 64,
            42, "html", "1", "etag-1", "last-modified", 200, "ref-1", "text/html",
            "", "{}", "hash", "https://vendor.example/ospf", "2026-01-03", "seed",
        ),
    )
    conn.execute(
        """
        INSERT INTO kb_document
        (id, tenant_id, collection_id, source_registry_id, canonical_key, title,
         source_uri, trust_level, acl_json, metadata_json, current_version_id,
         source_kind, status, lifecycle_status, lifecycle_revision, lifecycle_reason,
         created_at, updated_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "v2-doc-1", "tenant-1", "legacy-default", "source-1",
            "https://vendor.example/ospf", "OSPF Guide", "https://vendor.example/ospf",
            "official", "{}", json.dumps({"feature": "ospf"}), "doc-version-1",
            "configuration_guide", "draft", "draft", 0, "", "2026-01-01", "2026-01-03", "seed",
        ),
    )
    conn.execute(
        """
        INSERT INTO kb_document_version
        (id, tenant_id, document_id, source_version_id, version_no, original_content,
         normalized_content, content_hash, normalized_content_hash, metadata_json,
         parser_name, parser_version, trust_level, status, mime_type, byte_size,
         fetched_at, lifecycle_status, lifecycle_reason, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "doc-version-1", "tenant-1", "v2-doc-1", "source-version-1", 1,
            "raw ospf", "normalized ospf", "b" * 64, "c" * 64,
            json.dumps({"document_category": "configuration"}), "html", "1",
            "official", "draft", "text/html", 42, "2026-01-03", "draft", "", "2026-01-03", "seed",
        ),
    )
    conn.commit()
    return conn


def test_m0189_backfills_v1_provenance_and_is_idempotent() -> None:
    conn = _create_fixture()
    try:
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        document = conn.execute(
            "SELECT canonical_url, source_kind, source_content_hash, source_etag, "
            "source_parser_name, lifecycle_status FROM ai_document WHERE id = ?",
            ("v1-doc-1",),
        ).fetchone()
        assert tuple(document) == (
            "https://vendor.example/ospf", "configuration_guide", "a" * 64,
            "etag-1", "html", "draft",
        )

        revisions = conn.execute(
            "SELECT document_id, revision_no, canonical_url, content_hash, "
            "legacy_source_id, legacy_source_version_id, legacy_document_version_id "
            "FROM ai_document_revision ORDER BY document_id"
        ).fetchall()
        assert len(revisions) == 2
        v2_revision = next(row for row in revisions if row[0] == "v1-doc-1")
        assert tuple(v2_revision[1:]) == (
            1, "https://vendor.example/ospf", "a" * 64,
            "source-1", "source-version-1", "doc-version-1",
        )
        assert conn.execute("SELECT COUNT(*) FROM ai_document_revision").fetchone()[0] == 2
    finally:
        conn.close()
