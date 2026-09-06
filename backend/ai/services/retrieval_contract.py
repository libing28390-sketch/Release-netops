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
import math
import os
import re
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

from core.bounded_executor import BoundedDaemonExecutor, BoundedExecutorSaturated


RETRIEVAL_INDEX_VERSION = "retrieval-v1"
RETRIEVAL_CACHE_VERSION = "ret-cache-v1"
_RERANKER_MAX_QUERY_CHARS = 4096
_RERANKER_MAX_CANDIDATE_CHARS = 12_000
_RERANKER_MAX_CANDIDATES = 100
_RERANKER_MAX_PAYLOAD_BYTES = 256_000


def _bounded_int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


_RERANKER_EXECUTOR = BoundedDaemonExecutor(
    max_workers=_bounded_int_env("AI_RERANKER_WORKERS", 4, minimum=1, maximum=16),
    max_queue=_bounded_int_env("AI_RERANKER_QUEUE_SIZE", 8, minimum=1, maximum=64),
    thread_name_prefix="ret-rerank",
)


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
    actual_train_tokens = {
        token
        for token in re.findall(r"V[236]\d{2}(?=R\d|[^A-Z0-9]|$)", act_train)
    }
    train_matches = bool(
        req_train
        and act_train
        and (req_train == act_train or req_train in actual_train_tokens)
    )
    if train_matches:
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


class UnavailableReranker:
    """Failing implementation used when a requested integration is invalid."""

    name = "unavailable"

    def __init__(self, reason_code: str = "RERANKER_INITIALIZATION_FAILED") -> None:
        self.reason_code = str(reason_code or "RERANKER_INITIALIZATION_FAILED")[:64]

    def rank(self, query: str, candidates: Sequence[Mapping[str, Any]]) -> list[float]:
        raise RuntimeError(self.reason_code)


