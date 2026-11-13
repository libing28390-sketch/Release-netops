"""Backfill the browse-directory projection for existing V1 documents."""

from __future__ import annotations

from typing import Any

from ai.services.knowledge_metadata import directory_metadata_for_document

from . import m0189_knowledge_v1_provenance as _provenance


VERSION = 195
NAME = "knowledge_directory_projection"


def _text(value: Any) -> str:
    return str(value or "").strip()


def upgrade(cursor, use_pg: bool) -> None:
    """Populate missing directory metadata without changing document content.

    Existing non-empty paths are authoritative and are intentionally retained.
    For documents created before directory metadata was wired through the
    publication path, the semantic category/vendor columns determine a stable
    root/vendor browse path. An empty category falls back to the product root;
    an unknown vendor remains at that root for safe manual classification.
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
    cursor.execute(
        f"SELECT {', '.join(selected)} FROM ai_document "
        "WHERE metadata_json IS NOT NULL FOR UPDATE"
    )

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

        category = _text(category) or "hardware"
        projection = directory_metadata_for_document(category, vendor)
        if not projection:
            continue

        metadata.update(projection)
        cursor.execute(
            "UPDATE ai_document SET metadata_json = ? WHERE id = ?",
            (_provenance._json_value(metadata, use_pg), row[0]),
        )


def downgrade(cursor, use_pg: bool) -> None:
    """Do not erase user-authored or migrated metadata during downgrade."""
    del cursor, use_pg
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
