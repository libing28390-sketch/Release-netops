"""Deterministic retrieval contracts shared by the RAG and grounding layers.

This module deliberately contains no database or provider calls.  It provides
the stable pieces that must remain testable when the PostgreSQL accelerator is
disabled: score fusion, version compatibility, bounded reranking, cache-key
construction/invalidation, minimal context selection and a redacted
explanation object.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence


RETRIEVAL_INDEX_VERSION = "retrieval-v1"
RETRIEVAL_CACHE_VERSION = "ret-cache-v1"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _version_tokens(value: Any) -> tuple[int, ...] | None:
    text = _text(value).upper()
    if not text:
        return None
    numbers = re.findall(r"\d+", text)
    return tuple(int(item) for item in numbers) if numbers else None


def version_compatibility(
    requested_train: Any = None,
    requested_release: Any = None,
    actual_train: Any = None,
    actual_release: Any = None,
    applicable_versions: Iterable[Any] | None = None,
) -> tuple[float, str]:
    """Return a bounded score and stable evidence label for version matching.

    Exact release is strongest; a matching software train or an explicit
    applicable-version list is compatible but weaker.  A known conflicting
    release is zero and is never silently promoted by lexical similarity.
    Missing version evidence is neutral (0.5) only when the caller did not
    request a version; with an explicit request it is low confidence (0.15).
    """

    req_release = _text(requested_release).upper()
    req_train = _text(requested_train).upper()
    act_release = _text(actual_release).upper()
    act_train = _text(actual_train).upper()
    allowed = {_text(item).upper() for item in (applicable_versions or []) if _text(item)}
    if not req_release and not req_train:
        return 0.5, "not_requested"
    if req_release and act_release and req_release == act_release:
        return 1.0, "exact_release"
    if req_release and req_release in allowed:
        return 0.95, "applicable_release"
    if req_train and act_train and req_train == act_train:
        if req_release and act_release and _version_tokens(req_release) and _version_tokens(act_release):
            return 0.72, "same_train_release_unknown"
        return 0.82, "same_train"
    if req_release and act_release:
        return 0.0, "release_conflict"
    if req_train and act_train:
        return 0.0, "train_conflict"
    return (0.15 if (req_release or req_train) else 0.5), "version_evidence_missing"


@dataclass(frozen=True)
class ScoreComponents:
    lexical: float
    vector: float
    metadata: float
    trust: float
    version: float

    @property
    def total(self) -> float:
        # Weights are frozen for reproducible ranking and exposed in the
        # explanation object.  They sum to one and keep hard metadata filters
        # separate from the soft ranking signals.
        return max(
            0.0,
            min(
                1.0,
                0.45 * self.lexical
                + 0.25 * self.vector
                + 0.15 * self.metadata
                + 0.10 * self.trust
                + 0.05 * self.version,
            ),
        )

    def to_dict(self) -> dict[str, float | dict[str, float]]:
        return {
            "lexical": round(self.lexical, 4),
            "vector": round(self.vector, 4),
            "metadata": round(self.metadata, 4),
            "trust": round(self.trust, 4),
            "version": round(self.version, 4),
            "total": round(self.total, 4),
            "weights": {
                "lexical": 0.45,
                "vector": 0.25,
                "metadata": 0.15,
                "trust": 0.10,
                "version": 0.05,
            },
        }


class RetrievalResultCache:
    """Small process-local cache with exact-key and precise invalidation."""

    def __init__(self, *, max_entries: int = 512, ttl_seconds: float = 60.0) -> None:
        self.max_entries = max(1, int(max_entries))
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._items: OrderedDict[str, tuple[float, dict[str, Any], set[str], str]] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires, value, _documents, _tenant = item
            if expires <= now:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return json.loads(json.dumps(value, ensure_ascii=False))

    def set(self, key: str, value: Mapping[str, Any], *, document_ids: Iterable[Any] = (), tenant_id: str = "") -> None:
        with self._lock:
            self._items[key] = (
                time.monotonic() + self.ttl_seconds,
                json.loads(json.dumps(dict(value), ensure_ascii=False)),
                {str(item) for item in document_ids},
                _text(tenant_id),
            )
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)

    def invalidate_documents(self, document_ids: Iterable[Any]) -> int:
        ids = {str(item) for item in document_ids if _text(item)}
        if not ids:
            return 0
        with self._lock:
            keys = [key for key, (_expires, _value, docs, _tenant) in self._items.items() if docs & ids]
            for key in keys:
                self._items.pop(key, None)
            return len(keys)

    def invalidate_tenant(self, tenant_id: str) -> int:
        tenant = _text(tenant_id)
        with self._lock:
            keys = [key for key, (_expires, _value, _docs, owner) in self._items.items() if owner == tenant]
            for key in keys:
                self._items.pop(key, None)
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def retrieval_cache_key(
    request: Any,
    *,
    document_version: str = "",
    metadata_version: str = "",
    index_version: str = RETRIEVAL_INDEX_VERSION,
    access_scope: Mapping[str, Any] | None = None,
) -> str:
    """Build a stable key containing every version and authorization scope."""

    payload = {
        "cache_version": RETRIEVAL_CACHE_VERSION,
        "query": _text(getattr(request, "query", "")),
        "tenant_id": _text(getattr(request, "tenant_id", "tenant-default")),
        "filters": {
            key: getattr(request, key, None)
            for key in sorted(getattr(request, "__dataclass_fields__", {}))
            if key not in {"query", "include_debug", "normalized_query", "resolution"}
        },
        "document_version": _text(document_version),
        "metadata_version": _text(metadata_version),
        "index_version": _text(index_version) or RETRIEVAL_INDEX_VERSION,
        "access_scope": dict(access_scope or {
            "user_id": getattr(request, "user_id", None),
            "roles": sorted(str(item) for item in (getattr(request, "roles", None) or [])),
            "site_ids": sorted(str(item) for item in (getattr(request, "site_ids", None) or [])),
        }),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Reranker:
    """Interface for optional rerankers; the default implementation is no-op."""

    name = "none"

    def rank(self, query: str, candidates: Sequence[Mapping[str, Any]]) -> list[float]:
        return [float(item.get("relevance_score") or 0.0) for item in candidates]


class BoundedReranker:
    """Run a supplied reranker under a strict timeout and candidate/cost cap."""

    def __init__(self, reranker: Any = None, *, timeout_ms: int = 120, max_candidates: int = 20) -> None:
        self.reranker = reranker or Reranker()
        self.timeout_ms = max(1, min(int(timeout_ms), 5000))
        self.max_candidates = max(1, min(int(max_candidates), 100))

    def apply(self, query: str, candidates: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        bounded = list(candidates[: self.max_candidates])
        if not bounded:
            return [], {"stage": "skipped", "reason": "no_candidates", "cost_units": 0}
        started = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="ret-rerank") as pool:
                future = pool.submit(self.reranker.rank, query, bounded)
                values = future.result(timeout=self.timeout_ms / 1000.0)
            scores = [max(0.0, min(1.0, float(value))) for value in values]
            if len(scores) != len(bounded):
                raise ValueError("reranker returned an invalid score count")
            for item, score in zip(bounded, scores):
                item["reranker_score"] = round(score, 4)
                item["relevance_score"] = round(0.70 * float(item.get("relevance_score") or 0.0) + 0.30 * score, 4)
            bounded.sort(key=lambda item: (float(item.get("relevance_score") or 0.0), int(item.get("source_trust_rank") or 0)), reverse=True)
            return bounded, {
                "stage": "applied",
                "name": str(getattr(self.reranker, "name", type(self.reranker).__name__)),
                "timeout_ms": self.timeout_ms,
                "candidate_count": len(bounded),
                "cost_units": len(bounded),
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        except (FutureTimeout, Exception) as exc:
            return candidates, {
                "stage": "degraded",
                "name": str(getattr(self.reranker, "name", type(self.reranker).__name__)),
                "timeout_ms": self.timeout_ms,
                "candidate_count": len(bounded),
                "cost_units": 0,
                "reason": "timeout" if isinstance(exc, FutureTimeout) else "reranker_error",
            }


def build_minimal_context(primary: Mapping[str, Any], chunks: Sequence[Mapping[str, Any]], *, max_chars: int = 10000) -> dict[str, Any]:
    """Select primary + parent + immediate neighbors under a hard budget."""

    primary_id = _text(primary.get("chunk_id"))
    parent_id = _text(primary.get("parent_chunk_id"))
    ordinal = int(primary.get("ordinal") or 0)
    by_id = {_text(item.get("chunk_id")): item for item in chunks if _text(item.get("chunk_id"))}
    selected: list[Mapping[str, Any]] = []
    for item in chunks:
        item_id = _text(item.get("chunk_id"))
        if item_id == primary_id or (parent_id and item_id == parent_id) or abs(int(item.get("ordinal") or 0) - ordinal) <= 1:
            selected.append(item)
    if primary_id and primary_id not in {_text(item.get("chunk_id")) for item in selected}:
        selected.insert(0, primary)
    selected.sort(key=lambda item: (0 if _text(item.get("chunk_id")) == primary_id else 1, int(item.get("ordinal") or 0), _text(item.get("chunk_id"))))
    parts: list[str] = []
    ids: list[str] = []
    used = 0
    for item in selected:
        content = _text(item.get("content"))
        if not content:
            continue
        section = _text(item.get("section")) or "General Overview"
        rendered = f"## {section}\n{content}"
        if parts and used + len(rendered) + 2 > max_chars:
            continue
        parts.append(rendered)
        ids.append(_text(item.get("chunk_id")))
        used += len(rendered) + 2
    return {
        "content": "\n\n".join(parts),
        "context_chunk_ids": ids,
        "context_chunk_count": len(ids),
        "context_char_count": used,
        "context_budget": max_chars,
    }


def build_retrieval_explanation(request: Any, debug: Mapping[str, Any], results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a safe evidence-panel object without raw query/content/secrets."""

    candidate_summaries = []
    for item in results[:20]:
        candidate_summaries.append({
            "document_id": item.get("document_id"),
            "chunk_id": item.get("chunk_id"),
            "section": item.get("section"),
            "relevance_score": item.get("relevance_score"),
            "score_components": item.get("score_components"),
            "source_trust_rank": item.get("source_trust_rank"),
            "version_evidence": item.get("version_evidence"),
        })
    filters = {
        key: getattr(request, key, None)
        for key in (
            "tenant_id", "vendor", "product_family", "product_series", "product_model",
            "os_family", "os_generation", "software_train", "software_release",
            "cli_platform", "document_category", "feature_domain", "feature",
            "subfeature", "risk_level", "verification_level", "status",
        )
        if getattr(request, key, None) not in (None, "", [], {})
    }
    return {
        "contract_version": "ret-explanation-v1",
        "filters": filters,
        "candidate_count": int(debug.get("candidate_count") or 0),
        "metadata_candidate_documents": int(debug.get("metadata_candidate_documents") or 0),
        "final_count": len(results),
        "stages": {
            key: debug.get(key)
            for key in (
                "fts_stage", "trgm_stage", "vector_stage", "reranker",
                "clarification_required", "capability_degraded",
            )
            if key in debug
        },
        "candidates": candidate_summaries,
        "no_match": not bool(results),
        "ambiguous": bool(debug.get("clarification_required") or debug.get("cross_platform_search")),
    }


retrieval_cache = RetrievalResultCache()

