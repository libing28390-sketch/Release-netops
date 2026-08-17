"""PostgreSQL-only ING-024 duplicate-content and rollback probe.

The probe uses the real Knowledge V2 source registry/version tables in one
transaction.  It creates two temporary tenant-scoped source/version pairs,
verifies that the same tenant/source/content hash is rejected while the same
hash in another tenant is allowed, and rolls every write back.  It refuses
to run when the configured backend is not PostgreSQL.
"""

from __future__ import annotations

import json
import sys
import uuid

import database
import database.core as database_core


def _insert_source(connection, *, tenant_id: str, source_id: str) -> None:
    connection.execute(
        """
        INSERT INTO kb_source_registry (
            id, tenant_id, source_type, canonical_url, allowed_host,
            trust_level, collection_policy_json, created_at, updated_at,
            created_by, updated_by
        ) VALUES (?, ?, 'official_vendor', ?, 'docs.example', 'official', '{}'::jsonb,
                  CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'ing024-pg-probe', 'ing024-pg-probe')
        """,
        (source_id, tenant_id, f"https://docs.example/ing024/{tenant_id}"),
    )


def _insert_version(connection, *, tenant_id: str, source_id: str, version_id: str, content_hash: str) -> None:
    connection.execute(
        """
        INSERT INTO kb_source_version (
            id, tenant_id, source_registry_id, fetched_at, content_hash,
            byte_size, parser_name, parser_version, status, created_at,
            updated_at, created_by, updated_by
        ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, 24, 'ing024-pg-probe',
                  '1.0.0', 'fetched', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                  'ing024-pg-probe', 'ing024-pg-probe')
        """,
        (version_id, tenant_id, source_id, content_hash),
    )


def main() -> int:
    if not database_core._USE_PG:
        print(json.dumps({"status": "BLOCKED", "reason": "DATABASE_URL is not PostgreSQL"}))
        return 2

    connection = database.get_db_connection()
    suffix = uuid.uuid4().hex[:12]
    tenant_a = f"ing024-pg-a-{suffix}"
    tenant_b = f"ing024-pg-b-{suffix}"
    source_a = f"ing024-source-a-{suffix}"
    source_b = f"ing024-source-b-{suffix}"
    content_hash = "a" * 64
    duplicate_rejected = False
    cross_tenant_allowed = False
    try:
        _insert_source(connection, tenant_id=tenant_a, source_id=source_a)
        _insert_source(connection, tenant_id=tenant_b, source_id=source_b)
        _insert_version(connection, tenant_id=tenant_a, source_id=source_a, version_id=f"ing024-version-a-{suffix}", content_hash=content_hash)

        connection.execute("SAVEPOINT ing024_duplicate_content")
        try:
            _insert_version(connection, tenant_id=tenant_a, source_id=source_a, version_id=f"ing024-version-duplicate-{suffix}", content_hash=content_hash)
        except Exception as exc:  # psycopg2 unique violation; no body is logged
            if getattr(exc, "pgcode", None) != "23505":
                raise
            duplicate_rejected = True
            connection.execute("ROLLBACK TO SAVEPOINT ing024_duplicate_content")
        finally:
            connection.execute("RELEASE SAVEPOINT ing024_duplicate_content")

        _insert_version(connection, tenant_id=tenant_b, source_id=source_b, version_id=f"ing024-version-b-{suffix}", content_hash=content_hash)
        cross_tenant_allowed = True
        if not duplicate_rejected or not cross_tenant_allowed:
            raise AssertionError("PostgreSQL duplicate-content tenant invariant failed")

        connection.rollback()
        print(json.dumps({
            "status": "PASS",
            "database": "PostgreSQL",
            "duplicate_same_tenant_rejected": duplicate_rejected,
            "same_hash_other_tenant_allowed": cross_tenant_allowed,
            "rollback": True,
        }))
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
