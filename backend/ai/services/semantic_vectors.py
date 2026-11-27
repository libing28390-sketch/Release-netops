"""Semantic (bge-m3) chunk vectors: one write contract for every writer.

Ingestion, full reindex and the offline backfill all go through this module
so the ``embedding_v2*`` columns are always written the same way.

Write policy
------------
* Off (``AI_SEMANTIC_EMBEDDING_PROVIDER=none``): nothing is computed and the
  columns stay NULL.
* On: vectors are computed before the database transaction.  If the sidecar
  is unavailable the document is still stored -- with NULL semantic vectors
  that ``scripts/rag_index_maintenance.py backfill`` fills later -- unless
  ``AI_SEMANTIC_EMBEDDING_REQUIRED=1``, which makes the failure fatal.

A stored vector is valid only while model, version and the hash of the text
it was computed from all match; anything else is "stale" and re-embedded by
the backfill.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from ai.providers.embedding import (
    BaseEmbeddingProvider,
    EmbeddingProviderError,
    embed_documents_batch,
    semantic_embedding_provider,
)

logger = logging.getLogger(__name__)

SEMANTIC_COLUMNS = (
    "embedding_v2",
    "embedding_v2_model",
    "embedding_v2_version",
    "embedding_v2_content_hash",
    "embedding_v2_at",
)


def semantic_required() -> bool:
    return str(os.environ.get("AI_SEMANTIC_EMBEDDING_REQUIRED", "0")).strip().lower() in {"1", "true", "yes"}


def content_digest(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def vector_literal(vector: Sequence[float]) -> str:
    """pgvector text form; accepted for both vector(n) and halfvec(n)."""
    return json.dumps([float(value) for value in vector], separators=(",", ":"))


@dataclass
class SemanticBatch:
    """Result of embedding one document's chunks."""

    status: str  # "disabled" | "ok" | "failed"
    vectors: List[Optional[List[float]]] = field(default_factory=list)
    model_id: str = ""
    version: str = ""
    error_code: str | None = None

    def columns_for(self, index: int, text: str, *, now: str | None = None) -> Dict[str, Any]:
        """Column values for chunk ``index``; empty when nothing to write."""
        if self.status != "ok" or index >= len(self.vectors) or self.vectors[index] is None:
            return {}
        return {
            "embedding_v2": vector_literal(self.vectors[index]),
            "embedding_v2_model": self.model_id,
            "embedding_v2_version": self.version,
            "embedding_v2_content_hash": content_digest(text),
            "embedding_v2_at": now or datetime.now(timezone.utc).isoformat(),
        }


def embed_chunks(
    texts: Sequence[str],
    *,
    tenant_id: str,
    task_id: str,
    provider: BaseEmbeddingProvider | None = None,
    sleep_fn: Any = None,
) -> SemanticBatch:
    """Embed chunk texts with the semantic provider (never raises unless required)."""
    try:
        active = provider if provider is not None else semantic_embedding_provider()
    except EmbeddingProviderError:
        if semantic_required():
            raise
        logger.warning("Semantic embedding provider is misconfigured; storing without semantic vectors")
        return SemanticBatch(status="failed", error_code="SEMANTIC_PROVIDER_MISCONFIGURED")
    if active is None:
        return SemanticBatch(status="disabled")
    model_id = str(getattr(active, "model_id", ""))
    version = str(getattr(active, "version", ""))
    if not texts:
        return SemanticBatch(status="ok", model_id=model_id, version=version)
    kwargs: Dict[str, Any] = {
        "provider": active,
        "tenant_id": tenant_id,
        "task_id": task_id,
        "idempotency_namespace": f"semantic:{tenant_id}",
        # The sidecar has its own failure cooldown; one retry is enough.
        "max_retries": 1,
    }
    if sleep_fn is not None:
        kwargs["sleep_fn"] = sleep_fn
    try:
        vectors = embed_documents_batch([str(text or "") or " " for text in texts], **kwargs)
    except Exception as exc:
        if semantic_required():
            raise
        logger.warning("Semantic embedding failed (%s); storing without semantic vectors", type(exc).__name__)
        return SemanticBatch(status="failed", model_id=model_id, version=version, error_code="SEMANTIC_EMBEDDING_FAILED")
    return SemanticBatch(status="ok", vectors=[list(vector) for vector in vectors], model_id=model_id, version=version)


def semantic_column_type(cursor) -> str | None:
    """``halfvec(1024)`` / ``vector(1024)`` or None when the column is absent."""
    try:
        row = cursor.execute(
            "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relname = 'ai_document_chunk' "
            "AND a.attname = 'embedding_v2' AND NOT a.attisdropped"
        ).fetchone()
    except Exception:
        return None
    return str(row[0]) if row and row[0] else None


def guard_column(cursor, batch: SemanticBatch) -> SemanticBatch:
    """Drop the semantic vectors when the column is missing or sized differently.

    A dimension mismatch (for example a 768-d model configured against the
    1024-d column) must not make the whole document insert fail; it is
    reported and the backfill/operator fixes the configuration.
    """
    if batch.status != "ok" or not batch.vectors:
        return batch
    column_type = semantic_column_type(cursor)
    if column_type is None:
        return SemanticBatch(status="failed", error_code="SEMANTIC_COLUMN_MISSING")
    import re as _re

    match = _re.search(r"\((\d+)\)", column_type)
    dims = {len(vector) for vector in batch.vectors if vector is not None}
    if match and dims and dims != {int(match.group(1))}:
        if semantic_required():
            raise EmbeddingProviderError("Semantic vector dimensions do not match the embedding_v2 column")
        logger.error("Semantic vector dimensions %s do not match column %s; not stored", sorted(dims), column_type)
        return SemanticBatch(status="failed", model_id=batch.model_id, version=batch.version, error_code="SEMANTIC_DIMENSION_MISMATCH")
    return batch
