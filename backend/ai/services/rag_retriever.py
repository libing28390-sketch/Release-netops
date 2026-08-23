"""Metadata-first Retriever v2.

Eligibility is decided in SQL from structured document metadata.  Embeddings
and lexical signals only rank the already eligible candidate set; they can
never make an incompatible platform or document category eligible.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from database.core import _USE_PG, get_db_connection
from ai.providers.embedding import embedding_provider
from ai.security.sanitizer import sanitize_text
from ai.services.rag_policy import document_is_visible, trust_rank
from ai.services.knowledge_metadata import canonical_vendor
from ai.services.product_resolver import product_resolver
from ai.services.retrieval_contract import (
    BoundedReranker,
    build_minimal_context,
    build_retrieval_explanation,
    retrieval_cache,
    retrieval_cache_key,
    version_compatibility,
)
from ai.services.retrieval_index_service import retrieval_index_service
from ai.services.feature_flag_service import feature_flag_service
from core.config import settings


@dataclass
class RetrievalRequest:
    query: str
    top_k: int = 3
    vendor: Optional[str] = None
    product_family: Optional[str] = None
    product_series: Optional[str] = None
    product_model: Optional[str] = None
    os_family: Optional[str] = None
    os_generation: Optional[str] = None
    software_train: Optional[str] = None
    software_release: Optional[str] = None
    cli_platform: Optional[str] = None
    document_category: Optional[str] = None
    feature_domain: Optional[str] = None
    feature: Optional[str] = None
    subfeature: Optional[str] = None
    risk_level: Optional[str] = None
    verification_level: Optional[str] = None
    rag_priority: Optional[int] = None
    status: str = "active"
    applicability: Dict[str, Sequence[str] | str] = field(default_factory=dict)
    tenant_id: str = "tenant-default"
    user_id: str | None = None
    roles: Optional[List[str]] = None
    site_ids: Optional[List[str]] = None
    include_debug: bool = False
    normalized_query: Dict[str, Any] | None = None
    resolution: Dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, query: str, values: Dict[str, Any] | None = None, **kwargs: Any) -> "RetrievalRequest":
        values = dict(values or {})
        values.update(kwargs)
        if values.get("platform") and not values.get("cli_platform"):
            values["cli_platform"] = values.pop("platform")
        return cls(query=query, **{key: value for key, value in values.items() if key in cls.__dataclass_fields__})


class RAGRetriever:
    """SQL hard-filter → candidate Top-N → rank → document dedup → Top-K."""

    _ascii_token_re = re.compile(r"[a-z0-9_./:-]+", re.I)
    _han_run_re = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
    _command_re = re.compile(
        r"\b(?:display|show|system-view|interface|router|ospf|bgp|vlan|undo|no|ip|ipv6)"
        r"(?:\s+[a-z0-9_./:<>{}-]+){0,8}",
        re.I,
    )
    _lexical_stopwords = {
        "什么", "如何", "怎么", "请问", "一下", "这个", "那个", "是否", "可以",
        "华为", "交换机", "设备", "命令", "配置", "查看", "查询", "含义", "结果",
        "huawei", "command", "config", "configuration", "switch", "device",
    }

    def __init__(self, *, reranker: Any = None, cache_enabled: bool | None = None) -> None:
        self.last_debug: Dict[str, Any] = {}
        self.reranker = BoundedReranker(reranker)
        # Native caching is a release-safe feature flag.  Tests and legacy
        # deployments can keep it off while still using the exact key and
        # invalidation contract; PostgreSQL deployments may enable it with
        # AI_RETRIEVAL_CACHE_ENABLED=1.
        self.cache_enabled = (
            str(os.environ.get("AI_RETRIEVAL_CACHE_ENABLED", "0")).lower() in {"1", "true", "yes"}
            if cache_enabled is None
            else bool(cache_enabled)
        )

    @staticmethod
    def invalidate_cache_for_documents(document_ids: Sequence[Any]) -> int:
        return retrieval_cache.invalidate_documents(document_ids)

    @staticmethod
    def invalidate_cache_for_tenant(tenant_id: str) -> int:
        return retrieval_cache.invalidate_tenant(tenant_id)

    @staticmethod
    def _active_index_generation(tenant_id: str) -> Optional[Dict[str, Any]]:
        """Return the tenant's active shadow generation, fail-safe to V1.

        A missing migration or a temporarily unavailable control table must
        never make the legacy retrieval path unavailable.  Cutover itself is
        PostgreSQL-transactional; this read only selects a committed pointer.
        """
        try:
            generation = retrieval_index_service.get_active_generation(tenant_id)
            if not generation or str(generation.get("status") or "") != "active":
                return None
            if not generation.get("id") or not generation.get("index_version"):
                return None
            return generation
        except Exception:
            return None

    @classmethod
    def _search_tokens(cls, value: str) -> set[str]:
        text = str(value or "").lower()
        tokens = {token for token in cls._ascii_token_re.findall(text) if len(token) > 1}
        for run in cls._han_run_re.findall(text):
            tokens.update(run[index:index + 2] for index in range(max(0, len(run) - 1)))
            tokens.update(run[index:index + 3] for index in range(max(0, len(run) - 2)))
        return {token for token in tokens if token and token not in cls._lexical_stopwords}

    @classmethod
    def _command_phrases(cls, value: str) -> list[str]:
        phrases = []
        for match in cls._command_re.finditer(str(value or "")):
            parts = match.group(0).lower().split()
            if not parts or parts[0] not in {"display", "show"}:
                continue
            while parts and parts[-1] in {"command", "meaning", "output", "please", "query"}:
                parts.pop()
            if len(parts) >= 2:
                phrases.append(" ".join(parts))
        return phrases

    @classmethod
    def _calc_keyword_relevance(
        cls,
        query: str,
        content: str,
        doc_name: str,
        *,
        section: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> float:
        q_words = cls._search_tokens(query)
        if not q_words:
            return 0.0
        searchable_metadata = metadata or {}
        metadata_text = " ".join(
            str(searchable_metadata.get(key) or "")
            for key in ("title", "keywords", "tags", "commands", "feature", "subfeature", "scenario")
        )
        target_text = f"{doc_name} {section} {metadata_text} {content}".lower()
        target_words = cls._search_tokens(target_text)
        coverage = len(q_words & target_words) / max(1, len(q_words))

        command_phrases = cls._command_phrases(query)
        normalized_target = " ".join(target_text.split())
        if command_phrases:
            if any(phrase in normalized_target for phrase in command_phrases):
                return min(1.0, 0.65 * coverage + 0.55)
            return 0.10 * coverage
        return min(1.0, 0.65 * coverage)

    @staticmethod
    def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or not right:
            return 0.0
        size = min(len(left), len(right))
        dot = sum(float(left[index]) * float(right[index]) for index in range(size))
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left[:size]))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right[:size]))
        if not left_norm or not right_norm:
            return 0.0
        # Negative similarity is not relevance.  Mapping [-1, 1] to [0, 1]
        # gave unrelated orthogonal vectors a misleading score of 0.5.
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))

    @staticmethod
    def _parse_json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _table_columns(cursor, table: str) -> set[str]:
        cursor.execute(f"SELECT * FROM {table} WHERE 1 = 0")
        return {str(description[0]) for description in (cursor.description or [])}

    def _filter_sql(self, request: RetrievalRequest, columns: set[str]) -> tuple[str, list[Any]]:
        where = ["d.status = ?", "(d.tenant_id = ? OR d.tenant_id = 'tenant-default')"]
        params: list[Any] = [request.status, request.tenant_id]
        if "exclude_from_rag" in columns:
            where.append("COALESCE(d.exclude_from_rag, 0) = 0")

        scalar_filters = (
            ("product_family", request.product_family),
            ("os_family", request.os_family),
            ("os_generation", request.os_generation),
            ("software_train", request.software_train),
            ("feature_domain", request.feature_domain),
            ("feature", request.feature),
            ("subfeature", request.subfeature),
            ("risk_level", request.risk_level),
            ("verification_level", request.verification_level),
        )
        if request.vendor and str(request.vendor).lower() != "all" and "vendor" in columns:
            where.append("LOWER(d.vendor) = LOWER(?)")
            params.append(canonical_vendor(request.vendor))
        if request.document_category and "document_category" in columns:
            where.append("LOWER(d.document_category) = LOWER(?)")
            params.append(request.document_category)
        for column, value in scalar_filters:
            if value is not None and column in columns:
                where.append(f"LOWER(COALESCE(d.{column}, '')) = LOWER(?)")
                params.append(str(value))

        if request.software_release and "software_release" in columns:
            release = str(request.software_release)
            if "metadata_json" in columns and _USE_PG:
                where.append(
                    "(LOWER(COALESCE(d.software_release, '')) = LOWER(?) OR "
                    "COALESCE(d.metadata_json -> 'applicable_versions', '[]'::jsonb) @> jsonb_build_array(?) OR "
                    "COALESCE(d.metadata_json -> 'verified_versions', '[]'::jsonb) @> jsonb_build_array(?))"
                )
                params.extend([release, release, release])
            elif "metadata_json" in columns:
                where.append("(LOWER(COALESCE(d.software_release, '')) = LOWER(?) OR LOWER(CAST(d.metadata_json AS TEXT)) LIKE LOWER(?))")
                params.extend([release, f"%{release}%"])
            else:
                where.append("LOWER(COALESCE(d.software_release, '')) = LOWER(?)")
                params.append(release)

        # Product aliases are commonly represented as applicability arrays in
        # the source metadata while the high-frequency scalar may be null.
        for column, value, array_keys in (
            ("product_series", request.product_series, ("applicable_product_series", "product_series")),
            ("product_model", request.product_model, ("applicable_product_models", "applicable_models", "product_models", "models")),
        ):
            if value is None:
                continue
            value_text = str(value)
            is_series_prefix = bool(
                column == "product_series"
                and re.fullmatch(r"S\d{2,4}", value_text.strip(), re.IGNORECASE)
            )
            scalar = (
                f"LOWER(COALESCE(d.{column}, '')) LIKE LOWER(?)"
                if is_series_prefix and column in columns
                else f"LOWER(COALESCE(d.{column}, '')) = LOWER(?)"
                if column in columns
                else "0 = 1"
            )
            scalar_value = f"{value_text}%" if is_series_prefix else value_text
            if "metadata_json" in columns:
                if _USE_PG:
                    if is_series_prefix:
                        # Registry metadata is mixed-version: some imports
                        # store product_series as a scalar and others as an
                        # applicability array.  Text containment is portable
                        # here and remains guarded by the vendor/category
                        # predicates above.
                        where.append(f"({scalar} OR LOWER(CAST(d.metadata_json AS TEXT)) LIKE LOWER(?))")
                        params.extend([scalar_value, f"%{value_text}%"] if column in columns else [f"%{value_text}%"])
                    else:
                        array_expr = " OR ".join(
                            f"COALESCE(d.metadata_json -> '{key}', '[]'::jsonb) @> jsonb_build_array(?)"
                            for key in array_keys
                        )
                        # A short, reviewed hardware alias such as CE6885 or
                        # C9300 may be stored as the full SKU
                        # (CE6885-48YS8CQ / C9300-24T) in the registry.  Keep
                        # the exact equality and applicability-array checks,
                        # but add a dash-boundary prefix only for a concrete
                        # model prefix; a generic series remains governed by
                        # product_series above.
                        model_prefix = bool(
                            column == "product_model"
                            and re.fullmatch(r"[a-z]{1,3}\d{3,5}", value_text.strip(), re.IGNORECASE)
                            and "-" not in value_text
                        )
                        prefix_clause = (
                            f" OR LOWER(COALESCE(d.{column}, '')) LIKE LOWER(?)"
                            if model_prefix and column in columns
                            else ""
                        )
                        where.append(f"({scalar}{prefix_clause} OR ({array_expr}))")
                        params.append(scalar_value)
                        if model_prefix and column in columns:
                            params.append(f"{value_text}-%")
                        params.extend([scalar_value] * len(array_keys))
                else:
                    model_prefix = bool(
                        column == "product_model"
                        and re.fullmatch(r"[a-z]{1,3}\d{3,5}", value_text.strip(), re.IGNORECASE)
                        and "-" not in value_text
                    )
                    prefix_clause = (
                        f" OR LOWER(COALESCE(d.{column}, '')) LIKE LOWER(?)"
                        if model_prefix and column in columns
                        else ""
                    )
                    where.append(f"({scalar}{prefix_clause} OR LOWER(CAST(d.metadata_json AS TEXT)) LIKE LOWER(?))")
                    params.extend([scalar_value] if column in columns else [])
                    if model_prefix and column in columns:
                        params.append(f"{value_text}-%")
                    params.append(f"%{value_text}%")
            else:
                where.append(scalar)
                if column in columns:
                    params.append(scalar_value)

        if request.cli_platform and "cli_platform" in columns:
            # Never allow platform=all to satisfy a concrete command,
            # configuration, or CLI-output request.  Neutral documents are
            # represented by NULL, not the string all.
            platform_value = str(request.cli_platform)
            if "metadata_json" in columns and _USE_PG:
                # Product registries use a specific train (for example
                # huawei_vrp_v200), while a reviewed command skeleton may be
                # intentionally published for the broader huawei_vrp family.
                # The applicability array keeps that compatibility explicit
                # instead of weakening the platform hard gate globally.
                where.append(
                    "(LOWER(d.cli_platform) = LOWER(?) OR "
                    "COALESCE(d.metadata_json -> 'applicable_cli_platforms', '[]'::jsonb) "
                    "@> jsonb_build_array(?))"
                )
                params.extend([platform_value, platform_value])
            elif "metadata_json" in columns:
                where.append(
                    "(LOWER(d.cli_platform) = LOWER(?) OR "
                    "LOWER(CAST(d.metadata_json AS TEXT)) LIKE LOWER(?))"
                )
                params.extend([platform_value, f'%' + platform_value + '%'])
            else:
                where.append("LOWER(d.cli_platform) = LOWER(?)")
                params.append(platform_value)
        if request.rag_priority is not None and "rag_priority" in columns:
            where.append("COALESCE(d.rag_priority, 0) >= ?")
            params.append(int(request.rag_priority))

        # Additional applicability arrays are handled as hard predicates.  A
        # portable text containment fallback is retained for old SQLite JSON1
        # builds; it still runs in SQL before any chunks enter Python.
        for key, requested in (request.applicability or {}).items():
            values = requested if isinstance(requested, (list, tuple, set)) else [requested]
            for value in values:
                if value is None or "metadata_json" not in columns:
                    continue
                if _USE_PG:
                    where.append(f"COALESCE(d.metadata_json -> '{key}', '[]'::jsonb) @> jsonb_build_array(?)")
                    params.append(str(value))
                else:
                    where.append("LOWER(CAST(d.metadata_json AS TEXT)) LIKE LOWER(?)")
                    params.append(f"%{value}%")
        return " AND ".join(where), params

    def _query_rows(
        self,
        request: RetrievalRequest,
        vector_top_n: int,
        active_generation: Optional[Dict[str, Any]] = None,
    ) -> tuple[list[Any], int, Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            columns = self._table_columns(cursor, "ai_document")
            source_table = "ai_retrieval_index_shadow_chunk" if active_generation else "ai_document_chunk"
            chunk_columns = self._table_columns(cursor, source_table)
            where_sql, params = self._filter_sql(request, columns)
            cursor.execute(
                f"SELECT COUNT(*) FROM ai_document d WHERE {where_sql}",
                params,
            )
            document_count = int((cursor.fetchone() or [0])[0] or 0)
            document_category_expr = "d.document_category" if "document_category" in columns else "NULL"
            cli_platform_expr = "d.cli_platform" if "cli_platform" in columns else "NULL"
            semantic_document_id_expr = "d.document_id" if "document_id" in columns else "NULL"
            source_expr = "d.source" if "source" in columns else "NULL"
            document_version_expr = "d.version" if "version" in columns else "NULL"
            software_train_expr = "d.software_train" if "software_train" in columns else "NULL"
            software_release_expr = "d.software_release" if "software_release" in columns else "NULL"
            candidate_expr = "COALESCE(c.is_retrieval_candidate, 1)" if "is_retrieval_candidate" in chunk_columns else "1"
            chunk_role_expr = "c.chunk_role" if "chunk_role" in chunk_columns else "'legacy'"
            parent_expr = "c.parent_chunk_id" if "parent_chunk_id" in chunk_columns else "NULL"
            ordinal_expr = "COALESCE(c.ordinal, 0)" if "ordinal" in chunk_columns else "NULL"
            ordinal_order_expr = "COALESCE(c.ordinal, 0)" if "ordinal" in chunk_columns else "c.id"
            embedding_model_expr = "c.embedding_model" if "embedding_model" in chunk_columns else "NULL"
            embedding_dimensions_expr = "c.embedding_dimensions" if "embedding_dimensions" in chunk_columns else "NULL"
            candidate_where = f"AND {candidate_expr} = 1"
            source_where = ""
            source_params: list[Any] = []
            if active_generation:
                generation_id = str(active_generation.get("id") or "")
                generation_tenant = str(active_generation.get("tenant_id") or request.tenant_id)
                if generation_tenant != str(request.tenant_id):
                    # Never use a generation belonging to a different tenant,
                    # even if a caller supplied a forged request object.
                    return [], document_count, {
                        "metadata_filter": where_sql,
                        "metadata_candidate_documents": document_count,
                        "candidate_count": 0,
                        "vector_top_n": 0,
                        "index_source": "v1",
                        "capability_degraded": ["INDEX_TENANT_MISMATCH"],
                    }
                source_where = "c.generation_id = ? AND c.tenant_id = ? AND d.tenant_id = ? AND "
                source_params = [generation_id, generation_tenant, generation_tenant]
            cursor.execute(
                f"""SELECT c.id, c.content, c.embedding, c.metadata_json, c.section,
                           d.id, d.name, {source_expr}, {document_version_expr}, d.vendor, d.platform, d.tenant_id,
                           d.acl_json, d.source_trust_level,
                           {document_category_expr}, {cli_platform_expr}, {semantic_document_id_expr},
                           {software_train_expr}, {software_release_expr},
                           {candidate_expr}, {chunk_role_expr},
                           {parent_expr}, {ordinal_expr}, {embedding_model_expr}, {embedding_dimensions_expr}
                    FROM {source_table} c
                    JOIN ai_document d ON c.document_id = d.id
                    WHERE {source_where}{where_sql}
                      {candidate_where}
                    ORDER BY d.id ASC, {ordinal_order_expr} ASC, c.id ASC""",
                source_params + params,
            )
            rows = cursor.fetchall()
            debug = {
                "metadata_filter": where_sql,
                "metadata_candidate_documents": document_count,
                "candidate_count": len(rows),
                # Every metadata-eligible chunk is scored.  This field is
                # retained for the existing trace contract.
                "vector_top_n": len(rows),
                "index_source": "shadow" if active_generation else "v1",
            }
            if active_generation:
                debug["index_generation_id"] = active_generation.get("id")
                debug["index_version"] = active_generation.get("index_version")
            return rows, document_count, debug

    def _native_accelerator_scores(
        self,
        request: RetrievalRequest,
        chunk_ids: Sequence[Any],
        active_generation: Optional[Dict[str, Any]] = None,
    ) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
        """Run bounded PostgreSQL FTS/trigram/vector shadow scores.

        The tenant/status/ACL eligibility query has already produced the IDs;
        every accelerator query is therefore bounded to that candidate set.
        SQLite deliberately returns an explicit compatibility/degraded marker.
        """
        debug: dict[str, Any] = {
            "fts_stage": "not_applicable" if not _USE_PG else "disabled",
            "trgm_stage": "not_applicable" if not _USE_PG else "disabled",
            "vector_stage": "not_applicable" if not _USE_PG else "disabled",
            "fts_candidates": 0,
            "trgm_candidates": 0,
            "vector_candidates": 0,
            "capability_degraded": [],
            "index_source": "shadow" if active_generation else "v1",
        }
        if active_generation:
            debug["index_generation_id"] = active_generation.get("id")
            debug["index_version"] = active_generation.get("index_version")
        if not _USE_PG or not chunk_ids:
            if not _USE_PG:
                debug["capability_degraded"] = ["POSTGRES_ACCELERATORS_NOT_APPLICABLE"]
            return {}, debug
        scores: dict[str, dict[str, float]] = {}
        placeholders = ", ".join("?" for _ in chunk_ids)
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                source_table = "ai_retrieval_index_shadow_chunk" if active_generation else "ai_document_chunk"
                columns = self._table_columns(cursor, source_table)
                scope_sql = ""
                scope_params: list[Any] = []
                if active_generation:
                    scope_sql = "generation_id = ? AND tenant_id = ? AND "
                    scope_params = [str(active_generation.get("id") or ""), str(active_generation.get("tenant_id") or request.tenant_id)]
                if "search_text" in columns:
                    query_text = str(request.query or "")[:20000]
                    try:
                        rows = cursor.execute(
                            "SELECT id, LEAST(1.0, ts_rank_cd(to_tsvector('simple', COALESCE(search_text, '')), "
                            "websearch_to_tsquery('simple', ?))) "
                            f"FROM {source_table} WHERE {scope_sql}id IN ({placeholders}) "
                            "AND to_tsvector('simple', COALESCE(search_text, '')) @@ websearch_to_tsquery('simple', ?)",
                            [query_text, *scope_params, *chunk_ids, query_text],
                        ).fetchall()
                        for row in rows:
                            scores.setdefault(str(row[0]), {})["fts"] = max(0.0, min(1.0, float(row[1] or 0.0)))
                        debug["fts_stage"] = "native_postgresql"
                        debug["fts_candidates"] = len(rows)
                    except Exception:
                        debug["fts_stage"] = "degraded_missing_or_invalid_contract"
                        debug["capability_degraded"].append("FTS_QUERY_FAILED")
                    threshold = max(0.0, min(1.0, float(os.environ.get("AI_RETRIEVAL_TRGM_THRESHOLD", "0.35"))))
                    try:
                        rows = cursor.execute(
                            "SELECT id, similarity(COALESCE(search_text, ''), ?) "
                            f"FROM {source_table} WHERE {scope_sql}id IN ({placeholders}) "
                            "AND similarity(COALESCE(search_text, ''), ?) >= ?",
                            [query_text, *scope_params, *chunk_ids, query_text, threshold],
                        ).fetchall()
                        for row in rows:
                            scores.setdefault(str(row[0]), {})["trgm"] = max(0.0, min(1.0, float(row[1] or 0.0)))
                        debug["trgm_stage"] = "native_postgresql"
                        debug["trgm_threshold"] = threshold
                        debug["trgm_candidates"] = len(rows)
                    except Exception:
                        debug["trgm_stage"] = "degraded_missing_or_invalid_contract"
                        debug["capability_degraded"].append("TRGM_QUERY_FAILED")
                else:
                    debug["capability_degraded"].append("SEARCH_TEXT_COLUMN_MISSING")

                if "embedding_vector" in columns:
                    try:
                        query_vector = embedding_provider.embed_query(request.query)
                        vector_literal = "[" + ",".join(str(float(value)) for value in query_vector) + "]"
                        rows = cursor.execute(
                            "SELECT id, GREATEST(0.0, LEAST(1.0, 1 - (embedding_vector <=> CAST(? AS vector)))) "
                            f"FROM {source_table} WHERE {scope_sql}id IN ({placeholders}) AND embedding_vector IS NOT NULL",
                            [vector_literal, *scope_params, *chunk_ids],
                        ).fetchall()
                        for row in rows:
                            scores.setdefault(str(row[0]), {})["vector"] = max(0.0, min(1.0, float(row[1] or 0.0)))
                        debug["vector_stage"] = "native_pgvector"
                        debug["vector_candidates"] = len(rows)
                    except Exception:
                        debug["vector_stage"] = "degraded_missing_or_incompatible_contract"
                        debug["capability_degraded"].append("VECTOR_QUERY_FAILED")
                else:
                    debug["capability_degraded"].append("EMBEDDING_VECTOR_COLUMN_MISSING")
        except Exception:
            debug["capability_degraded"].append("POSTGRES_ACCELERATOR_CONNECTION_FAILED")
        return scores, debug

    @staticmethod
    def _expand_document_context(primary: Dict[str, Any], chunks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Attach primary/parent/neighbor chunks under a hard context budget."""

        category = str(primary.get("document_category") or "")
        max_chars = 12_000 if category == "configuration" else 10_000 if category == "cli_output" else 8_000
        context = build_minimal_context(primary, chunks, max_chars=max_chars)
        expanded = dict(primary)
        expanded["content"] = context["content"]
        selected_ids = set(context["context_chunk_ids"])
        expanded["context_sections"] = [
            str(item.get("section") or "General Overview")
            for item in chunks
            if str(item.get("chunk_id") or "") in selected_ids
        ]
        expanded.update(context)
        return expanded

    def _search_once(
        self,
        request: RetrievalRequest,
        min_relevance: float = 0.20,
        *,
        active_generation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute one bounded retrieval against V1 or a supplied V2 generation.

        The caller owns the choice of source.  Keeping this seam explicit is
        what lets MIG-009 execute a V2 read for comparison without allowing
        the shadow result to replace the V1 user answer.
        """
        top_k = max(1, int(request.top_k or 3))
        candidate_hint = max(top_k * 30, 100)
        cache_key = retrieval_cache_key(
            request,
            index_version=str((active_generation or {}).get("index_version") or "retrieval-v1"),
        )
        if self.cache_enabled:
            cached = retrieval_cache.get(cache_key)
            if cached is not None:
                cached.setdefault("debug", {})["cache"] = {"hit": True, "key": cache_key}
                self.last_debug = cached.get("debug") or {}
                return cached
        try:
            rows, _document_count, debug = self._query_rows(request, candidate_hint, active_generation)
            accelerator_scores, accelerator_debug = self._native_accelerator_scores(
                request,
                [row[0] for row in rows],
                active_generation,
            )
            debug.update(accelerator_debug)
            try:
                query_vector = embedding_provider.embed_text(request.query)
            except Exception:
                query_vector = []

            scored: list[dict[str, Any]] = []
            chunks_by_document: Dict[str, list[dict[str, Any]]] = {}
            incompatible_vectors = 0
            version_conflicts = 0
            wrong_vendor_rows = 0
            current_model = str(getattr(embedding_provider, "model_id", "") or "")
            for row in rows:
                (
                    c_id, content, embedding_json, meta_json, section,
                    doc_id, doc_name, document_source, document_version, d_vendor, d_platform, d_tenant,
                    acl_json, trust_level, document_category, cli_platform,
                    semantic_document_id, document_software_train, document_software_release,
                    _is_candidate, chunk_role,
                    parent_chunk_id, ordinal, stored_embedding_model, stored_embedding_dimensions,
                ) = row
                document = {"id": doc_id, "tenant_id": d_tenant, "acl_json": acl_json}
                if not document_is_visible(document, tenant_id=request.tenant_id, user_id=request.user_id, roles=request.roles, site_ids=request.site_ids):
                    continue
                metadata = self._parse_json(meta_json)
                requested_vendor = str(getattr(request, "vendor", "") or "").strip().lower()
                actual_vendor = str(metadata.get("vendor") or d_vendor or "").strip().lower()
                if requested_vendor and actual_vendor and requested_vendor != actual_vendor:
                    wrong_vendor_rows += 1
                keyword_score = self._calc_keyword_relevance(
                    request.query,
                    str(content or ""),
                    str(doc_name or ""),
                    section=str(section or ""),
                    metadata=metadata,
                )
                native_scores = accelerator_scores.get(str(c_id), {})
                keyword_score = max(
                    keyword_score,
                    float(native_scores.get("fts", 0.0)),
                    float(native_scores.get("trgm", 0.0)),
                )
                try:
                    chunk_vector = embedding_json if isinstance(embedding_json, list) else json.loads(str(embedding_json or "[]"))
                    if not isinstance(chunk_vector, list):
                        chunk_vector = []
                except (TypeError, ValueError):
                    chunk_vector = []
                stored_dimensions = int(stored_embedding_dimensions or 0)
                vector_incompatible = bool(
                    stored_dimensions
                    and (len(chunk_vector) != stored_dimensions or len(query_vector) != stored_dimensions)
                )
                if stored_embedding_model and current_model and str(stored_embedding_model) != current_model:
                    vector_score = 0.0
                    incompatible_vectors += 1
                elif vector_incompatible:
                    vector_score = 0.0
                    incompatible_vectors += 1
                else:
                    vector_score = float(native_scores.get("vector", self._cosine(query_vector, chunk_vector)))
                specificity_fields = ("vendor", "document_category", "product_series", "product_model", "cli_platform", "feature_domain", "feature")
                requested_count = sum(1 for field_name in specificity_fields if getattr(request, field_name, None))
                matched_count = 0
                for field_name in specificity_fields:
                    requested_value = getattr(request, field_name, None)
                    actual_value = metadata.get(field_name)
                    if not requested_value:
                        continue
                    requested_text = str(requested_value).strip().lower()
                    actual_text = str(actual_value or "").strip().lower()
                    if field_name == "product_series" and re.fullmatch(r"s\d{2,4}", requested_text):
                        if actual_text.startswith(requested_text):
                            matched_count += 1
                    elif actual_text == requested_text:
                        matched_count += 1
                metadata_score = matched_count / max(1, requested_count)
                applicable_versions = metadata.get("applicable_versions") or metadata.get("verified_versions") or []
                version_score, version_evidence = version_compatibility(
                    request.software_train,
                    request.software_release,
                    document_software_train or metadata.get("software_train"),
                    document_software_release or metadata.get("software_release"),
                    applicable_versions if isinstance(applicable_versions, (list, tuple, set)) else [],
                )
                trust_score = max(0.0, min(1.0, trust_rank(trust_level) / 4.0))
                from ai.services.retrieval_contract import ScoreComponents
                components = ScoreComponents(
                    lexical=keyword_score,
                    vector=vector_score,
                    metadata=metadata_score,
                    trust=trust_score,
                    version=version_score,
                )
                score = components.total
                exact_command_required = bool(self._command_phrases(request.query)) and str(document_category or "") in {"command", "cli_output"}
                # Product/series questions often use a local alias such as
                # ``CE6800`` while the verified document stores the canonical
                # series ``CloudEngine 6800``.  Once SQL has already matched
                # that exact hardware identity, do not discard the document
                # merely because the alias has no lexical overlap.
                exact_hardware_identity = bool(
                    str(document_category or "").lower() == "hardware"
                    and (request.product_series or request.product_model)
                    and metadata_score >= 0.90
                )
                if version_score == 0.0 and (request.software_train or request.software_release):
                    # Version conflicts are hard retrieval boundaries.  A
                    # lexical/vector hit must not smuggle a known incompatible
                    # release into an operator answer.
                    version_conflicts += 1
                    continue
                item = {
                    "chunk_id": c_id,
                    "content": sanitize_text(str(content or "")),
                    "document_name": doc_name,
                    "source": document_source,
                    "document_version": document_version,
                    "document_status": request.status,
                    "document_id": semantic_document_id or doc_id,
                    "storage_document_id": doc_id,
                    "section": section,
                    "vendor": d_vendor,
                    "platform": cli_platform or d_platform,
                    "cli_platform": cli_platform,
                    "document_category": document_category,
                    "source_trust_level": trust_level or "untrusted",
                    "source_trust_rank": trust_rank(trust_level),
                    "untrusted_data": True,
                    "metadata": metadata,
                    "chunk_role": chunk_role or "standalone",
                    "parent_chunk_id": parent_chunk_id,
                    "ordinal": int(ordinal or 0),
                    "keyword_score": round(keyword_score, 4),
                    "vector_score": round(vector_score, 4),
                    "metadata_score": round(metadata_score, 4),
                    "trust_score": round(trust_score, 4),
                    "version_score": round(version_score, 4),
                    "version_evidence": version_evidence,
                    "score_components": components.to_dict(),
                    "relevance_score": round(score, 4),
                }
                key = str(doc_id)
                chunks_by_document.setdefault(key, []).append(item)
                if (score >= min_relevance or exact_hardware_identity) and not (exact_command_required and keyword_score < 0.55):
                    scored.append(item)

            best_by_document: Dict[str, dict[str, Any]] = {}
            for item in scored:
                key = str(item["storage_document_id"])
                previous = best_by_document.get(key)
                if previous is None or (item["relevance_score"], item["source_trust_rank"]) > (previous["relevance_score"], previous["source_trust_rank"]):
                    best_by_document[key] = item
            ranked_documents = sorted(
                best_by_document.values(),
                key=lambda item: (item["relevance_score"], item["source_trust_rank"]),
                reverse=True,
            )[:top_k]
            reranked_documents, reranker_debug = self.reranker.apply(request.query, ranked_documents)
            final_results = [
                self._expand_document_context(item, chunks_by_document.get(str(item["storage_document_id"]), [item]))
                for item in reranked_documents[:top_k]
            ]
            candidate_snapshot = []
            if self._setting_flag("KNOWLEDGE_V2_SHADOW_READ"):
                ordered_candidates = sorted(
                    scored,
                    key=lambda item: (
                        item.get("relevance_score", 0.0),
                        item.get("source_trust_rank", 0),
                        str(item.get("storage_document_id") or ""),
                        str(item.get("chunk_id") or ""),
                    ),
                    reverse=True,
                )[:100]
                candidate_snapshot = [
                    projected
                    for index, item in enumerate(ordered_candidates, 1)
                    if (projected := self._shadow_candidate(item, index)) is not None
                ]
            debug.update({
                "dedup_document_count": len(best_by_document),
                "incompatible_embedding_chunks": incompatible_vectors,
                "version_conflict_count": version_conflicts,
                "wrong_vendor_count": wrong_vendor_rows,
                "expanded_context_chunks": sum(int(item.get("context_chunk_count") or 0) for item in final_results),
                "final_document_ids": [item["document_id"] for item in final_results],
                "reranker": reranker_debug,
                "cache": {"hit": False, "key": cache_key, "enabled": self.cache_enabled},
                "outcome": "matched" if final_results else "no_match",
            })
            if candidate_snapshot:
                debug["candidate_snapshot"] = candidate_snapshot
            explanation = build_retrieval_explanation(request, debug, final_results)
            self.last_debug = debug
            payload = {"results": final_results, "debug": debug, "explanation": explanation}
            if self.cache_enabled:
                retrieval_cache.set(
                    cache_key,
                    payload,
                    document_ids=[item.get("storage_document_id") for item in final_results],
                    tenant_id=request.tenant_id,
                )
            return payload
        except Exception:
            # Never expose dependency/SQL/provider exception text through the
            # retrieval debug contract.  The stable code is sufficient for an
            # operator to correlate the request with server-side logs.
            self.last_debug = {
                "error_code": "RETRIEVAL_EXECUTION_FAILED",
                "candidate_count": 0,
                "vector_top_n": candidate_hint,
            }
            return {"results": [], "debug": self.last_debug, "explanation": build_retrieval_explanation(request, self.last_debug, [])}

    @staticmethod
    def _setting_flag(name: str, default: bool = False) -> bool:
        value = getattr(settings, name, None)
        if value is None:
            value = os.environ.get(name, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _shadow_identity(item: Any) -> str:
        if not isinstance(item, dict):
            return ""
        return f"{item.get('storage_document_id') or item.get('document_id') or ''}:{item.get('chunk_id') or ''}"

    @classmethod
    def _shadow_hashes(cls, results: Any) -> list[str]:
        if not isinstance(results, list):
            return []
        return [
            hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
            for identity in (cls._shadow_identity(item) for item in results[:20])
            if identity
        ]

    @staticmethod
    def _shadow_score(item: Any, key: str) -> float | None:
        if not isinstance(item, dict):
            return None
        value = item.get(key)
        try:
            return round(max(0.0, min(1.0, float(value))), 4)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _shadow_candidate(cls, item: Any, rank: int) -> dict[str, Any] | None:
        """Project one candidate without exposing document/chunk identifiers."""

        if not isinstance(item, dict):
            return None
        identity = cls._shadow_identity(item)
        supplied_hash = str(item.get("candidate_hash") or "").strip()
        if identity:
            candidate_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        elif supplied_hash:
            candidate_hash = hashlib.sha256(supplied_hash.encode("utf-8")).hexdigest()[:32]
        else:
            return None
        components = item.get("score_components") if isinstance(item.get("score_components"), dict) else {}
        return {
            "rank": max(1, int(rank or 1)),
            "candidate_hash": candidate_hash,
            "relevance_score": cls._shadow_score(item, "relevance_score"),
            "keyword_score": cls._shadow_score(item, "keyword_score"),
            "vector_score": cls._shadow_score(item, "vector_score"),
            "metadata_score": cls._shadow_score(item, "metadata_score"),
            "trust_score": cls._shadow_score(item, "trust_score"),
            "version_score": cls._shadow_score(item, "version_score"),
            "score_components": {
                key: cls._shadow_score(components, key)
                for key in ("lexical", "vector", "metadata", "trust", "version", "total")
                if components.get(key) is not None
            },
        }

    @classmethod
    def _shadow_final_chunk(cls, item: Any, rank: int) -> dict[str, Any] | None:
        """Project one final result to a hash-only chunk observation."""

        if not isinstance(item, dict):
            return None
        identity = cls._shadow_identity(item)
        supplied_hash = str(item.get("chunk_hash") or "").strip()
        if identity:
            chunk_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        elif supplied_hash:
            chunk_hash = hashlib.sha256(supplied_hash.encode("utf-8")).hexdigest()[:32]
        else:
            return None
        context_ids = item.get("context_chunk_ids") if isinstance(item.get("context_chunk_ids"), list) else []
        return {
            "rank": max(1, int(rank or 1)),
            "chunk_hash": chunk_hash,
            "relevance_score": cls._shadow_score(item, "relevance_score"),
            "context_chunk_count": max(0, int(item.get("context_chunk_count") or len(context_ids))),
            "context_chunk_hashes": [
                hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]
                for value in context_ids[:20]
                if value not in (None, "")
            ],
        }

    @classmethod
    def _shadow_rows(cls, payload: Any, key: str, fallback: Any) -> list[dict[str, Any]]:
        debug = payload.get("debug") if isinstance(payload, dict) else {}
        rows = debug.get(key) if isinstance(debug, dict) else None
        if not isinstance(rows, list) or not rows:
            rows = fallback if isinstance(fallback, list) else []
        return [row for row in rows[:100] if isinstance(row, dict)]

    @staticmethod
    def _shadow_only_hashes(rows: list[dict[str, Any]], other: list[dict[str, Any]], key: str) -> list[str]:
        other_hashes = {str(row.get(key) or "") for row in other}
        return [str(row.get(key)) for row in rows if row.get(key) and str(row.get(key)) not in other_hashes][:20]

    @classmethod
    def _shadow_score_deltas(cls, v1_rows: list[dict[str, Any]], v2_rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        v1_by_hash = {str(row.get(key)): row for row in v1_rows if row.get(key)}
        v2_by_hash = {str(row.get(key)): row for row in v2_rows if row.get(key)}
        deltas: list[dict[str, Any]] = []
        for opaque_hash in [str(row.get(key)) for row in v1_rows if row.get(key) in v2_by_hash][:20]:
            left = v1_by_hash.get(opaque_hash) or {}
            right = v2_by_hash.get(opaque_hash) or {}
            v1_score = cls._shadow_score(left, "relevance_score")
            v2_score = cls._shadow_score(right, "relevance_score")
            if v1_score is None and v2_score is None:
                continue
            delta = round((v2_score or 0.0) - (v1_score or 0.0), 4)
            if delta:
                deltas.append({
                    "chunk_hash": opaque_hash,
                    "v1_score": v1_score,
                    "v2_score": v2_score,
                    "delta": delta,
                })
        return deltas[:20]

    @classmethod
    def _shadow_compare(
        cls,
        v1: Dict[str, Any],
        v2: Dict[str, Any],
        *,
        v1_latency_ms: int,
        v2_latency_ms: int,
        generation: Dict[str, Any],
    ) -> Dict[str, Any]:
        v1_results = v1.get("results") if isinstance(v1.get("results"), list) else []
        v2_results = v2.get("results") if isinstance(v2.get("results"), list) else []
        v1_ids = {cls._shadow_identity(item) for item in v1_results if cls._shadow_identity(item)}
        v2_ids = {cls._shadow_identity(item) for item in v2_results if cls._shadow_identity(item)}
        v2_error = bool((v2.get("debug") or {}).get("error_code") or (v2.get("debug") or {}).get("error"))
        v1_candidate_rows = [
            projected
            for index, item in enumerate(cls._shadow_rows(v1, "candidate_snapshot", v1_results), 1)
            if (projected := cls._shadow_candidate(item, index)) is not None
        ]
        v2_candidate_rows = [
            projected
            for index, item in enumerate(cls._shadow_rows(v2, "candidate_snapshot", v2_results), 1)
            if (projected := cls._shadow_candidate(item, index)) is not None
        ]
        v1_final_rows = [
            projected
            for index, item in enumerate(v1_results[:50], 1)
            if (projected := cls._shadow_final_chunk(item, index)) is not None
        ]
        v2_final_rows = [
            projected
            for index, item in enumerate(v2_results[:50], 1)
            if (projected := cls._shadow_final_chunk(item, index)) is not None
        ]
        return {
            "mode": "v1_primary_v2_shadow",
            "status": "degraded" if v2_error else "ok",
            "user_answer_source": "v1",
            "v1_result_count": len(v1_results),
            "v2_result_count": len(v2_results),
            "overlap_count": len(v1_ids & v2_ids),
            "v1_only_count": len(v1_ids - v2_ids),
            "v2_only_count": len(v2_ids - v1_ids),
            "v1_top_hashes": cls._shadow_hashes(v1_results),
            "v2_top_hashes": cls._shadow_hashes(v2_results),
            "v1_latency_ms": max(0, int(v1_latency_ms)),
            "v2_latency_ms": max(0, int(v2_latency_ms)),
            "index_version": str(generation.get("index_version") or "")[:128],
            "error_code": "RETRIEVAL_V2_SHADOW_FAILED" if v2_error else None,
            "v1_candidates": v1_candidate_rows[:20],
            "v2_candidates": v2_candidate_rows[:20],
            "v1_final_chunks": v1_final_rows[:20],
            "v2_final_chunks": v2_final_rows[:20],
            "difference": {
                "added_hashes": cls._shadow_only_hashes(v2_final_rows, v1_final_rows, "chunk_hash"),
                "removed_hashes": cls._shadow_only_hashes(v1_final_rows, v2_final_rows, "chunk_hash"),
                "candidate_added_hashes": cls._shadow_only_hashes(v2_candidate_rows, v1_candidate_rows, "candidate_hash"),
                "candidate_removed_hashes": cls._shadow_only_hashes(v1_candidate_rows, v2_candidate_rows, "candidate_hash"),
                "score_deltas": cls._shadow_score_deltas(v1_final_rows, v2_final_rows, "chunk_hash"),
            },
        }

    def search(self, request: RetrievalRequest, min_relevance: float = 0.20) -> Dict[str, Any]:
        """Return one user-visible V1 answer and optionally compare V2 in shadow.

        V2 is never selected merely because an active generation exists.  A
        rollout flag must explicitly enable it.  In shadow mode the V2 call is
        read-only and its results are reduced to bounded, hashed metrics.
        """
        generation = self._active_index_generation(request.tenant_id)
        if not generation:
            return self._search_once(request, min_relevance, active_generation=None)

        user_ctx = {
            "tenant_id": getattr(request, "tenant_id", "tenant-default"),
            "user_id": getattr(request, "user_id", None),
            "roles": getattr(request, "roles", None),
            "site_ids": getattr(request, "site_ids", None),
        }
        v2_enabled, rollout_reason, rollout_meta = feature_flag_service.evaluate_v2_access(user_ctx)
        shadow_enabled = self._setting_flag("KNOWLEDGE_V2_SHADOW_READ")

        if shadow_enabled and not v2_enabled:
            started = time.perf_counter()
            v1 = self._search_once(request, min_relevance, active_generation=None)
            v1_elapsed = int((time.perf_counter() - started) * 1000)
            v2_started = time.perf_counter()
            try:
                v2 = self._search_once(request, min_relevance, active_generation=generation)
            except Exception:
                v2 = {"results": [], "debug": {"error_code": "RETRIEVAL_V2_SHADOW_FAILED"}}
            v2_elapsed = int((time.perf_counter() - v2_started) * 1000)
            debug = dict(v1.get("debug") or {})
            debug["index_source"] = "v1"
            debug["shadow"] = self._shadow_compare(
                v1,
                v2,
                v1_latency_ms=v1_elapsed,
                v2_latency_ms=v2_elapsed,
                generation=generation,
            )
            v1["debug"] = debug
            return v1

        if v2_enabled:
            v2_res = self._search_once(request, min_relevance, active_generation=generation)
            debug = dict(v2_res.get("debug") or {})
            debug["index_source"] = "v2"
            debug["rollout_reason"] = rollout_reason
            debug["rollout_meta"] = rollout_meta
            v2_res["debug"] = debug
            return v2_res

        return self._search_once(request, min_relevance, active_generation=None)

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        vendor: Optional[str] = None,
        platform: Optional[str] = None,
        min_relevance: float = 0.30,
        tenant_id: str = "tenant-default",
        user_id: str | None = None,
        roles: Optional[List[str]] = None,
        site_ids: Optional[List[str]] = None,
        **metadata_filters: Any,
    ) -> List[Dict[str, Any]]:
        resolved_filters = dict(metadata_filters)
        # Direct callers (CLI, tests and future APIs) use the same Product
        # Resolver boundary as the Assistant path. Explicit caller filters
        # always win; inferred values are only populated from query evidence.
        try:
            resolution = product_resolver.resolve_query(
                query,
                resolved_filters,
                tenant_id=tenant_id or "tenant-default",
            )
            if not resolution.ambiguous:
                resolved_filters.update({
                    key: value
                    for key, value in resolution.metadata.items()
                    if key not in resolved_filters and value not in (None, "", [], {})
                })
            resolved_filters["normalized_query"] = {
                "query": resolution.normalized_query,
                "match_method": resolution.match_method,
                "match_score": resolution.match_score,
                "candidate_count": len(resolution.candidates),
            }
            resolved_filters["resolution"] = resolution.to_dict()
        except Exception:
            resolution = None
        # ``resolve_query`` can legitimately return vendor/cli_platform in
        # the inferred metadata.  Build one mapping before constructing the
        # dataclass; passing the same key once as a named argument and once
        # through ``**resolved_filters`` raises ``TypeError`` and used to
        # make direct/CLI conversations fail before SQL retrieval.
        request_values = dict(resolved_filters)
        if vendor is not None:
            request_values["vendor"] = vendor
        if platform is not None:
            request_values["cli_platform"] = platform
        request_values.update({
            "top_k": top_k,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "roles": roles,
            "site_ids": site_ids,
        })
        request = RetrievalRequest.from_mapping(query, request_values)
        return self.search(request, min_relevance=min_relevance)["results"]


rag_retriever = RAGRetriever()
