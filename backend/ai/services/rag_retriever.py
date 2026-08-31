"""Metadata-first Retriever for the V1 knowledge projection.

Eligibility is decided in SQL from structured document metadata.  Embeddings
and lexical signals only rank the already eligible candidate set; they can
never make an incompatible platform or document category eligible.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from database.core import get_db_connection
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
            if "metadata_json" in columns:
                where.append(
                    "(LOWER(COALESCE(d.software_release, '')) = LOWER(?) OR "
                    "COALESCE(d.metadata_json -> 'applicable_versions', '[]'::jsonb) @> jsonb_build_array(?) OR "
                    "COALESCE(d.metadata_json -> 'verified_versions', '[]'::jsonb) @> jsonb_build_array(?))"
                )
                params.extend([release, release, release])
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
                if is_series_prefix:
                    # Registry metadata is mixed-version: some imports store
                    # product_series as a scalar and others as an
                    # applicability array. Text containment remains guarded
                    # by the vendor/category predicates above.
                    where.append(f"({scalar} OR LOWER(CAST(d.metadata_json AS TEXT)) LIKE LOWER(?))")
                    params.extend([scalar_value, f"%{value_text}%"] if column in columns else [f"%{value_text}%"])
                else:
                    array_expr = " OR ".join(
                        f"COALESCE(d.metadata_json -> '{key}', '[]'::jsonb) @> jsonb_build_array(?)"
                        for key in array_keys
                    )
                    # A short, reviewed hardware alias such as CE6885 or
                    # C9300 may be stored as the full SKU
                    # (CE6885-48YS8CQ / C9300-24T) in the registry.
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
                where.append(scalar)
                if column in columns:
                    params.append(scalar_value)

        if request.cli_platform and "cli_platform" in columns:
            # Never allow platform=all to satisfy a concrete command,
            # configuration, or CLI-output request.  Neutral documents are
            # represented by NULL, not the string all.
            platform_value = str(request.cli_platform)
            if "metadata_json" in columns:
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
            else:
                where.append("LOWER(d.cli_platform) = LOWER(?)")
                params.append(platform_value)
        if request.rag_priority is not None and "rag_priority" in columns:
            where.append("COALESCE(d.rag_priority, 0) >= ?")
            params.append(int(request.rag_priority))

        # Additional applicability arrays are PostgreSQL JSONB hard
        # predicates evaluated before any chunks enter Python.
        for key, requested in (request.applicability or {}).items():
            values = requested if isinstance(requested, (list, tuple, set)) else [requested]
            for value in values:
                if value is None or "metadata_json" not in columns:
                    continue
                where.append(f"COALESCE(d.metadata_json -> '{key}', '[]'::jsonb) @> jsonb_build_array(?)")
                params.append(str(value))
        return " AND ".join(where), params

    def _query_rows(
        self,
        request: RetrievalRequest,
        vector_top_n: int,
    ) -> tuple[list[Any], int, Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            columns = self._table_columns(cursor, "ai_document")
            chunk_columns = self._table_columns(cursor, "ai_document_chunk")
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
            cursor.execute(
                f"""SELECT c.id, c.content, c.embedding, c.metadata_json, c.section,
                           d.id, d.name, {source_expr}, {document_version_expr}, d.vendor, d.platform, d.tenant_id,
                           d.acl_json, d.source_trust_level,
                           {document_category_expr}, {cli_platform_expr}, {semantic_document_id_expr},
                           {software_train_expr}, {software_release_expr},
                           {candidate_expr}, {chunk_role_expr},
                           {parent_expr}, {ordinal_expr}, {embedding_model_expr}, {embedding_dimensions_expr}
                     FROM ai_document_chunk c
                     JOIN ai_document d ON c.document_id = d.id
                     WHERE {where_sql}
                       {candidate_where}
                     ORDER BY d.id ASC, {ordinal_order_expr} ASC, c.id ASC""",
                 params,
            )
            rows = cursor.fetchall()
            debug = {
                "metadata_filter": where_sql,
                "metadata_candidate_documents": document_count,
                "candidate_count": len(rows),
                # Every metadata-eligible chunk is scored.  This field is
                # retained for the existing trace contract.
                "vector_top_n": len(rows),
                "index_source": "v1",
            }
            return rows, document_count, debug

    def _native_accelerator_scores(
        self,
        request: RetrievalRequest,
        chunk_ids: Sequence[Any],
    ) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
        """Run bounded PostgreSQL FTS/trigram/vector scores.

        The tenant/status/ACL eligibility query has already produced the IDs;
        every accelerator query is therefore bounded to that candidate set.
        """
        debug: dict[str, Any] = {
            "fts_stage": "disabled",
            "trgm_stage": "disabled",
            "vector_stage": "disabled",
            "fts_candidates": 0,
            "trgm_candidates": 0,
            "vector_candidates": 0,
            "capability_degraded": [],
            "index_source": "v1",
        }
        if not chunk_ids:
            return {}, debug
        scores: dict[str, dict[str, float]] = {}
        placeholders = ", ".join("?" for _ in chunk_ids)
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                source_table = "ai_document_chunk"
                columns = self._table_columns(cursor, source_table)
                scope_sql = ""
                scope_params: list[Any] = []
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
    ) -> Dict[str, Any]:
        """Execute one bounded retrieval against the V1 document projection."""
        top_k = max(1, int(request.top_k or 3))
        candidate_hint = max(top_k * 30, 100)
        cache_key = retrieval_cache_key(
            request,
            index_version="retrieval-v1",
        )
        if self.cache_enabled:
            cached = retrieval_cache.get(cache_key)
            if cached is not None:
                cached.setdefault("debug", {})["cache"] = {"hit": True, "key": cache_key}
                self.last_debug = cached.get("debug") or {}
                return cached
        try:
            rows, _document_count, debug = self._query_rows(request, candidate_hint)
            accelerator_scores, accelerator_debug = self._native_accelerator_scores(
                request,
                [row[0] for row in rows],
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

    def search(self, request: RetrievalRequest, min_relevance: float = 0.20) -> Dict[str, Any]:
        """Return the user-visible result from the single V1 retrieval path."""
        return self._search_once(request, min_relevance)

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
