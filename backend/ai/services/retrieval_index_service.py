"""Tenant-scoped PostgreSQL shadow-index lifecycle.

The service intentionally keeps the V1 document/chunk projection untouched.
It builds a bounded shadow generation, verifies its invariants, then changes a
single PostgreSQL ``active`` pointer in one transaction.  Rollback is another
pointer transaction; shadow rows and V1 facts are never destructively edited by
cutover operations.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database.core import _USE_PG, get_db_connection
from ai.services.retrieval_contract import retrieval_cache


_STATUSES = frozenset({"building", "shadow", "ready", "active", "superseded", "failed", "rolled_back"})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bounded(value: Any, *, default: str, limit: int = 200) -> str:
    text = str(value or default).strip()
    if not text:
        text = default
    if len(text) > limit:
        raise ValueError("retrieval index identifier is too long")
    return text


class RetrievalIndexError(RuntimeError):
    """Stable, non-sensitive shadow-index lifecycle error."""

    def __init__(self, code: str, message: str = "retrieval index operation rejected") -> None:
        super().__init__(message)
        self.code = code


class RetrievalIndexService:
    """Build, verify, activate and rollback a tenant's retrieval generation."""

    @staticmethod
    def _require_pg() -> None:
        if not _USE_PG:
            raise RetrievalIndexError("POSTGRES_REQUIRED", "PostgreSQL is required for retrieval shadow indexes")

    @staticmethod
    def _tenant(tenant_id: Any) -> str:
        return _bounded(tenant_id, default="tenant-default")

    @staticmethod
    def _row(cursor) -> Optional[dict[str, Any]]:
        row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return dict(row)
        columns = [str(item[0]) for item in (cursor.description or [])]
        return dict(zip(columns, row))

    @classmethod
    def _get_generation(cls, cursor, generation_id: str, tenant_id: str, *, for_update: bool = False) -> Optional[dict[str, Any]]:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            "SELECT id, tenant_id, generation_no, index_version, status, previous_generation_id, "
            "document_count, chunk_count, verification_json, build_config_json, failure_code, actor_id, "
            "created_at, updated_at, activated_at, rolled_back_at "
            "FROM ai_retrieval_index_generation WHERE id = ? AND tenant_id = ?" + suffix,
            (generation_id, tenant_id),
        )
        return cls._row(cursor)

    @staticmethod
    def _public(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not row:
            return None
        result = dict(row)
        for key in ("verification_json", "build_config_json"):
            value = result.get(key)
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError):
                    value = {}
            result[key] = value if isinstance(value, dict) else {}
        return result

    def create_shadow_generation(
        self,
        index_version: str,
        *,
        tenant_id: str = "tenant-default",
        actor_id: str | None = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        self._require_pg()
        tenant = self._tenant(tenant_id)
        version = _bounded(index_version, default="retrieval-v2")
        actor = _bounded(actor_id, default="system", limit=200)
        build_config = dict(config or {})
        # Config is metadata only.  Never allow identity or secret material to
        # be smuggled into the generation record.
        for key in list(build_config):
            if any(token in str(key).lower() for token in ("secret", "token", "password", "api_key", "tenant", "user", "acl")):
                build_config.pop(key, None)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Serialize generation numbers per tenant without taking a table
            # lock.  This is PostgreSQL-only and remains transaction-scoped.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (tenant,))
            existing = self._row(
                cursor.execute(
                    "SELECT id, tenant_id, generation_no, index_version, status, previous_generation_id, "
                    "document_count, chunk_count, verification_json, build_config_json, failure_code, actor_id, "
                    "created_at, updated_at, activated_at, rolled_back_at "
                    "FROM ai_retrieval_index_generation WHERE tenant_id = ? AND index_version = ?",
                    (tenant, version),
                )
            )
            if existing:
                conn.commit()
                return self._public(existing) or {}
            cursor.execute(
                "SELECT id FROM ai_retrieval_index_generation WHERE tenant_id = ? AND status = 'active' "
                "ORDER BY generation_no DESC LIMIT 1",
                (tenant,),
            )
            previous = cursor.fetchone()
            now = _now()
            generation = str(uuid.uuid4())
            cursor.execute(
                "SELECT COALESCE(MAX(generation_no), 0) + 1 FROM ai_retrieval_index_generation WHERE tenant_id = ?",
                (tenant,),
            )
            generation_no = int((cursor.fetchone() or [0])[0] or 1)
            cursor.execute(
                "INSERT INTO ai_retrieval_index_generation "
                "(id, tenant_id, generation_no, index_version, status, previous_generation_id, "
                "verification_json, build_config_json, actor_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'building', ?, '{}'::jsonb, CAST(? AS jsonb), ?, ?, ?)",
                (generation, tenant, generation_no, version, previous[0] if previous else None,
                 json.dumps(build_config, ensure_ascii=False, separators=(",", ":")), actor, now, now),
            )
            conn.commit()
            return self._public(self._get_generation(cursor, generation, tenant)) or {}

    def build_shadow_generation(self, generation_id: str, *, tenant_id: str = "tenant-default") -> dict[str, Any]:
        self._require_pg()
        tenant = self._tenant(tenant_id)
        generation = _bounded(generation_id, default="")
        if not generation:
            raise RetrievalIndexError("GENERATION_REQUIRED")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = self._get_generation(cursor, generation, tenant, for_update=True)
            if not row:
                raise RetrievalIndexError("GENERATION_NOT_FOUND")
            status = str(row.get("status") or "")
            if status in {"ready", "active"}:
                conn.commit()
                return self._public(row) or {}
            if status not in {"building", "shadow", "failed", "rolled_back"}:
                raise RetrievalIndexError("GENERATION_NOT_BUILDABLE")
            cursor.execute("DELETE FROM ai_retrieval_index_shadow_chunk WHERE generation_id = ? AND tenant_id = ?", (generation, tenant))
            cursor.execute(
                """
                INSERT INTO ai_retrieval_index_shadow_chunk (
                    generation_id, tenant_id, id, document_id, content, embedding, metadata_json, page, section,
                    parent_chunk_id, chunk_role, chunk_type, ordinal, raw_content, embedding_content,
                    heading_path_json, token_count, content_hash, source_locator_json, chunking_version,
                    is_retrieval_candidate, oversize_reason, document_id_metadata, document_category, vendor,
                    product_series, product_model, software_train, software_release, cli_platform, feature_domain,
                    feature, subfeature, risk_level, verification_level, rag_priority, chunk_index, embedding_model,
                    embedding_dimensions, embedding_version, chunker_version, structure_types_json,
                    neighbor_chunk_ids_json, parser_version, document_version, index_version, embedding_mode,
                    embedding_contract_version, search_text, retrieval_index_version, embedding_vector, created_at
                )
                SELECT ?, ?, c.id, c.document_id, c.content, c.embedding,
                       COALESCE(c.metadata_json, '{}'::jsonb), c.page, c.section, c.parent_chunk_id,
                       c.chunk_role, c.chunk_type, COALESCE(c.ordinal, 0), c.raw_content, c.embedding_content,
                       c.heading_path_json, c.token_count, c.content_hash, c.source_locator_json, c.chunking_version,
                       COALESCE(c.is_retrieval_candidate, 1), c.oversize_reason, c.document_id_metadata,
                       c.document_category, c.vendor, c.product_series, c.product_model, c.software_train,
                       c.software_release, c.cli_platform, c.feature_domain, c.feature, c.subfeature, c.risk_level,
                       c.verification_level, c.rag_priority, c.chunk_index, c.embedding_model,
                       c.embedding_dimensions, c.embedding_version, c.chunker_version, c.structure_types_json,
                       c.neighbor_chunk_ids_json, c.parser_version, c.document_version, c.index_version,
                       c.embedding_mode, c.embedding_contract_version, c.search_text, c.retrieval_index_version,
                       c.embedding_vector, c.created_at
                FROM ai_document_chunk c
                JOIN ai_document d ON d.id = c.document_id AND d.tenant_id = ?
                WHERE d.tenant_id = ? AND d.status = 'active'
                """,
                (generation, tenant, tenant, tenant),
            )
            cursor.execute("SELECT COUNT(DISTINCT document_id), COUNT(*) FROM ai_retrieval_index_shadow_chunk WHERE generation_id = ? AND tenant_id = ?", (generation, tenant))
            counts = cursor.fetchone() or (0, 0)
            now = _now()
            cursor.execute(
                "UPDATE ai_retrieval_index_generation SET status = 'shadow', document_count = ?, chunk_count = ?, "
                "failure_code = NULL, updated_at = ? WHERE id = ? AND tenant_id = ?",
                (int(counts[0] or 0), int(counts[1] or 0), now, generation, tenant),
            )
            conn.commit()
            return self._public(self._get_generation(cursor, generation, tenant)) or {}

    def verify_shadow_generation(self, generation_id: str, *, tenant_id: str = "tenant-default") -> dict[str, Any]:
        self._require_pg()
        tenant = self._tenant(tenant_id)
        generation = _bounded(generation_id, default="")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = self._get_generation(cursor, generation, tenant, for_update=True)
            if not row:
                raise RetrievalIndexError("GENERATION_NOT_FOUND")
            if str(row.get("status") or "") == "ready":
                conn.commit()
                return self._public(row) or {}
            if str(row.get("status") or "") not in {"shadow", "building"}:
                raise RetrievalIndexError("GENERATION_NOT_VERIFYABLE")
            cursor.execute(
                "SELECT COUNT(*), COUNT(DISTINCT document_id), "
                "COUNT(*) FILTER (WHERE tenant_id <> ?), "
                "COUNT(*) FILTER (WHERE COALESCE(is_retrieval_candidate, 1) NOT IN (0, 1)) "
                "FROM ai_retrieval_index_shadow_chunk WHERE generation_id = ? AND tenant_id = ?",
                (tenant, generation, tenant),
            )
            counts = cursor.fetchone() or (0, 0, 0, 0)
            errors = []
            if int(counts[2] or 0):
                errors.append("SHADOW_TENANT_MISMATCH")
            if int(counts[3] or 0):
                errors.append("INVALID_CANDIDATE_FLAG")
            now = _now()
            verification = {
                "contract_version": "shadow-index-v1",
                "document_count": int(counts[1] or 0),
                "chunk_count": int(counts[0] or 0),
                "tenant_mismatch_count": int(counts[2] or 0),
                "invalid_candidate_count": int(counts[3] or 0),
                "checked_at": now,
                "database": "PostgreSQL",
            }
            status = "failed" if errors else "ready"
            cursor.execute(
                "UPDATE ai_retrieval_index_generation SET status = ?, document_count = ?, chunk_count = ?, "
                "verification_json = CAST(? AS jsonb), failure_code = ?, updated_at = ? "
                "WHERE id = ? AND tenant_id = ?",
                (status, int(counts[1] or 0), int(counts[0] or 0), json.dumps(verification, separators=(",", ":")),
                 ",".join(errors) if errors else None, now, generation, tenant),
            )
            conn.commit()
            return self._public(self._get_generation(cursor, generation, tenant)) or {}

    def cutover_generation(self, generation_id: str, *, tenant_id: str = "tenant-default") -> dict[str, Any]:
        self._require_pg()
        tenant = self._tenant(tenant_id)
        generation = _bounded(generation_id, default="")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            target = self._get_generation(cursor, generation, tenant, for_update=True)
            if not target:
                raise RetrievalIndexError("GENERATION_NOT_FOUND")
            status = str(target.get("status") or "")
            if status == "active":
                conn.commit()
                retrieval_cache.invalidate_tenant(tenant)
                return self._public(target) or {}
            if status != "ready":
                raise RetrievalIndexError("GENERATION_NOT_READY")
            cursor.execute(
                "SELECT id FROM ai_retrieval_index_generation WHERE tenant_id = ? AND status = 'active' "
                "AND id <> ? ORDER BY generation_no DESC LIMIT 1 FOR UPDATE",
                (tenant, generation),
            )
            previous = cursor.fetchone()
            now = _now()
            if previous:
                cursor.execute(
                    "UPDATE ai_retrieval_index_generation SET status = 'superseded', updated_at = ? "
                    "WHERE id = ? AND tenant_id = ?",
                    (now, previous[0], tenant),
                )
            cursor.execute(
                "UPDATE ai_retrieval_index_generation SET status = 'active', activated_at = ?, updated_at = ? "
                "WHERE id = ? AND tenant_id = ? AND status = 'ready'",
                (now, now, generation, tenant),
            )
            if int(getattr(cursor, "rowcount", 0) or 0) != 1:
                raise RetrievalIndexError("CUTOVER_CONFLICT")
            conn.commit()
            retrieval_cache.invalidate_tenant(tenant)
            return self._public(self._get_generation(cursor, generation, tenant)) or {}

    def rollback_generation(self, generation_id: str | None = None, *, tenant_id: str = "tenant-default") -> dict[str, Any]:
        self._require_pg()
        tenant = self._tenant(tenant_id)
        requested = _bounded(generation_id, default="") if generation_id else ""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if requested:
                current = self._get_generation(cursor, requested, tenant, for_update=True)
            else:
                cursor.execute(
                    "SELECT id FROM ai_retrieval_index_generation WHERE tenant_id = ? AND status = 'active' "
                    "ORDER BY generation_no DESC LIMIT 1",
                    (tenant,),
                )
                active_id = cursor.fetchone()
                current = self._get_generation(cursor, active_id[0], tenant, for_update=True) if active_id else None
            if not current:
                raise RetrievalIndexError("ACTIVE_GENERATION_NOT_FOUND")
            if str(current.get("status") or "") == "rolled_back":
                conn.commit()
                return self._public(current) or {}
            if str(current.get("status") or "") != "active":
                raise RetrievalIndexError("GENERATION_NOT_ACTIVE")
            previous_id = str(current.get("previous_generation_id") or "")
            previous = self._get_generation(cursor, previous_id, tenant, for_update=True) if previous_id else None
            if not previous:
                raise RetrievalIndexError("ROLLBACK_TARGET_MISSING")
            if str(previous.get("status") or "") not in {"superseded", "ready", "active"}:
                raise RetrievalIndexError("ROLLBACK_TARGET_INVALID")
            now = _now()
            cursor.execute(
                "UPDATE ai_retrieval_index_generation SET status = 'rolled_back', rolled_back_at = ?, updated_at = ? "
                "WHERE id = ? AND tenant_id = ? AND status = 'active'",
                (now, now, current["id"], tenant),
            )
            cursor.execute(
                "UPDATE ai_retrieval_index_generation SET status = 'active', activated_at = COALESCE(activated_at, ?), updated_at = ? "
                "WHERE id = ? AND tenant_id = ?",
                (now, now, previous["id"], tenant),
            )
            conn.commit()
            retrieval_cache.invalidate_tenant(tenant)
            return self._public(self._get_generation(cursor, previous["id"], tenant)) or {}

    def get_active_generation(self, tenant_id: str = "tenant-default") -> Optional[dict[str, Any]]:
        self._require_pg()
        tenant = self._tenant(tenant_id)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tenant_id, generation_no, index_version, status, previous_generation_id, "
                "document_count, chunk_count, verification_json, build_config_json, failure_code, actor_id, "
                "created_at, updated_at, activated_at, rolled_back_at "
                "FROM ai_retrieval_index_generation WHERE tenant_id = ? AND status = 'active' "
                "ORDER BY generation_no DESC LIMIT 1",
                (tenant,),
            )
            return self._public(self._row(cursor))

    def list_generations(self, *, tenant_id: str = "tenant-default", limit: int = 50) -> list[dict[str, Any]]:
        self._require_pg()
        tenant = self._tenant(tenant_id)
        bounded_limit = max(1, min(int(limit or 50), 100))
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tenant_id, generation_no, index_version, status, previous_generation_id, "
                "document_count, chunk_count, verification_json, build_config_json, failure_code, actor_id, "
                "created_at, updated_at, activated_at, rolled_back_at "
                "FROM ai_retrieval_index_generation WHERE tenant_id = ? "
                "ORDER BY generation_no DESC LIMIT ?",
                (tenant, bounded_limit),
            )
            return [self._public(dict(row) if isinstance(row, dict) else dict(zip([str(item[0]) for item in cursor.description], row))) or {} for row in cursor.fetchall()]


retrieval_index_service = RetrievalIndexService()

