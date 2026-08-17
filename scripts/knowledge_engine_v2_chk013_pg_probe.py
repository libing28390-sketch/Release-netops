"""PostgreSQL-only CHK-013 precision rebuild probe.

The probe exercises the real V1-compatible ``ai_document`` and
``ai_document_chunk`` tables through ``KnowledgeReindexService``.  It proves
that a changed normalized body creates a new deterministic chunk/embedding
projection, that ``original_content`` remains untouched, that dry-run and
provider failure leave the prior projection intact, and that a compare-and-set
update refuses to overwrite a concurrent document edit.  Every write is
rolled back before exit; SQLite is rejected.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid

import database
import database.core as database_core
import ai.services.knowledge_reindex_service as reindex_module
from ai.services.knowledge_reindex_service import KnowledgeReindexService, ReindexDocumentChanged


class _SameConnection:
    """Keep service ``with get_db_connection()`` blocks in one rollback scope."""

    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def _row_dict(connection, document_id: str) -> dict[str, object]:
    cursor = connection.execute("SELECT * FROM ai_document WHERE id = ?", (document_id,))
    row = cursor.fetchone()
    if not row:
        raise AssertionError("probe document was not inserted")
    names = [str(item[0]) for item in (cursor.description or [])]
    return dict(zip(names, row))


def _chunk_snapshot(connection, document_id: str) -> list[tuple[object, ...]]:
    rows = connection.execute(
        "SELECT id, content_hash, embedding_content, document_version, embedding_dimensions "
        "FROM ai_document_chunk WHERE document_id = ? ORDER BY ordinal, id",
        (document_id,),
    ).fetchall()
    return [tuple(row) for row in rows]


def _insert_probe_document(connection, *, document_id: str, knowledge_base_id: str, tenant_id: str, original: str, normalized: str, updated_at: str) -> None:
    connection.execute(
        """
        INSERT INTO ai_document (
            id, knowledge_base_id, name, status, tenant_id, created_at,
            updated_at, original_content, normalized_content, content_hash,
            metadata_json, ingestion_status, exclude_from_rag
        ) VALUES (?, ?, 'CHK-013 probe', 'active', ?, ?, ?, ?, ?, ?, '{}'::jsonb, 'ready', 0)
        """,
        (
            document_id,
            knowledge_base_id,
            tenant_id,
            updated_at,
            updated_at,
            original,
            normalized,
            hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        ),
    )


def main() -> int:
    if not database_core._USE_PG:
        print(json.dumps({"status": "BLOCKED", "reason": "DATABASE_URL is not PostgreSQL"}))
        return 2

    connection = database.get_db_connection()
    proxy = _SameConnection(connection)
    original_get_connection = reindex_module.get_db_connection
    original_embed = reindex_module.embed_documents_batch
    original_invalidate = reindex_module.retrieval_cache.invalidate_documents
    suffix = uuid.uuid4().hex[:12]
    tenant_id = f"chk013-pg-{suffix}"
    document_id = f"chk013-document-{suffix}"
    original_content = "Immutable source body; the normalized projection is rebuilt from edits.\n"
    first_body = "# Version one\n\nThe first body contains the original operational procedure."
    second_body = "# Version two\n\nThe edited body contains the updated operational procedure and validation."
    third_body = "# Version three\n\nA dry-run body must never replace the committed projection."
    old_chunk_rows: list[tuple[object, ...]] = []
    try:
        reindex_module.get_db_connection = lambda: proxy
        dimensions = int(getattr(reindex_module.embedding_provider, "dimensions", 1536) or 1536)
        reindex_module.embed_documents_batch = lambda texts, **_kwargs: [[0.001] * dimensions for _ in texts]
        reindex_module.retrieval_cache.invalidate_documents = lambda _ids: None
        timestamp = "2026-08-17T19:20:00+00:00"
        knowledge_base_id = f"chk013-pg-kb-{suffix}"
        connection.execute(
            "INSERT INTO ai_knowledge_base (id, name, description, enabled, created_by, created_at, tenant_id, acl_json) "
            "VALUES (?, 'CHK-013 PostgreSQL probe', 'transactional probe', 1, 'chk013-pg-probe', ?, ?, '{}')",
            (knowledge_base_id, timestamp, tenant_id),
        )
        _insert_probe_document(
            connection,
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            tenant_id=tenant_id,
            original=original_content,
            normalized=first_body,
            updated_at=timestamp,
        )
        service = KnowledgeReindexService()
        first = _row_dict(connection, document_id)
        first["_reindex_expected_updated_at"] = first["updated_at"]
        first_result = service._process_document(first, dry_run=False, operation="reindex")
        old_chunk_rows = _chunk_snapshot(connection, document_id)
        if first_result["rechunked"] != len(old_chunk_rows) or not old_chunk_rows:
            raise AssertionError(f"initial rebuild did not persist a complete projection: {first_result!r}")

        second_timestamp = "2026-08-17T19:20:01+00:00"
        connection.execute(
            "UPDATE ai_document SET normalized_content = ?, content_hash = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
            (second_body, hashlib.sha256(second_body.encode("utf-8")).hexdigest(), second_timestamp, document_id, tenant_id),
        )
        second = _row_dict(connection, document_id)
        second["_reindex_expected_updated_at"] = second["updated_at"]
        second_result = service._process_document(second, dry_run=False, operation="reindex")
        new_chunk_rows = _chunk_snapshot(connection, document_id)
        if second_result["rechunked"] != len(new_chunk_rows) or new_chunk_rows == old_chunk_rows:
            raise AssertionError("edited body did not produce a new exact chunk/embedding projection")
        if any(original_content in str(row[2]) for row in new_chunk_rows):
            raise AssertionError(f"chunk projection unexpectedly included immutable source body: {new_chunk_rows!r}")
        committed = _row_dict(connection, document_id)
        if committed.get("original_content") != original_content or committed.get("normalized_content") != second_body:
            raise AssertionError("document source/normalized preservation invariant failed")

        before_dry_run = _chunk_snapshot(connection, document_id)
        connection.execute(
            "UPDATE ai_document SET normalized_content = ?, content_hash = ?, updated_at = ? WHERE id = ? AND tenant_id = ?",
            (third_body, hashlib.sha256(third_body.encode("utf-8")).hexdigest(), "2026-08-17T19:20:02+00:00", document_id, tenant_id),
        )
        dry = _row_dict(connection, document_id)
        dry["_reindex_expected_updated_at"] = dry["updated_at"]
        service._process_document(dry, dry_run=True, operation="reindex")
        if _chunk_snapshot(connection, document_id) != before_dry_run:
            raise AssertionError("dry-run changed persisted chunks")

        failing = _row_dict(connection, document_id)
        failing["_reindex_expected_updated_at"] = failing["updated_at"]
        reindex_module.embed_documents_batch = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("provider failure"))
        try:
            service._process_document(failing, dry_run=False, operation="reindex")
        except RuntimeError as exc:
            if str(exc) != "provider failure":
                raise
        else:
            raise AssertionError("provider failure was silently accepted")
        if _chunk_snapshot(connection, document_id) != before_dry_run:
            raise AssertionError("provider failure partially replaced chunks")

        # Force an edit between embedding and the compare-and-set update.
        reindex_module.embed_documents_batch = lambda texts, **_kwargs: (
            connection.execute(
                "UPDATE ai_document SET updated_at = ? WHERE id = ? AND tenant_id = ?",
                ("2026-08-17T19:20:03+00:00", document_id, tenant_id),
            ),
            [[0.001] * dimensions for _ in texts],
        )[1]
        raced = _row_dict(connection, document_id)
        raced["_reindex_expected_updated_at"] = raced["updated_at"]
        try:
            service._process_document(raced, dry_run=False, operation="reindex")
        except ReindexDocumentChanged:
            pass
        else:
            raise AssertionError("concurrent edit was not rejected by compare-and-set")
        if _chunk_snapshot(connection, document_id) != before_dry_run:
            raise AssertionError("concurrent edit partially replaced chunks")

        connection.rollback()
        print(json.dumps({
            "status": "PASS",
            "database": "PostgreSQL",
            "initial_chunks": len(old_chunk_rows),
            "changed_projection": True,
            "original_content_preserved": True,
            "dry_run_unchanged": True,
            "provider_failure_atomic": True,
            "concurrent_edit_rejected": True,
            "rollback": True,
        }))
        return 0
    finally:
        reindex_module.get_db_connection = original_get_connection
        reindex_module.embed_documents_batch = original_embed
        reindex_module.retrieval_cache.invalidate_documents = original_invalidate
        connection.rollback()
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