class RemoteSidecarReranker:
    """Invokes external BGE Reranker Sidecar via HTTP with strict timeouts."""

    name = "bge-reranker-sidecar"

    def __init__(self, endpoint: str | None = None, *, timeout_seconds: float = 0.30) -> None:
        self.endpoint = (
            endpoint or os.environ.get("AI_RERANKER_ENDPOINT", "http://127.0.0.1:8004/v1/rerank")
        ).strip()
        self.timeout_seconds = max(0.05, min(float(timeout_seconds), 5.0))
        from urllib.parse import urlparse
        if len(self.endpoint) > 2048:
            raise ValueError("Reranker endpoint is too long")
        parsed = urlparse(self.endpoint)
        try:
            host = (parsed.hostname or "").lower()
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Reranker endpoint is malformed") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Reranker endpoint must be an HTTP(S) URL without credentials or query parameters")
        allowed_hosts = {"127.0.0.1", "localhost", "::1", "reranker-sidecar", "netops"}
        extra = {h.strip().lower() for h in os.environ.get("AI_RERANKER_ALLOWED_HOSTS", "").split(",") if h.strip()}
        allowed_hosts.update(extra)
        if host not in allowed_hosts:
            raise ValueError("Reranker endpoint host is not in the configured allowlist")

    @staticmethod
    def _candidate_id(candidate: Mapping[str, Any]) -> str:
        for key in ("storage_document_id", "document_id", "chunk_id"):
            value = str(candidate.get(key) or "").strip()
            if value:
                if len(value) > 160:
                    raise ValueError("Reranker candidate ID is too long")
                return value
        raise ValueError("Reranker candidate is missing a stable ID")

    def rank(self, query: str, candidates: Sequence[Mapping[str, Any]]) -> list[float]:
        if not candidates:
            return []
        query_text = str(query or "").strip()
        if not query_text or len(query_text) > _RERANKER_MAX_QUERY_CHARS:
            raise ValueError("Reranker query is empty or too long")
        if len(candidates) > _RERANKER_MAX_CANDIDATES:
            raise ValueError("Reranker candidate count exceeds the limit")
        items = []
        candidate_ids: list[str] = []
        for c in candidates:
            cid = self._candidate_id(c)
            text = str(c.get("content") or "")
            if len(text) > _RERANKER_MAX_CANDIDATE_CHARS:
                raise ValueError("Reranker candidate text exceeds the limit")
            if cid in candidate_ids:
                raise ValueError("Reranker candidate IDs must be unique")
            candidate_ids.append(cid)
            items.append({"candidate_id": cid, "text": text})

        payload = {
            "query": query_text,
            "candidates": items,
            "top_n": len(items),
        }
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(data_bytes) > _RERANKER_MAX_PAYLOAD_BYTES:
            raise ValueError("Reranker request exceeds the payload limit")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        api_key = os.environ.get("BGE_API_KEY")
        if api_key:
            headers["X-Internal-Token"] = api_key

        req = urllib.request.Request(
            self.endpoint,
            data=data_bytes,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            raw_body = resp.read(_RERANKER_MAX_PAYLOAD_BYTES + 1)
        if len(raw_body) > _RERANKER_MAX_PAYLOAD_BYTES:
            raise ValueError("Reranker response exceeds the payload limit")
        body = json.loads(raw_body.decode("utf-8"))
        if not isinstance(body, Mapping):
            raise ValueError("Reranker response must be an object")

        results = body.get("results")
        if not isinstance(results, list) or len(results) != len(candidate_ids):
            raise ValueError("Reranker response count does not match the request")
        score_map: dict[str, float] = {}
        for result in results:
            if not isinstance(result, Mapping):
                raise ValueError("Reranker response item is invalid")
            result_id = str(result.get("candidate_id") or "").strip()
            if result_id not in candidate_ids or result_id in score_map:
                raise ValueError("Reranker response contains an unknown or duplicate candidate ID")
            try:
                score = float(result.get("score"))
            except (TypeError, ValueError) as exc:
                raise ValueError("Reranker response score is invalid") from exc
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError("Reranker response score is outside the valid range")
            score_map[result_id] = score
        if set(score_map) != set(candidate_ids):
            raise ValueError("Reranker response is missing a candidate ID")
        return [score_map[candidate_id] for candidate_id in candidate_ids]


class BoundedReranker:
    """Run a supplied reranker under a strict timeout and candidate/cost cap.

    The shared worker pool is finite and its queue is bounded.  A timed-out
    call can occupy one daemon worker until the dependency returns, but it can
    never create an unbounded number of request threads.
    """

    def __init__(
        self,
        reranker: Any = None,
        *,
        timeout_ms: int = 120,
        max_candidates: int = 20,
        mode: str | None = None,
    ) -> None:
        self.reranker = reranker or Reranker()
        self.timeout_ms = max(1, min(int(timeout_ms), 5000))
        self.max_candidates = max(1, min(int(max_candidates), 100))
        self.mode = str(
            mode if mode is not None else os.environ.get("AI_RERANKER_MODE", "active" if reranker else "legacy")
        ).lower()

    def _debug(self, *, stage: str, name: str, candidate_count: int, cost_units: int = 0, reason: str = "", latency_ms: int | None = None) -> dict[str, Any]:
        debug = {
            "stage": stage,
            "mode": self.mode,
            "name": name,
            "timeout_ms": self.timeout_ms,
            "candidate_count": candidate_count,
            "cost_units": cost_units,
        }
        if reason:
            debug["reason"] = reason
        if latency_ms is not None:
            debug["latency_ms"] = max(0, int(latency_ms))
        return debug

    def apply(self, query: str, candidates: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        bounded = list(candidates[: self.max_candidates])
        if not bounded:
            return [], {"stage": "skipped", "reason": "no_candidates", "cost_units": 0}

        # legacy 模式：对所有 reranker 均直接跳过重排计算，保留基础排序
        if self.mode == "legacy":
            return bounded, self._debug(
                stage="legacy_pass",
                name=str(getattr(self.reranker, "name", type(self.reranker).__name__)),
                candidate_count=len(bounded),
            )

        started = time.perf_counter()
        name = str(getattr(self.reranker, "name", type(self.reranker).__name__))
        try:
            future = _RERANKER_EXECUTOR.submit(self.reranker.rank, query, bounded)
        except BoundedExecutorSaturated:
            return bounded, self._debug(
                stage="degraded", name=name, candidate_count=len(bounded), reason="executor_saturated",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        try:
            values = future.result(timeout=self.timeout_ms / 1000.0)
        except FutureTimeout:
            future.cancel()
            return bounded, self._debug(
                stage="degraded", name=name, candidate_count=len(bounded), reason="timeout",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except Exception:
            return bounded, self._debug(
                stage="degraded", name=name, candidate_count=len(bounded), reason="reranker_error",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            return bounded, self._debug(
                stage="degraded", name=name, candidate_count=len(bounded), reason="score_count_mismatch",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        try:
            scores = [float(value) for value in values]
        except (TypeError, ValueError):
            return bounded, self._debug(
                stage="degraded", name=name, candidate_count=len(bounded), reason="score_invalid",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        if len(scores) != len(bounded):
            return bounded, self._debug(
                stage="degraded", name=name, candidate_count=len(bounded), reason="score_count_mismatch",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in scores):
            return bounded, self._debug(
                stage="degraded", name=name, candidate_count=len(bounded), reason="score_invalid",
                latency_ms=(time.perf_counter() - started) * 1000,
            )

        if self.mode == "shadow":
            # Shadow 模式：在影子副本上计算重排，保留原始 candidates 供生产返回
            shadow_candidates = [dict(item) for item in bounded]
            for item, score in zip(shadow_candidates, scores):
                item["reranker_score"] = round(score, 4)
                item["relevance_score"] = round(0.70 * float(item.get("relevance_score") or 0.0) + 0.30 * score, 4)
            shadow_candidates.sort(
                key=lambda item: (float(item.get("relevance_score") or 0.0), int(item.get("source_trust_rank") or 0)),
                reverse=True,
            )
            shadow_top_ids = [RemoteSidecarReranker._candidate_id(item) for item in shadow_candidates]
            baseline_top_ids = [RemoteSidecarReranker._candidate_id(item) for item in bounded]
            debug = self._debug(
                stage="shadow_observed", name=name, candidate_count=len(bounded), cost_units=len(bounded),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            debug.update({
                "shadow_top_ids": shadow_top_ids,
                "baseline_top_ids": baseline_top_ids,
                "order_changed": shadow_top_ids != baseline_top_ids,
            })
            return bounded, debug

        # active 模式：直接更新 bounded 并返回重排结果
        for item, score in zip(bounded, scores):
            item["reranker_score"] = round(score, 4)
            item["relevance_score"] = round(0.70 * float(item.get("relevance_score") or 0.0) + 0.30 * score, 4)
        bounded.sort(
            key=lambda item: (float(item.get("relevance_score") or 0.0), int(item.get("source_trust_rank") or 0)),
            reverse=True,
        )
        return bounded, self._debug(
            stage="applied", name=name, candidate_count=len(bounded), cost_units=len(bounded),
            latency_ms=(time.perf_counter() - started) * 1000,
        )


def build_minimal_context(
    primary: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    *,
    max_chars: int = 10000,
    max_chunks: int = 4,
) -> dict[str, Any]:
    """Select primary + parent + immediate neighbors under a hard budget."""

    primary_id = _text(primary.get("chunk_id"))
    parent_id = _text(primary.get("parent_chunk_id"))
    ordinal = int(primary.get("ordinal") or 0)
    by_id = {_text(item.get("chunk_id")): item for item in chunks if _text(item.get("chunk_id"))}
    selected_by_id: dict[str, Mapping[str, Any]] = {}
    for item in chunks:
        item_id = _text(item.get("chunk_id"))
        if item_id == primary_id or (parent_id and item_id == parent_id) or abs(int(item.get("ordinal") or 0) - ordinal) <= 1:
            selected_by_id[item_id or f"__anonymous_{len(selected_by_id)}"] = item
    if primary_id and primary_id not in selected_by_id:
        selected_by_id[primary_id] = primary
    selected = list(selected_by_id.values())
    selected.sort(key=lambda item: (0 if _text(item.get("chunk_id")) == primary_id else 1, int(item.get("ordinal") or 0), _text(item.get("chunk_id"))))
    parts: list[str] = []
    ids: list[str] = []
    used = 0
    for item in selected[: max(1, min(int(max_chunks), 20))]:
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

