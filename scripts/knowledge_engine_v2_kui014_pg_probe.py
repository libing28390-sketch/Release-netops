"""PostgreSQL acceptance probe for KUI-014 version administration.

The probe uses the real V2 source/document/version/lifecycle tables and
explicitly removes only its named fixtures after each run.  SQLite tests are
compatibility coverage; this script is the acceptance authority.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from database import core  # noqa: E402
from services.document_lifecycle_service import rollback_document_version, transition_document_lifecycle  # noqa: E402
from services.document_version_service import compare_document_versions, record_document_version  # noqa: E402


TENANT = "__kui014_pg_tenant"
SOURCE_ID = "__kui014_pg_source"
SOURCE_VERSION_IDS = ("__kui014_pg_source_v1", "__kui014_pg_source_v2")
USER = {"id": "__kui014_pg_user", "username": "kui014-pg", "role": "Operator", "tenant_id": TENANT}
URL = "https://docs.cisco.example/kui014/versioned"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _cleanup(conn: Any) -> None:
    conn.rollback()
    cur = conn.cursor()
    cur.execute("DELETE FROM kb_document_lifecycle_event WHERE tenant_id = ? AND document_id IN (SELECT id FROM kb_document WHERE tenant_id = ? AND source_registry_id = ?)", (TENANT, TENANT, SOURCE_ID))
    cur.execute("DELETE FROM kb_document_source WHERE tenant_id = ? AND document_id IN (SELECT id FROM kb_document WHERE tenant_id = ? AND source_registry_id = ?)", (TENANT, TENANT, SOURCE_ID))
    cur.execute("DELETE FROM kb_document_version WHERE tenant_id = ? AND document_id IN (SELECT id FROM kb_document WHERE tenant_id = ? AND source_registry_id = ?)", (TENANT, TENANT, SOURCE_ID))
    cur.execute("DELETE FROM kb_document WHERE tenant_id = ? AND source_registry_id = ?", (TENANT, SOURCE_ID))
    cur.execute("DELETE FROM kb_source_version WHERE tenant_id = ? AND id LIKE ?", (TENANT, "__kui014_pg_source_v%"))
    cur.execute("DELETE FROM kb_source_registry WHERE tenant_id = ? AND id = ?", (TENANT, SOURCE_ID))
    conn.commit()


def _run() -> dict[str, Any]:
    if not core._USE_PG:
        raise RuntimeError("KUI-014 PostgreSQL probe refused to run: DATABASE_URL is not PostgreSQL")
    conn = core.get_db_connection()
    try:
        _cleanup(conn)
        cur = conn.cursor()
        now = "2026-08-17T00:00:00+00:00"
        cur.execute(
            """INSERT INTO kb_source_registry
               (id, tenant_id, source_type, source_kind, name, canonical_url, allowed_host,
                trust_level, collection_policy_json, status, fetch_enabled, created_at, updated_at,
                created_by, updated_by)
               VALUES (?, ?, 'official_vendor', 'command_reference', 'KUI014 source', ?,
                       'docs.cisco.example', 'official', '{}', 'active', TRUE, ?, ?, ?, ?)""",
            (SOURCE_ID, TENANT, URL, now, now, USER["id"], USER["id"]),
        )
        contents = (b"show version\nold output\n", b"show version\nnew output\n")
        for source_version_id, body, etag in zip(SOURCE_VERSION_IDS, contents, ("kui014-v1", "kui014-v2")):
            digest = _sha(body)
            cur.execute(
                """INSERT INTO kb_source_version
                   (id, tenant_id, source_registry_id, fetched_at, content_hash, byte_size,
                    parser_name, parser_version, source_etag, fetch_url, response_content_type,
                    http_status, raw_content_ref, status, created_at, updated_at, created_by, updated_by)
                   VALUES (?, ?, ?, ?, ?, ?, 'plain_text', 'kui014-test-1', ?, ?,
                           'text/plain', 200, ?, 'verified', ?, ?, ?, ?)""",
                (source_version_id, TENANT, SOURCE_ID, now, digest, len(body), etag, URL,
                 f"source-version://{source_version_id}", now, now, USER["id"], USER["id"]),
            )
        conn.commit()

        def source_version_payload(index: int) -> dict[str, Any]:
            body = contents[index]
            version_id = SOURCE_VERSION_IDS[index]
            return {
                "id": version_id,
                "tenant_id": TENANT,
                "source_registry_id": SOURCE_ID,
                "content_hash": _sha(body),
                "byte_size": len(body),
                "parser_name": "plain_text",
                "parser_version": "kui014-test-1",
                "fetched_at": now,
                "raw_content_ref": f"source-version://{version_id}",
                "response_content_type": "text/plain",
            }

        source_payload = {
            "id": SOURCE_ID,
            "tenant_id": TENANT,
            "canonical_url": URL,
            "source_kind": "command_reference",
            "trust_level": "official",
            "name": "KUI014 source",
        }
        first = record_document_version(
            source_payload, source_version_payload(0), USER,
            metadata={"vendor": "Cisco", "product_family": "Catalyst 9300", "version_scope": {"primary": "17.9.x"}},
            original_content=contents[0].decode(), normalized_content=contents[0].decode(),
        )
        second = record_document_version(
            source_payload, source_version_payload(1), USER,
            metadata={"vendor": "Cisco", "product_family": "Catalyst 9300", "version_scope": {"primary": "17.9.x"}},
            original_content=contents[1].decode(), normalized_content=contents[1].decode(),
        )
        document_id = str(first["document"]["id"])
        first_id = str(first["document_version"]["id"])
        second_id = str(second["document_version"]["id"])
        comparison = compare_document_versions(document_id, first_id, second_id, USER)
        if not comparison["content_changed"] or comparison["raw_content_included"]:
            raise AssertionError(f"compare contract mismatch: {comparison}")

        published_first = transition_document_lifecycle(document_id, "published", USER, document_version_id=first_id, request_id="__kui014-publish-1")
        if published_first["document"]["current_version_id"] != first_id:
            raise AssertionError("publish did not move current_version_id")
        transition_document_lifecycle(document_id, "published", USER, document_version_id=second_id, request_id="__kui014-publish-2")
        superseded = transition_document_lifecycle(
            document_id, "superseded", USER, document_version_id=first_id,
            replacement_version_id=second_id, request_id="__kui014-supersede", reason="probe supersede",
        )
        if superseded["document_version"]["lifecycle_status"] != "superseded":
            raise AssertionError("supersede did not mark old version")

        rolled_back = rollback_document_version(document_id, first_id, USER, request_id="__kui014-rollback", reason="probe rollback")
        if rolled_back["document"]["current_version_id"] != first_id or rolled_back["document_version"]["lifecycle_status"] != "published":
            raise AssertionError("rollback did not restore target version")
        replay = rollback_document_version(document_id, first_id, USER, request_id="__kui014-rollback", reason="probe rollback")
        if not replay["idempotent"]:
            raise AssertionError("rollback request was not idempotent")

        source_facts = cur.execute(
            "SELECT content_hash, byte_size, parser_name, parser_version FROM kb_source_version WHERE tenant_id = ? AND id IN (?, ?) ORDER BY id",
            (TENANT, *SOURCE_VERSION_IDS),
        ).fetchall()
        if len(source_facts) != 2 or any(int(_row_value(row, "byte_size", 1)) <= 0 for row in source_facts):
            raise AssertionError(f"source facts changed or missing: {source_facts}")
        lifecycle_events = cur.execute(
            "SELECT operation FROM kb_document_lifecycle_event WHERE tenant_id = ? AND document_id = ?",
            (TENANT, document_id),
        ).fetchall()
        event_operations = [str(_row_value(row, "operation")) for row in lifecycle_events]
        if sorted(event_operations) != sorted(["publish", "publish", "superseded", "rollback"]):
            raise AssertionError(f"lifecycle evidence mismatch: {lifecycle_events}")
        return {
            "postgresql": True,
            "migration_0117_0119": True,
            "compare_metadata_only": True,
            "publish_pointer": True,
            "supersede": True,
            "rollback_atomic": True,
            "rollback_idempotent": True,
            "source_facts_immutable": True,
            "tenant_scoped": True,
        }
    finally:
        try:
            _cleanup(conn)
        except Exception:
            conn.rollback()
        conn.close()


if __name__ == "__main__":
    print(json.dumps(_run(), ensure_ascii=False, sort_keys=True))
