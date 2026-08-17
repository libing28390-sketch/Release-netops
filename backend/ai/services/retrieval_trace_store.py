"""Bounded, tenant-scoped and metadata-only retrieval trace store.

The durable DB-012 trace tables are a later migration concern.  KUI-017 uses
an in-process bounded read model so administrators can inspect the current
worker without introducing an out-of-order schema migration.  Every value is
projected through an allowlist before it enters the store.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Mapping

from ai.security.sanitizer import sanitize_log_text


MAX_TRACES = 200
MAX_CITATIONS = 20
MAX_OBSERVATION_CANDIDATES = 100
MAX_OBSERVATION_CHUNKS = 50
_REQUEST_FIELDS = (
    "vendor", "product_series", "product_model", "software_train",
    "cli_platform", "document_category", "feature_domain", "feature",
)
_FILTER_FIELDS = (
    "vendor", "product_family", "product_series", "product_model", "os_family",
    "os_generation", "software_train", "software_release", "cli_platform",
    "document_category", "feature_domain", "feature", "subfeature", "risk_level",
    "verification_level", "rag_priority", "status",
)
_ENTITY_FIELDS = (
    "vendor", "product", "product_family", "product_series", "product_model",
    "os_family", "os_generation", "software_train", "software_release", "cli_platform",
    "topic", "feature", "command", "error", "intent",
)
_LOCK = threading.RLock()
_TRACES: deque[dict[str, Any]] = deque(maxlen=MAX_TRACES)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any, limit: int = 128) -> str:
    return sanitize_log_text(value, limit=limit).replace("<REDACTED>", "<redacted>").strip()[:limit]


def _hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_score(value: Any) -> float | None:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return None


def _safe_hash(value: Any) -> str:
    return _hash(value)[:32]


def _safe_mapping(value: Any, fields: tuple[str, ...], *, limit: int = 128) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in fields:
        item = value.get(key)
        if item in (None, "", [], {}):
            continue
        if isinstance(item, (list, tuple, set)):
            result[key] = [_text(entry, limit) for entry in list(item)[:20]]
        elif isinstance(item, (str, int, float, bool)):
            result[key] = _text(item, limit) if isinstance(item, str) else item
    return result


def _runtime_projection(runtime: Any) -> dict[str, Any]:
    runtime = runtime if isinstance(runtime, Mapping) else {}
    reranker = runtime.get("reranker") if isinstance(runtime.get("reranker"), Mapping) else {}
    latency = runtime.get("latency") if isinstance(runtime.get("latency"), Mapping) else {}
    tokens = runtime.get("tokens") if isinstance(runtime.get("tokens"), Mapping) else {}
    security = runtime.get("security") if isinstance(runtime.get("security"), Mapping) else {}
    citation = runtime.get("citation") if isinstance(runtime.get("citation"), Mapping) else {}
    quality = runtime.get("quality") if isinstance(runtime.get("quality"), Mapping) else {}
    token_projection = {
        key: _nonnegative_int(tokens.get(key))
        for key in ("input", "output", "total")
        if tokens.get(key) is not None
    }
    if "total" not in token_projection and {"input", "output"}.issubset(token_projection):
        token_projection["total"] = token_projection["input"] + token_projection["output"]
    return {
        "reranker": {
            "stage": _text(reranker.get("stage"), 32),
            "name": _text(reranker.get("name"), 64),
            "candidate_count": _nonnegative_int(reranker.get("candidate_count")),
            "timeout_ms": _nonnegative_int(reranker.get("timeout_ms")),
            "cost_units": _nonnegative_int(reranker.get("cost_units")),
            "reason": _text(reranker.get("reason"), 64),
        },
        "citation": {
            "count": _nonnegative_int(citation.get("count")),
            "warning_count": _nonnegative_int(citation.get("warning_count")),
            "verified_count": _nonnegative_int(citation.get("verified_count")),
            "failed_count": _nonnegative_int(citation.get("failed_count")),
        },
        "latency": {
            key: _nonnegative_int(latency.get(key))
            for key in ("retrieval_ms", "reranker_ms", "llm_ms", "total_ms")
            if latency.get(key) is not None
        },
        "tokens": token_projection,
        "provider": {
            "provider_id": _text(runtime.get("provider_id"), 96),
            "model_id": _text(runtime.get("model_id"), 128),
            "requested_model_id": _text(runtime.get("requested_model_id"), 128),
            "route_reason": _text(runtime.get("route_reason"), 64),
            "fallback_used": bool(runtime.get("fallback_used")),
        },
        "security": {
            "decision": _text(security.get("decision") or runtime.get("security_result") or "not_recorded", 32),
            "policy_version": _text(security.get("policy_version"), 64),
            "result_code": _text(security.get("result_code"), 64),
        },
        "quality": {
            "no_match": bool(quality.get("no_match")),
            "wrong_vendor_count": _nonnegative_int(quality.get("wrong_vendor_count")),
            "version_conflict_count": _nonnegative_int(quality.get("version_conflict_count")),
            "low_confidence_count": _nonnegative_int(quality.get("low_confidence_count")),
            "low_confidence_threshold": _safe_score(quality.get("low_confidence_threshold")),
            "top_relevance_score": _safe_score(quality.get("top_relevance_score")),
            "error": bool(quality.get("error")),
        },
    }


def _merge_runtime(current: Mapping[str, Any] | None, update: Mapping[str, Any]) -> dict[str, Any]:
    """Merge runtime observations without dropping previously recorded stages."""

    merged: dict[str, Any] = dict(current) if isinstance(current, Mapping) else {}
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = {**dict(merged[key]), **dict(value)}
        else:
            merged[key] = value
    return merged


def _candidate_projection(item: Mapping[str, Any], rank: int) -> dict[str, Any]:
    identity = f"{item.get('storage_document_id') or item.get('document_id') or ''}:{item.get('chunk_id') or item.get('alias') or rank}"
    components = item.get("score_components") if isinstance(item.get("score_components"), Mapping) else {}
    return {
        "rank": rank,
        "candidate_hash": _safe_hash(identity),
        "match_method": _text(item.get("match_method"), 32),
        "match_score": _safe_score(item.get("match_score")),
        "relevance_score": _safe_score(item.get("relevance_score")),
        "keyword_score": _safe_score(item.get("keyword_score")),
        "vector_score": _safe_score(item.get("vector_score")),
        "metadata_score": _safe_score(item.get("metadata_score")),
        "trust_score": _safe_score(item.get("trust_score")),
        "version_score": _safe_score(item.get("version_score")),
        "score_components": {
            key: _safe_score(components.get(key))
            for key in ("lexical", "vector", "metadata", "trust", "version", "total")
            if components.get(key) is not None
        },
        "version_evidence": _text(item.get("version_evidence"), 64),
        "source_trust_rank": _nonnegative_int(item.get("source_trust_rank")),
    }


def _observation_projection(*, query: str, observation: Mapping[str, Any] | None) -> dict[str, Any]:
    observation = observation if isinstance(observation, Mapping) else {}
    normalized = _text(observation.get("normalized_query"), 2000)
    raw_query = str(observation.get("raw_query") or query or "")
    entities = _safe_mapping(observation.get("entities"), _ENTITY_FIELDS, limit=160)
    filters = _safe_mapping(observation.get("filters"), _FILTER_FIELDS, limit=128)
    candidates = observation.get("candidates") if isinstance(observation.get("candidates"), list) else []
    final_chunks = observation.get("final_chunks") if isinstance(observation.get("final_chunks"), list) else []
    return {
        "schema": "nxa.retrieval.observation.v1",
        "query": {
            # The raw query is observed at the request boundary but is never
            # persisted or returned; DB-012 requires hash/length only.
            "raw_query_captured": bool(raw_query),
            "raw_query_retention": "request_scope_only",
            "raw_query_hash": _hash(raw_query),
            "raw_query_length": len(raw_query),
            "normalized_query": normalized,
            "normalized_query_hash": _hash(normalized),
        },
        "entities": entities,
        "filters": filters,
        "candidates": [
            _candidate_projection(item, index + 1)
            for index, item in enumerate(candidates[:MAX_OBSERVATION_CANDIDATES])
            if isinstance(item, Mapping)
        ],
        "scores": [
            _candidate_projection(item, index + 1)
            for index, item in enumerate(candidates[:MAX_OBSERVATION_CANDIDATES])
            if isinstance(item, Mapping)
        ],
        "final_chunks": [
            {
                "rank": index + 1,
                "chunk_hash": _safe_hash(f"{item.get('storage_document_id') or item.get('document_id') or ''}:{item.get('chunk_id') or ''}"),
                "context_chunk_count": _nonnegative_int(item.get("context_chunk_count")),
                "context_chunk_hashes": [_safe_hash(value) for value in (item.get("context_chunk_ids") or [])[:20]],
                "relevance_score": _safe_score(item.get("relevance_score")),
            }
            for index, item in enumerate(final_chunks[:MAX_OBSERVATION_CHUNKS])
            if isinstance(item, Mapping)
        ],
    }


def _citation_projection(item: Mapping[str, Any]) -> dict[str, Any]:
    # Citation identity and applicability are useful to an admin; document,
    # chunk, URL and source-body identifiers are intentionally omitted.
    return {
        "citation_id": _text(item.get("citation_id"), 96),
        "vendor": _text(item.get("vendor"), 64),
        "product": _text(item.get("product"), 128),
        "software_version": _text(item.get("software_version"), 96),
        "source_type": _text(item.get("source_type"), 64),
        "status": _text(item.get("status"), 32),
        "trust": _text(item.get("trust"), 32),
        "validation": _text(item.get("validation"), 64),
        "warning_count": len(item.get("warnings") or []) if isinstance(item.get("warnings"), list) else 0,
    }


def _project(
    *,
    trace_id: str,
    tenant_id: str,
    user_id: str | None,
    query: str,
    trace: Mapping[str, Any],
    observation: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    request = trace.get("request") if isinstance(trace.get("request"), Mapping) else {}
    resolution = trace.get("resolution") if isinstance(trace.get("resolution"), Mapping) else {}
    citations = trace.get("citations") if isinstance(trace.get("citations"), list) else []
    request_projection = {
        key: _text(request.get(key), 128)
        for key in _REQUEST_FIELDS
        if request.get(key) not in (None, "", [], {})
    }
    return {
        "trace_id": trace_id,
        "request_id": _text(request_id or trace.get("request_id"), 128) or None,
        "tenant_id": _text(tenant_id, 128),
        "actor_hash": _hash(user_id)[:16] if user_id else None,
        "query_hash": _hash(query),
        "created_at": _now(),
        "source": _text(trace.get("source") or "local_rag", 32),
        "status": _text(trace.get("status") or "not_run", 32),
        "metadata_candidate_documents": _nonnegative_int(trace.get("metadata_candidate_documents")),
        "candidate_count": _nonnegative_int(trace.get("candidate_count")),
        "dedup_document_count": _nonnegative_int(trace.get("dedup_document_count")),
        "final_document_count": _nonnegative_int(trace.get("final_document_count")),
        "vector_top_n": _nonnegative_int(trace.get("vector_top_n")),
        "clarification_required": bool(trace.get("clarification_required")),
        "cross_platform_search": bool(trace.get("cross_platform_search")),
        "request": request_projection,
        "resolution": {
            "ambiguous": bool(resolution.get("ambiguous")),
            "platform_candidates": [_text(value, 96) for value in (resolution.get("platform_candidates") or [])[:20]],
            "evidence": _text(resolution.get("evidence") or "none", 64),
        },
        "observation": _observation_projection(query=query, observation=observation),
        "runtime": _runtime_projection(trace.get("runtime")),
        "citations": [_citation_projection(item) for item in citations[:MAX_CITATIONS] if isinstance(item, Mapping)],
        "citation_warning_count": len(trace.get("citation_warnings") or []) if isinstance(trace.get("citation_warnings"), list) else 0,
        "redaction": {
            "default": True,
            "raw_query_included": False,
            "raw_chunk_included": False,
            "raw_sql_included": False,
            "credentials_included": False,
        },
    }


def record_retrieval_trace(*, tenant_id: str, user_id: str | None, query: str, trace: Mapping[str, Any], observation: Mapping[str, Any] | None = None, request_id: str | None = None) -> str:
    trace_id = f"rt_{uuid.uuid4().hex[:24]}"
    projected = _project(trace_id=trace_id, tenant_id=tenant_id or "tenant-default", user_id=user_id, query=query, trace=trace, observation=observation, request_id=request_id)
    with _LOCK:
        _TRACES.appendleft(projected)
    return trace_id


def update_retrieval_trace(trace_id: str, *, citations: list[Mapping[str, Any]] | None = None, citation_warnings: list[Mapping[str, Any]] | None = None, runtime: Mapping[str, Any] | None = None) -> None:
    with _LOCK:
        for item in _TRACES:
            if item.get("trace_id") != trace_id:
                continue
            if citations is not None:
                item["citations"] = [_citation_projection(value) for value in citations[:MAX_CITATIONS]]
            if citation_warnings is not None:
                item["citation_warning_count"] = len(citation_warnings)
            if citations is not None or citation_warnings is not None:
                current_runtime = item.get("runtime") if isinstance(item.get("runtime"), Mapping) else {}
                current_citation = current_runtime.get("citation") if isinstance(current_runtime.get("citation"), Mapping) else {}
                item["runtime"] = _runtime_projection(_merge_runtime(current_runtime, {
                    "citation": {
                        **current_citation,
                        "count": len(citations) if citations is not None else current_citation.get("count", 0),
                        "warning_count": len(citation_warnings) if citation_warnings is not None else current_citation.get("warning_count", 0),
                        "verified_count": sum(1 for value in (citations or []) if str(value.get("validation") or "").lower() in {"verified", "validated", "validated_official"}) if citations is not None else current_citation.get("verified_count", 0),
                        "failed_count": sum(1 for value in (citations or []) if str(value.get("validation") or "").lower() in {"failed", "mismatch", "stale", "acl_denied"}) if citations is not None else current_citation.get("failed_count", 0),
                    },
                }))
            if runtime is not None:
                current_runtime = item.get("runtime") if isinstance(item.get("runtime"), Mapping) else {}
                item["runtime"] = _runtime_projection(_merge_runtime(current_runtime, runtime))
            return


def list_retrieval_traces(*, tenant_id: str, limit: int = 50, status: str = "all") -> list[dict[str, Any]]:
    bounded = max(1, min(int(limit or 50), MAX_TRACES))
    status_filter = _text(status or "all", 32).lower()
    with _LOCK:
        rows = [dict(item) for item in _TRACES if item.get("tenant_id") == (tenant_id or "tenant-default") and (status_filter in {"", "all"} or item.get("status") == status_filter)]
    return rows[:bounded]


def get_retrieval_trace(*, tenant_id: str, trace_id: str) -> dict[str, Any] | None:
    with _LOCK:
        for item in _TRACES:
            if item.get("trace_id") == trace_id and item.get("tenant_id") == (tenant_id or "tenant-default"):
                return dict(item)
    return None


def clear_retrieval_traces() -> None:
    """Test-only reset hook; production code never calls this."""

    with _LOCK:
        _TRACES.clear()


__all__ = [
    "MAX_TRACES",
    "clear_retrieval_traces",
    "get_retrieval_trace",
    "list_retrieval_traces",
    "record_retrieval_trace",
    "update_retrieval_trace",
]
