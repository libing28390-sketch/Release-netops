"""Repair the V1 current-revision pointer for databases finalized before 191 was patched.

Migration 191 owns the destructive V2 cleanup and also projects the latest
document revision into ``ai_document.current_version_id``.  A database that
recorded 191 before that projection was added needs this small additive repair;
it is safe to replay and does not recreate any retired V2 object.
"""

from __future__ import annotations

from . import m0189_knowledge_v1_provenance as _provenance


VERSION = 192
NAME = "knowledge_v1_current_version_projection"


def upgrade(cursor, use_pg: bool) -> None:
    if not _provenance._table_exists(cursor, "ai_document", use_pg):
        raise RuntimeError("knowledge_v1_current_version_projection requires ai_document")
    if not _provenance._table_exists(cursor, "ai_document_revision", use_pg):
        raise RuntimeError("knowledge_v1_current_version_projection requires ai_document_revision")

    columns = _provenance._columns(cursor, "ai_document", use_pg)
    if "current_version_id" not in columns:
        cursor.execute("ALTER TABLE ai_document ADD COLUMN current_version_id TEXT")

    cursor.execute(
        "UPDATE ai_document SET current_version_id = ("
        "SELECT r.id FROM ai_document_revision r "
        "WHERE r.tenant_id = ai_document.tenant_id AND r.document_id = ai_document.id "
        "AND r.record_type = 'document_revision' "
        "ORDER BY r.revision_no DESC, r.created_at DESC, r.id DESC LIMIT 1) "
        "WHERE EXISTS (SELECT 1 FROM ai_document_revision r2 "
        "WHERE r2.tenant_id = ai_document.tenant_id AND r2.document_id = ai_document.id "
        "AND r2.record_type = 'document_revision')"
    )


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
