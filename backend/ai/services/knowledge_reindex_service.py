"""Metadata Reindex service for the RAG Pipeline v2.

Reindexing is deliberately document-scoped and transactional.  It never
deletes source rows or directories; a document's old chunks are replaced only
after parsing, validation, and all embeddings for the new chunk set succeed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from database.core import _USE_PG, get_db_connection
from ai.chunking.engine import ChunkingEngine
from ai.providers.embedding import (
    EmbeddingProviderError,
    assert_pgvector_column_compatible,
    embed_documents_batch,
    embedding_contract,
    embedding_metadata,
    embedding_provider,
)
from ai.security.gateway import SecurityBlocked
from ai.services.knowledge_metadata import (
    MetadataParseError,
    MetadataValidationError,
    json_safe_metadata,
    merge_metadata,
    metadata_columns,
    chunk_projection_metadata,
    validate_metadata,
)
from ai.services.knowledge_source_parser import KnowledgeSourceParseError, parse_knowledge_source
from ai.services.retrieval_contract import retrieval_cache
from ai.services.metrics import ai_metrics


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 250
MIN_BATCH_SIZE = 1
MAX_BATCH_SIZE = 5000
DEFAULT_LEASE_SECONDS = 15 * 60
_CONTROL_KEY = "_db022_control"
_SUPPORTED_OPERATIONS = frozenset({"reparse", "rechunk", "reindex"})


class ReindexLeaseLost(RuntimeError):
    """Raised when a worker no longer owns the database lease."""


class ReindexDocumentChanged(RuntimeError):
    """Raised when a document changes while its derived rows are rebuilding."""

    code = "KNOWLEDGE_DOCUMENT_CHANGED_DURING_REBUILD"


def _clamp_batch_size(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_BATCH_SIZE
    return max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, parsed))


class _ReindexLease:
    """A database-backed expiring lease using the existing V1 lock table.

    ``locked_at`` stores an opaque owner token, so a stale worker cannot
    heartbeat or release a lease that a replacement worker acquired.  No
    document rows are changed while acquiring, heartbeating, or releasing.
    """

    def __init__(self, job_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS):
        self.lock_name = f"knowledge_reindex:{job_id}"
        self.owner = f"reindex-worker:{uuid.uuid4().hex}"
        self.lease_seconds = max(30, int(lease_seconds))
        self._held = False

    def acquire(self) -> bool:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires = now + timedelta(seconds=self.lease_seconds)
        with get_db_connection() as conn:
            try:
                conn.execute("DELETE FROM scheduler_locks WHERE expires_at < ?", (now.isoformat(),))
                conn.execute(
                    "INSERT INTO scheduler_locks (lock_name, locked_at, expires_at) VALUES (?, ?, ?)",
                    (self.lock_name, self.owner, expires.isoformat()),
                )
                conn.commit()
                ai_metrics.job_event("reindex", "lease_acquired")
                self._held = True
                return True
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                ai_metrics.job_event("reindex", "lease_held")
                return False

    def heartbeat(self) -> bool:
        if not self._held:
            return False
        now = datetime.now(timezone.utc).replace(microsecond=0)
        expires = now + timedelta(seconds=self.lease_seconds)
        with get_db_connection() as conn:
            try:
                cursor = conn.execute(
                    "UPDATE scheduler_locks SET expires_at = ? "
                    "WHERE lock_name = ? AND locked_at = ? AND expires_at >= ?",
                    (expires.isoformat(), self.lock_name, self.owner, now.isoformat()),
                )
                conn.commit()
                rowcount = getattr(cursor, "rowcount", 0)
                if int(rowcount or 0) != 1:
                    self._held = False
                    ai_metrics.job_event("reindex", "lease_lost")
                    return False
                return True
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                self._held = False
                ai_metrics.job_event("reindex", "lease_error")
                return False

    def release(self) -> None:
        if not self._held:
            return
        with get_db_connection() as conn:
            try:
                conn.execute(
                    "DELETE FROM scheduler_locks WHERE lock_name = ? AND locked_at = ?",
                    (self.lock_name, self.owner),
                )
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
            finally:
                self._held = False


class KnowledgeReindexService:
    def _ensure_job_table(self, cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_knowledge_reindex_job (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL DEFAULT 'tenant-default',
                scope_json TEXT NOT NULL DEFAULT '{}',
                dry_run INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'queued',
                total INTEGER NOT NULL DEFAULT 0,
                parsed INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                updated INTEGER NOT NULL DEFAULT 0,
                rechunked INTEGER NOT NULL DEFAULT 0,
                embedding_success INTEGER NOT NULL DEFAULT 0,
                embedding_failed INTEGER NOT NULL DEFAULT 0,
                error_log_json TEXT NOT NULL DEFAULT '[]',
                operation TEXT NOT NULL DEFAULT 'reindex',
                action_id TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        # m0145 adds these columns for existing installations.  The worker is
        # also able to start on a database that has not yet run the migration
        # (for example during a rolling deployment), so keep this repair
        # idempotent at the runtime boundary as well.  Check the schema first;
        # catching PostgreSQL ``duplicate_column`` would otherwise leave the
        # transaction aborted for the subsequent INSERT.
        existing = self._table_columns(cursor, "ai_knowledge_reindex_job")
        if "operation" not in existing:
            cursor.execute("ALTER TABLE ai_knowledge_reindex_job ADD COLUMN operation TEXT NOT NULL DEFAULT 'reindex'")
        if "action_id" not in existing:
            cursor.execute("ALTER TABLE ai_knowledge_reindex_job ADD COLUMN action_id TEXT")

    @staticmethod
    def _external_scope(scope: Dict[str, Any] | None) -> dict[str, Any]:
        """Strip internal checkpoint metadata before returning an API scope."""
        value = dict(scope or {})
        value.pop(_CONTROL_KEY, None)
        return value

    @staticmethod
    def _stored_scope(scope: Dict[str, Any], *, batch_size: int, cursor: str | None = None) -> dict[str, Any]:
        """Persist a restart checkpoint without exposing the cursor to callers."""
        value = KnowledgeReindexService._external_scope(scope)
        value[_CONTROL_KEY] = {
            "batch_size": _clamp_batch_size(batch_size),
            "cursor": str(cursor) if cursor else None,
        }
        return value

    @staticmethod
    def _decode_scope(raw_scope: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            value = json.loads(raw_scope or "{}")
        except (TypeError, ValueError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        control = value.get(_CONTROL_KEY)
        if not isinstance(control, dict):
            control = {}
        return KnowledgeReindexService._external_scope(value), control

    @staticmethod
    def _table_columns(cursor, table: str) -> set[str]:
        cursor.execute(f"SELECT * FROM {table} WHERE 1 = 0")
        return {str(description[0]) for description in (cursor.description or [])}

    def _scope_clause(self, cursor, scope: Dict[str, Any], tenant_id: str) -> tuple[str, list[Any]]:
        columns = self._table_columns(cursor, "ai_document")
        where = ["d.status = 'active'", "(d.tenant_id = ? OR d.tenant_id = 'tenant-default')"]
        params: list[Any] = [tenant_id]
        if scope.get("document_id"):
            key = str(scope["document_id"])
            if "document_id" in columns:
                where.append("(d.id = ? OR d.document_id = ?)")
                params.extend([key, key])
            else:
                where.append("d.id = ?")
                params.append(key)
        if scope.get("vendor") and "vendor" in columns:
            where.append("LOWER(d.vendor) = LOWER(?)")
            params.append(str(scope["vendor"]))
        if scope.get("directory_path") and "metadata_json" in columns:
            where.append("LOWER(COALESCE(CAST(d.metadata_json AS TEXT), '')) LIKE ?")
            params.append("%" + str(scope["directory_path"]).strip("/").lower() + "%")
        return " AND ".join(where), params

    def _count_documents(self, scope: Dict[str, Any], tenant_id: str) -> int:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            where, params = self._scope_clause(cursor, scope, tenant_id)
            row = cursor.execute(f"SELECT COUNT(*) FROM ai_document d WHERE {where}", params).fetchone()
            return int(row[0] or 0) if row else 0

    def _select_document_batch(
        self,
        scope: Dict[str, Any],
        tenant_id: str,
        *,
        after_id: str | None,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        """Fetch a stable keyset page without loading the full corpus."""
        safe_batch_size = _clamp_batch_size(batch_size)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            where, params = self._scope_clause(cursor, scope, tenant_id)
            if after_id:
                where += " AND d.id > ?"
                params.append(str(after_id))
            cursor.execute(
                f"SELECT * FROM ai_document d WHERE {where} ORDER BY d.id LIMIT ?",
                [*params, safe_batch_size],
            )
            descriptions = [str(item[0]) for item in (cursor.description or [])]
            return [dict(zip(descriptions, row)) for row in cursor.fetchall()]

    def _select_documents(self, scope: Dict[str, Any], tenant_id: str) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            where, params = self._scope_clause(cursor, scope, tenant_id)
            cursor.execute(f"SELECT * FROM ai_document d WHERE {where} ORDER BY d.id", params)
            descriptions = [str(item[0]) for item in (cursor.description or [])]
            return [dict(zip(descriptions, row)) for row in cursor.fetchall()]

    @staticmethod
    def _json_value(value: Dict[str, Any]) -> Any:
        if _USE_PG:
            try:
                from psycopg2.extras import Json
                return Json(value, dumps=lambda item: json.dumps(item, ensure_ascii=False))
            except ImportError:
                return json_safe_metadata(value)
        return json_safe_metadata(value)

    def _update_job(self, job_id: str, **values: Any) -> None:
        if not values:
            return
        allowed = {
            "scope_json", "status", "total", "parsed", "failed", "updated", "rechunked",
            "embedding_success", "embedding_failed", "error_log_json", "started_at",
            "finished_at", "updated_at",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unsupported reindex job update field(s): {sorted(unknown)}")
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            self._ensure_job_table(cursor)
            cursor.execute(f"UPDATE ai_knowledge_reindex_job SET {assignments} WHERE id = ?", [*values.values(), job_id])
            conn.commit()

    def create_job(
        self,
        *,
        tenant_id: str = "tenant-default",
        scope: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
        run_async: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE,
        operation: str = "reindex",
        action_id: str | None = None,
    ) -> Dict[str, Any]:
        operation = str(operation or "reindex").strip().lower()
        if operation not in _SUPPORTED_OPERATIONS:
            raise ValueError("Unsupported knowledge document operation")
        scope = self._external_scope(scope)
        safe_batch_size = _clamp_batch_size(batch_size)
        job_id = f"reindex_{uuid.uuid4().hex[:16]}"
        now = _now()
        total = self._count_documents(scope, tenant_id)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            self._ensure_job_table(cursor)
            cursor.execute(
                """INSERT INTO ai_knowledge_reindex_job
                (id, tenant_id, scope_json, dry_run, status, total, operation, action_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
                (
                    job_id, tenant_id,
                    json.dumps(self._stored_scope(scope, batch_size=safe_batch_size), ensure_ascii=False),
                    1 if dry_run else 0, total, operation, action_id, now, now,
                ),
            )
            conn.commit()
        ai_metrics.job_event("reindex", "enqueued")
        if run_async:
            thread = threading.Thread(target=self.run_job, args=(job_id,), daemon=True, name=f"rag-reindex-{job_id}")
            thread.start()
        else:
            self.run_job(job_id)
        return self.get_status(job_id) or {
            "id": job_id,
            "status": "queued",
            "total": total,
            "batch_size": safe_batch_size,
            "operation": operation,
            "action_id": action_id,
        }

    def _record_failure(self, job_id: str, document: dict[str, Any], error: str) -> None:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            self._ensure_job_table(cursor)
            cursor.execute("SELECT error_log_json, failed FROM ai_knowledge_reindex_job WHERE id = ?", (job_id,))
            row = cursor.fetchone() or ("[]", 0)
            try:
                errors = json.loads(row[0] or "[]")
            except (TypeError, ValueError):
                errors = []
            errors.append({"document_id": document.get("id"), "name": document.get("name"), "error": error})
            cursor.execute(
                "UPDATE ai_knowledge_reindex_job SET failed = ?, error_log_json = ?, updated_at = ? WHERE id = ?",
                (int(row[1] or 0) + 1, json.dumps(errors, ensure_ascii=False), _now(), job_id),
            )
            conn.commit()
        ai_metrics.job_event("reindex", "document_failed")

    def _mark_document_parse_error(self, document: dict[str, Any], error: str) -> None:
        columns = set(document)
        if "metadata_parse_status" not in columns:
            return
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE ai_document SET metadata_parse_status = ?, metadata_parse_error = ?, ingestion_status = ? WHERE id = ?",
                ("failed", error[:2000], "failed", document["id"]),
            )
            conn.commit()

    def _sync_action_status(self, job: dict[str, Any], status: str, *, error_code: str | None = None) -> None:
        """Project a terminal job outcome to the KUI action ledger."""
        action_id = str(job.get("action_id") or "").strip()
        if not action_id:
            return
        try:
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE ai_knowledge_document_action SET status = ?, error_code = ?, completed_at = ? WHERE id = ?",
                    (status, error_code, _now(), action_id),
                )
                conn.commit()
        except Exception:
            # The job remains the source of truth for recovery.  A legacy
            # installation without m0145 must not crash a worker.
            return

    def _process_document(
        self,
        document: dict[str, Any],
        dry_run: bool,
        operation: str = "reindex",
    ) -> dict[str, int]:
        """Process one document for an explicitly confirmed operation.

        Reparse is deliberately metadata-only.  Rechunk and Reindex use the
        existing transactional replacement path; Rechunk still validates the
        source before replacing chunks because chunk metadata is part of the
        retrieval contract and must not be written from an unparsed body.
        """
        operation = str(operation or "reindex").strip().lower()
        if operation not in _SUPPORTED_OPERATIONS:
            raise ValueError("Unsupported knowledge document operation")
        if operation == "reparse":
            return self._process_reparse(document, dry_run)
        return self._process_full_reindex(document, dry_run)

    def _process_reparse(self, document: dict[str, Any], dry_run: bool) -> dict[str, int]:
        """Parse and persist metadata without touching document chunks."""
        raw = document.get("original_content") or document.get("normalized_content") or ""
        try:
            parsed = parse_knowledge_source(str(raw), filename=str(document.get("name") or ""))
        except KnowledgeSourceParseError as exc:
            raise ValueError(f"知识文档文件格式无法解析: {exc.message}") from exc
        source_metadata: dict[str, Any] = {}
        raw_meta = document.get("metadata_json")
        if isinstance(raw_meta, dict):
            source_metadata = raw_meta
        elif raw_meta:
            try:
                loaded = json.loads(str(raw_meta))
                if isinstance(loaded, dict):
                    source_metadata = loaded
            except (TypeError, ValueError):
                source_metadata = {}
        directory_path = source_metadata.get("knowledge_directory_path") or source_metadata.get("source_relative_path")
        validated = validate_metadata(
            parsed.metadata,
            directory_path=directory_path,
            name=document.get("name"),
            allow_missing_required=parsed.metadata_parse_status == "missing",
        )
        merged = merge_metadata(validated, source_metadata)
        merged.setdefault("document_id", document.get("document_id") or document.get("id"))
        merged.setdefault("status", document.get("status") or "active")
        merged.setdefault("exclude_from_rag", False)
        content = parsed.content.strip()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        merged.setdefault("document_version", str(merged.get("source_version") or content_hash[:16]))
        merged.setdefault("parser_version", ChunkingEngine.parser_version)
        merged.setdefault("index_version", document.get("index_version") or ChunkingEngine.default_index_version)
        platform = merged.get("cli_platform")
        if str(platform or "").lower() == "all":
            platform = None
        vendor = merged.get("vendor") or document.get("vendor") or "all"
        if dry_run:
            return {"parsed": 1, "updated": 0, "rechunked": 0, "embedding_success": 0, "embedding_failed": 0}

        old_content = str(document.get("normalized_content") or "").strip()
        ingestion_status = "ready" if old_content == content else "rechunk_required"
        now = _now()
        values = {
            "vendor": vendor,
            "platform": platform,
            "metadata_json": self._json_value(merged),
            "normalized_content": content,
            "fts_text": f"{document.get('name') or ''}\n{content}",
            "original_content": parsed.original_content,
            "content_hash": content_hash,
            "ingestion_status": ingestion_status,
            "metadata_parse_status": parsed.metadata_parse_status,
            "metadata_parse_error": parsed.metadata_parse_error,
            "parser_version": merged.get("parser_version"),
            "document_version": merged.get("document_version"),
            "index_version": merged.get("index_version"),
            "updated_at": now,
            "exclude_from_rag": 1 if merged.get("exclude_from_rag") else 0,
            **metadata_columns(merged),
        }
        with get_db_connection() as conn:
            cursor = conn.cursor()
            available_docs = self._table_columns(cursor, "ai_document")
            values = {key: value for key, value in values.items() if key in available_docs}
            cursor.execute(
                f"UPDATE ai_document SET {', '.join(f'{key} = ?' for key in values)} WHERE id = ?",
                [*values.values(), document["id"]],
            )
            conn.commit()
        retrieval_cache.invalidate_documents([document["id"]])
        return {"parsed": 1, "updated": 1, "rechunked": 0, "embedding_success": 0, "embedding_failed": 0}

    def _process_full_reindex(self, document: dict[str, Any], dry_run: bool) -> dict[str, int]:
        # ``original_content`` is the immutable source fact while
        # ``normalized_content`` is the current derived body.  Rebuilds must
        # consume the latest normalized body after an edit, but parse metadata
        # from the original source so a re-chunk never erases Front Matter or
        # rewrites the V1 source fact.
        original_content = str(document.get("original_content") or "")
        normalized_content = str(document.get("normalized_content") or "").strip()
        metadata_source = original_content or normalized_content
        try:
            parsed = parse_knowledge_source(metadata_source, filename=str(document.get("name") or ""))
        except KnowledgeSourceParseError as exc:
            raise ValueError(f"知识文档文件格式无法解析: {exc.message}") from exc
        source_metadata = {}
        raw_meta = document.get("metadata_json")
        if isinstance(raw_meta, dict):
            source_metadata = raw_meta
        elif raw_meta:
            try:
                loaded = json.loads(str(raw_meta))
                if isinstance(loaded, dict):
                    source_metadata = loaded
            except (TypeError, ValueError):
                source_metadata = {}
        directory_path = source_metadata.get("knowledge_directory_path") or source_metadata.get("source_relative_path")
        validated = validate_metadata(
            parsed.metadata,
            directory_path=directory_path,
            name=document.get("name"),
            allow_missing_required=parsed.metadata_parse_status == "missing",
        )
        merged = merge_metadata(validated, source_metadata)
        merged.setdefault("document_id", document.get("document_id") or document.get("id"))
        merged.setdefault("status", document.get("status") or "active")
        merged.setdefault("exclude_from_rag", False)
        content = normalized_content or parsed.content.strip()
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        merged.setdefault("document_version", str(merged.get("source_version") or content_hash[:16]))
        merged.setdefault("parser_version", ChunkingEngine.parser_version)
        merged.setdefault("index_version", ChunkingEngine.default_index_version)
        platform = merged.get("cli_platform")
        if str(platform or "").lower() == "all":
            platform = None
        vendor = merged.get("vendor") or document.get("vendor") or "all"
        chunks = ChunkingEngine().chunk(
            content,
            document_identity=str(document["id"]),
            document_metadata={**merged, "vendor": vendor, "platform": platform},
            target_tokens_override=800,
        )
        vectors = embed_documents_batch(
            [chunk.embedding_content for chunk in chunks],
            provider=embedding_provider,
            tenant_id=str(document.get("tenant_id") or "tenant-default"),
            task_id=f"knowledge-reindex:{document['id']}",
            idempotency_namespace=f"knowledge:{document.get('tenant_id') or 'tenant-default'}",
        )
        contract = embedding_contract(embedding_provider)
        embedding_info = embedding_metadata()
        counters = {"parsed": 1, "updated": 0, "rechunked": len(chunks), "embedding_success": len(vectors), "embedding_failed": 0}
        if dry_run:
            return counters

        now = _now()
        values = {
            "vendor": vendor,
            "platform": platform,
            "metadata_json": self._json_value(merged),
            "normalized_content": content,
            "fts_text": f"{document.get('name') or ''}\n{content}",
            "content_hash": content_hash,
            "chunking_version": "v2",
            "ingestion_status": "ready",
            "metadata_parse_status": parsed.metadata_parse_status,
            "metadata_parse_error": parsed.metadata_parse_error,
            "chunker_version": ChunkingEngine.chunker_version,
            "parser_version": merged.get("parser_version"),
            "document_version": merged.get("document_version"),
            "index_version": merged.get("index_version"),
            "embedding_mode": contract.mode,
            "embedding_contract_version": contract.contract_version,
            "updated_at": now,
            "exclude_from_rag": 1 if merged.get("exclude_from_rag") else 0,
            **metadata_columns(merged),
            "embedding_model": embedding_info.get("embedding_model"),
            "embedding_dimensions": embedding_info.get("embedding_dimensions"),
            "embedding_version": embedding_info.get("embedding_version"),
        }
        with get_db_connection() as conn:
            cursor = conn.cursor()
            available_docs = self._table_columns(cursor, "ai_document")
            values = {key: value for key, value in values.items() if key in available_docs}
            predicates = ["id = ?"]
            predicate_params: list[Any] = [document["id"]]
            if "tenant_id" in available_docs:
                predicates.append("COALESCE(tenant_id, 'tenant-default') = ?")
                predicate_params.append(str(document.get("tenant_id") or "tenant-default"))
            expected_updated_at = str(document.get("_reindex_expected_updated_at") or "").strip()
            if expected_updated_at and "updated_at" in available_docs:
                predicates.append("updated_at = ?")
                predicate_params.append(expected_updated_at)
            cursor.execute(
                f"UPDATE ai_document SET {', '.join(f'{key} = ?' for key in values)} WHERE {' AND '.join(predicates)}",
                [*values.values(), *predicate_params],
            )
            if expected_updated_at and int(getattr(cursor, "rowcount", 0) or 0) != 1:
                raise ReindexDocumentChanged()
            cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (document["id"],))
            available_chunks = self._table_columns(cursor, "ai_document_chunk")
            assert_pgvector_column_compatible(cursor, expected_dimensions=contract.dimensions)
            for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
                section = chunk.to_dict()["section"]
                chunk_metadata = dict(merged)
                chunk_metadata.update(chunk.metadata)
                chunk_metadata.update({"chunk_index": index, "chunk_idx": index, "section": section})
                chunk_metadata = chunk_projection_metadata(chunk_metadata)
                chunk_values = {
                    "id": chunk.chunk_id,
                    "document_id": document["id"],
                    "content": chunk.raw_content,
                    "raw_content": chunk.raw_content,
                    "embedding_content": chunk.embedding_content,
                    "embedding": json.dumps(vector),
                    "embedding_vector": json.dumps(vector, separators=(",", ":")),
                    "search_text": f"{section}\n{chunk.embedding_content}",
                    "retrieval_index_version": "retrieval-v1",
                    "metadata_json": self._json_value(chunk_metadata),
                    "page": int(chunk.page or chunk.source_locator.get("line_start") or index + 1),
                    "section": section,
                    "created_at": now,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "chunk_role": chunk.chunk_role,
                    "chunk_type": chunk.chunk_type,
                    "ordinal": chunk.ordinal,
                    "heading_path_json": json.dumps(list(chunk.heading_path), ensure_ascii=False),
                    "token_count": chunk.token_count,
                    "content_hash": chunk.content_hash,
                    "source_locator_json": json.dumps(chunk.source_locator, ensure_ascii=False),
                    "chunking_version": "v2",
                    "is_retrieval_candidate": 1 if chunk.is_retrieval_candidate else 0,
                    "oversize_reason": chunk.oversize_reason,
                    "chunker_version": ChunkingEngine.chunker_version,
                    "structure_types_json": json.dumps(list(chunk.structure_types), ensure_ascii=False),
                    "neighbor_chunk_ids_json": json.dumps(list(chunk.neighbor_chunk_ids), ensure_ascii=False),
                    "parser_version": chunk.parser_version,
                    "document_version": chunk.document_version,
                    "index_version": chunk.index_version,
                    "embedding_mode": contract.mode,
                    "embedding_contract_version": contract.contract_version,
                    "chunk_index": index,
                    "embedding_model": embedding_info.get("embedding_model"),
                    "embedding_dimensions": len(vector),
                    "embedding_version": embedding_info.get("embedding_version"),
                    **{key: value for key, value in metadata_columns(merged).items() if key != "document_id"},
                }
                chunk_values = {key: value for key, value in chunk_values.items() if key in available_chunks}
                cursor.execute(
                    f"INSERT INTO ai_document_chunk ({', '.join(chunk_values)}) VALUES ({', '.join('?' for _ in chunk_values)})",
                    list(chunk_values.values()),
                )
            conn.commit()
        counters["updated"] = 1
        retrieval_cache.invalidate_documents([document["id"]])
        return counters

    def _read_job_record(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Read the raw job row, including the private restart checkpoint."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            self._ensure_job_table(cursor)
            cursor.execute("SELECT * FROM ai_knowledge_reindex_job WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            descriptions = [str(item[0]) for item in (cursor.description or [])]
            return dict(zip(descriptions, row))

    def run_job(self, job_id: str) -> Dict[str, Any]:
        raw = self._read_job_record(job_id)
        if not raw:
            raise KeyError(job_id)
        if str(raw.get("status") or "").lower() in {"completed", "succeeded", "cancelled"}:
            return self.get_status(job_id) or {}

        scope, control = self._decode_scope(raw.get("scope_json"))
        tenant_id = raw.get("tenant_id") or "tenant-default"
        dry_run = bool(raw.get("dry_run"))
        operation = str(raw.get("operation") or "reindex").strip().lower()
        if operation not in _SUPPORTED_OPERATIONS:
            self._update_job(job_id, status="failed", error_log_json=json.dumps([{"code": "KNOWLEDGE_OPERATION_INVALID"}], ensure_ascii=False), finished_at=_now())
            self._sync_action_status(raw, "failed", error_code="KNOWLEDGE_OPERATION_INVALID")
            return self.get_status(job_id) or raw
        batch_size = _clamp_batch_size(control.get("batch_size"))
        cursor_checkpoint = str(control.get("cursor") or "") or None
        lease = _ReindexLease(job_id)
        if not lease.acquire():
            # Another process owns the job.  Returning the current snapshot is
            # intentionally idempotent and avoids a second worker mutating it.
            logger.info("[RAG reindex] job=%s lease is held; skipping duplicate worker", job_id)
            return self.get_status(job_id) or raw

        counters = {
            "parsed": int(raw.get("parsed") or 0),
            "failed": int(raw.get("failed") or 0),
            "updated": int(raw.get("updated") or 0),
            "rechunked": int(raw.get("rechunked") or 0),
            "embedding_success": int(raw.get("embedding_success") or 0),
            "embedding_failed": int(raw.get("embedding_failed") or 0),
        }
        try:
            total = self._count_documents(scope, str(tenant_id))
            self._update_job(
                job_id,
                status="running",
                started_at=raw.get("started_at") or _now(),
                total=total,
                scope_json=json.dumps(
                    self._stored_scope(scope, batch_size=batch_size, cursor=cursor_checkpoint),
                    ensure_ascii=False,
                ),
            )
            while True:
                if not lease.heartbeat():
                    raise ReindexLeaseLost(job_id)
                documents = self._select_document_batch(
                    scope, str(tenant_id), after_id=cursor_checkpoint, batch_size=batch_size,
                )
                if not documents:
                    break
                for document in documents:
                    if not lease.heartbeat():
                        raise ReindexLeaseLost(job_id)
                    try:
                        # Keep a compare-and-set snapshot alongside the
                        # document.  The long-standing two-argument seam
                        # remains patchable for V1/DB-022 compatibility tests.
                        document = dict(document)
                        document["_reindex_expected_updated_at"] = document.get("updated_at")
                        if operation == "reindex":
                            # Keep the long-standing two-argument seam
                            # patchable for V1/DB-022 compatibility tests.
                            result = self._process_document(document, dry_run)
                        else:
                            result = self._process_document(document, dry_run, operation=operation)
                        for key in ("parsed", "updated", "rechunked", "embedding_success", "embedding_failed"):
                            counters[key] += int(result.get(key) or 0)
                    except (EmbeddingProviderError, SecurityBlocked, MetadataParseError, MetadataValidationError, ValueError) as exc:
                        error = str(exc)
                        self._record_failure(job_id, document, error)
                        self._mark_document_parse_error(document, error)
                        counters["failed"] += 1
                    except Exception as exc:  # keep one bad document from aborting the batch
                        error = f"{type(exc).__name__}: {exc}"
                        self._record_failure(job_id, document, error)
                        counters["failed"] += 1
                        if "embed" in error.lower() or "vector" in error.lower():
                            counters["embedding_failed"] += 1

                # Keyset checkpoint is committed only after every document in
                # this batch has reached a terminal per-document outcome.
                cursor_checkpoint = str(documents[-1].get("id") or cursor_checkpoint or "") or None
                self._update_job(
                    job_id,
                    **counters,
                    scope_json=json.dumps(
                        self._stored_scope(scope, batch_size=batch_size, cursor=cursor_checkpoint),
                        ensure_ascii=False,
                    ),
                )

            self._update_job(
                job_id,
                **counters,
                status="completed",
                finished_at=_now(),
                scope_json=json.dumps(self._stored_scope(scope, batch_size=batch_size), ensure_ascii=False),
            )
            ai_metrics.job_event("reindex", "succeeded")
            self._sync_action_status(
                raw,
                "failed" if counters["failed"] else "succeeded",
                error_code="KNOWLEDGE_ACTION_PARTIAL_FAILURE" if counters["failed"] else None,
            )
        except ReindexLeaseLost:
            # A replacement worker can safely resume from the last committed
            # keyset checkpoint.  The current document is idempotent and may
            # be retried; it is never marked successful speculatively.
            logger.warning("[RAG reindex] job=%s lease lost; checkpoint retained", job_id)
            ai_metrics.job_event("reindex", "lease_lost")
            try:
                self._update_job(
                    job_id,
                    **counters,
                    status="retry_wait",
                    scope_json=json.dumps(
                        self._stored_scope(scope, batch_size=batch_size, cursor=cursor_checkpoint),
                        ensure_ascii=False,
                    ),
                )
            except Exception:
                logger.error("[RAG reindex] job=%s could not persist lease-loss checkpoint", job_id, exc_info=True)
            self._sync_action_status(raw, "failed", error_code="KNOWLEDGE_ACTION_LEASE_LOST")
        except Exception as exc:
            logger.error("[RAG reindex] job=%s failed: %s", job_id, type(exc).__name__, exc_info=True)
            ai_metrics.job_event("reindex", "failed")
            self._update_job(
                job_id,
                **counters,
                status="failed",
                finished_at=_now(),
                scope_json=json.dumps(
                    self._stored_scope(scope, batch_size=batch_size, cursor=cursor_checkpoint),
                    ensure_ascii=False,
                ),
            )
            self._sync_action_status(raw, "failed", error_code="KNOWLEDGE_ACTION_JOB_FAILED")
        finally:
            lease.release()
        return self.get_status(job_id) or {}

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        value = self._read_job_record(job_id)
        if value is None:
            return None
        scope, control = self._decode_scope(value.pop("scope_json", "{}"))
        value["scope"] = scope
        value["batch_size"] = _clamp_batch_size(control.get("batch_size"))
        value["checkpointed"] = bool(control.get("cursor"))
        try:
            value["errors"] = json.loads(value.pop("error_log_json") or "[]")
        except (TypeError, ValueError):
            value["errors"] = []
        value["dry_run"] = bool(value.get("dry_run"))
        value["processed"] = int(value.get("parsed") or 0) + int(value.get("failed") or 0)
        total = int(value.get("total") or 0)
        value["progress_percent"] = 100 if total == 0 else round(min(100, value["processed"] * 100 / total), 2)
        return value

    def retry(self, job_id: str, *, run_async: bool = True) -> Dict[str, Any]:
        previous = self.get_status(job_id)
        if not previous:
            raise KeyError(job_id)
        return self.create_job(
            tenant_id=previous.get("tenant_id") or "tenant-default",
            scope=previous.get("scope") or {},
            dry_run=False,
            run_async=run_async,
            batch_size=_clamp_batch_size(previous.get("batch_size")),
            operation=str(previous.get("operation") or "reindex"),
            action_id=previous.get("action_id"),
        )


knowledge_reindex_service = KnowledgeReindexService()
