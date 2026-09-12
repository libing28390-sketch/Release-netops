"""Make incomplete knowledge taxonomy explicit and non-retrievable.

Legacy uploads could be active and searchable while their vendor/product
facets were empty.  This migration keeps those source documents visible to
administrators, records a stable governance reason, and removes them from RAG
until a reviewer supplies authoritative taxonomy evidence.
"""

from __future__ import annotations

import json
from typing import Any

from ai.services.knowledge_metadata import (
    METADATA_GOVERNANCE_PENDING_REVIEW,
    metadata_governance,
)

from . import m0189_knowledge_v1_provenance as _provenance


VERSION = 200
NAME = "knowledge_metadata_governance"

_DOCUMENT_COLUMNS = {
    "metadata_governance_status": "TEXT NOT NULL DEFAULT 'ready'",
    "metadata_governance_reason": "TEXT NOT NULL DEFAULT ''",
}


def _json_load(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_value(value: dict[str, Any], use_pg: bool) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if not use_pg:
        return encoded
    try:
        from psycopg2.extras import Json

        return Json(value, dumps=lambda item: json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    except ImportError:  # pragma: no cover - PostgreSQL runtime includes psycopg2
        return encoded


def upgrade(cursor, use_pg: bool) -> None:
    if not _provenance._table_exists(cursor, "ai_document", use_pg):
        return

    columns = _provenance._columns(cursor, "ai_document", use_pg)
    for name, definition in _DOCUMENT_COLUMNS.items():
        if name in columns:
            continue
        cursor.execute(f"ALTER TABLE ai_document ADD COLUMN {name} {definition}")
        columns.add(name)

    required = {"id", "metadata_json", "vendor", "product_family", "product_series", "exclude_from_rag"}
    if not required <= columns:
        return

    cursor.execute(
        "SELECT id, name, vendor, product_family, product_series, metadata_json "
        "FROM ai_document"
        + (" FOR UPDATE" if use_pg else "")
    )
    for row in cursor.fetchall():
        document_id, name, vendor, family, series, raw_metadata = row
        metadata = _json_load(raw_metadata)
        metadata.setdefault("vendor", vendor)
        metadata.setdefault("product_family", family)
        metadata.setdefault("product_series", series)
        status, reason = metadata_governance(metadata, name=name)
        if status != METADATA_GOVERNANCE_PENDING_REVIEW:
            continue

        metadata["metadata_governance_status"] = status
        metadata["metadata_governance_reason"] = reason
        assignments = [
            "metadata_governance_status = ?",
            "metadata_governance_reason = ?",
            "metadata_json = ?",
            "exclude_from_rag = 1",
        ]
        values: list[Any] = [status, reason, _json_value(metadata, use_pg)]
        if "ingestion_status" in columns:
            assignments.append("ingestion_status = ?")
            values.append("pending_review")
        values.append(document_id)
        cursor.execute(
            f"UPDATE ai_document SET {', '.join(assignments)} WHERE id = ?",
            values,
        )


def downgrade(cursor, use_pg: bool) -> None:
    """Keep the source rows safe; rollback only removes additive columns."""

    del use_pg
    for name in _DOCUMENT_COLUMNS:
        try:
            cursor.execute(f"ALTER TABLE ai_document DROP COLUMN {name}")
        except Exception:
            # A rollback must not hide the source document if a legacy engine
            # cannot drop a column.  The forward safety state remains visible.
            continue


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
