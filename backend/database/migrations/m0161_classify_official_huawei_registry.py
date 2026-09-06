"""Expose imported Huawei official registry records in the official scope.

The first Huawei hardware-registry import predates the dedicated
``knowledge_source_type`` values used by Knowledge Engine V2.  Its metadata
already carries ``official_only=true`` and an official Huawei source URL, but
the relational source type was left as ``user_document``.  That made the
records disappear from the Knowledge page's official filter even though RAG
could still see them.  This idempotent migration repairs the classification
without changing the document body.
"""

from __future__ import annotations

import json


VERSION = 161
NAME = "classify_official_huawei_registry"


def _metadata(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _official_url(metadata: dict) -> str | None:
    sources = metadata.get("sources")
    if not isinstance(sources, list):
        return None
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("source_url") or "").strip()
        if url.lower().startswith(("https://", "http://")):
            return url
    return None


def upgrade(cursor, use_pg: bool) -> None:
    rows = cursor.execute(
        """
        SELECT id, source, metadata_json
        FROM ai_document
        WHERE LOWER(COALESCE(vendor, '')) = 'huawei'
          AND knowledge_source_type = 'user_document'
        """
    ).fetchall()
    for row in rows:
        document_id, current_source, raw_metadata = row[0], row[1], row[2]
        metadata = _metadata(raw_metadata)
        if str(metadata.get("document_type") or "").lower() != "hardware_manual":
            continue
        if str(metadata.get("source_type") or "").lower() != "official":
            continue
        if str(metadata.get("official_only") or "").lower() not in {"true", "1", "yes"}:
            continue

        official_url = _official_url(metadata)
        if official_url and str(current_source or "").lower() in {"", "upload", "uploaded"}:
            cursor.execute(
                "UPDATE ai_document SET knowledge_source_type = 'official_url', source = ? WHERE id = ?",
                (official_url, document_id),
            )
        else:
            cursor.execute(
                "UPDATE ai_document SET knowledge_source_type = 'official_url' WHERE id = ?",
                (document_id,),
            )


__all__ = ["VERSION", "NAME", "upgrade"]
