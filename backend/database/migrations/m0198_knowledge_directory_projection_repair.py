"""Repair browse-directory paths for documents created after migration 195."""

from __future__ import annotations

import json
from typing import Any

from ai.services.knowledge_metadata import directory_metadata_for_document

from . import m0189_knowledge_v1_provenance as _provenance


VERSION = 198
NAME = "knowledge_directory_projection_repair"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json_value(value: dict[str, Any], use_pg: bool) -> Any:
    """Bind JSONB on PostgreSQL and plain JSON text on SQLite."""

    if use_pg:
        return _provenance._json_value(value, use_pg=True)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def upgrade(cursor, use_pg: bool) -> None:
    """Backfill only documents that do not already have an explicit path.

    Migration 195 ran before later official template/catalog rows were
    published.  This repair is intentionally additive and idempotent: it
    preserves custom paths and derives a root/vendor path only for rows whose
    metadata lacks ``knowledge_directory_path``.
    """

    if not _provenance._table_exists(cursor, "ai_document", use_pg):
        return

    columns = _provenance._columns(cursor, "ai_document", use_pg)
    if "metadata_json" not in columns:
        return

    selected = ["id", "metadata_json"]
    if "document_category" in columns:
        selected.append("document_category")
    if "vendor" in columns:
        selected.append("vendor")
    lock_clause = " FOR UPDATE" if use_pg else ""
    cursor.execute(f"SELECT {', '.join(selected)} FROM ai_document{lock_clause}")

    for row in cursor.fetchall():
        metadata = _provenance._json_load(row[1], {})
        if not isinstance(metadata, dict):
            metadata = {}
        if _text(metadata.get("knowledge_directory_path")):
            continue

        offset = 2
        category = metadata.get("document_category")
        if "document_category" in columns:
            category = category or row[offset]
            offset += 1
        vendor = metadata.get("vendor")
        if "vendor" in columns:
            vendor = vendor or row[offset]

        projection = directory_metadata_for_document(_text(category) or "hardware", vendor)
        if not projection:
            continue

        metadata.update(projection)
        cursor.execute(
            "UPDATE ai_document SET metadata_json = ? WHERE id = ?",
            (_json_value(metadata, use_pg), row[0]),
        )


def downgrade(cursor, use_pg: bool) -> None:
    """Keep derived paths intact; removal requires an explicit data change."""

    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
