"""Metadata-first Retriever for the V1 knowledge projection.

Eligibility is decided in SQL from structured document metadata.  Embeddings
and lexical signals only rank the already eligible candidate set; they can
never make an incompatible platform or document category eligible.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace as _dataclass_replace
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)
_APPLICABILITY_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

# ── V2 retrieval engine settings (read per call so operators and tests can
# switch without a restart) ─────────────────────────────────────────────────
_RETRIEVAL_ENGINES = {"v1", "shadow", "v2"}
_RRF_K = 60


def _retrieval_engine() -> str:
    """``v1`` (default), ``shadow`` (serve V1, compare V2) or ``v2``."""
    value = str(os.environ.get("AI_RETRIEVAL_ENGINE", "v1") or "v1").strip().lower()
    return value if value in _RETRIEVAL_ENGINES else "v1"


_VECTOR_SOURCES = {"legacy", "semantic"}




# ── shadow comparison runtime ─────────────────────────────────────────────
#
# AI_RETRIEVAL_SHADOW_MODE        async (default): V2 runs on one background
#                                 worker after V1 has answered, so the user
#                                 never waits for it; sync: inline (tests,
#                                 one-off diagnosis).
# AI_RETRIEVAL_SHADOW_SAMPLE_RATE share of searches compared (0..1, default 1).
# AI_RETRIEVAL_SHADOW_MAX_PENDING queued comparisons beyond which new ones are
#                                 dropped (default 16): shadow work must never
#                                 build up behind real traffic.
# AI_RETRIEVAL_SHADOW_STORE_QUERY 1 also stores a sanitised 200-char query
#                                 preview (default 0: hash only).
# AI_RETRIEVAL_SHADOW_RETENTION_DAYS rows older than this are pruned (30).

_SHADOW_LOCK = threading.Lock()
_SHADOW_STATE: Dict[str, Any] = {"executor": None, "pending": 0, "dropped": 0, "recorded": 0, "record_failures": 0}
_SHADOW_PRUNE_EVERY = 200


def _shadow_mode() -> str:
    value = str(os.environ.get("AI_RETRIEVAL_SHADOW_MODE", "async") or "async").strip().lower()
    return value if value in {"async", "sync"} else "async"


def _shadow_float(name: str, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def _shadow_executor() -> ThreadPoolExecutor:
    with _SHADOW_LOCK:
        executor = _SHADOW_STATE["executor"]
        if executor is None:
            # One worker: at most one extra pooled DB connection, and shadow
            # traffic cannot compete with user searches for CPU.
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-shadow")
            _SHADOW_STATE["executor"] = executor
        return executor


def shadow_runtime_status() -> Dict[str, Any]:
    with _SHADOW_LOCK:
        return {key: value for key, value in _SHADOW_STATE.items() if key != "executor"}


def wait_for_shadow_jobs(timeout: float = 30.0) -> bool:
    """Block until queued shadow comparisons finish (tests, benchmarks)."""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        with _SHADOW_LOCK:
            if not _SHADOW_STATE["pending"]:
                return True
        time.sleep(0.02)
    return False


def shutdown_shadow_executor(wait: bool = False) -> None:
    with _SHADOW_LOCK:
        executor = _SHADOW_STATE["executor"]
        _SHADOW_STATE["executor"] = None
    if executor is not None:
        executor.shutdown(wait=wait, cancel_futures=True)

def _vector_source() -> str:
    """Vector signal for the V2 engine: ``legacy`` (embedding_vector, default)
    or ``semantic`` (bge-m3 embedding_v2).  V1 always uses legacy."""
    value = str(os.environ.get("AI_RETRIEVAL_VECTOR_SOURCE", "legacy") or "legacy").strip().lower()
    return value if value in _VECTOR_SOURCES else "legacy"


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


_PGVECTOR_VERSION: tuple[int, ...] | None = None
_PGVECTOR_LOCK = threading.Lock()


_TRGM_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]*[A-Za-z0-9]")
_TRGM_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]{2,}")


def _trgm_terms(query: str, limit: int = 6) -> list[str]:
    """Distinctive fuzzy-match terms: identifiers with digits or separators,
    and CJK runs.  Plain Latin words are covered by the FTS leg."""
    text = str(query or "")[:512]
    terms: list[str] = []
    for token in _TRGM_IDENTIFIER_RE.findall(text):
        if len(token) >= 3 and re.search(r"\d|[-_./:]", token):
            terms.append(token.lower())
    for run in _TRGM_CJK_RE.findall(text):
        terms.append(run[:32])
    unique = list(dict.fromkeys(terms))
    unique.sort(key=len, reverse=True)
    return unique[:limit]


def _pgvector_version(cursor) -> tuple[int, ...]:
    """Installed pgvector version, read once per process."""
    global _PGVECTOR_VERSION
    if _PGVECTOR_VERSION is not None:
        return _PGVECTOR_VERSION
    with _PGVECTOR_LOCK:
        if _PGVECTOR_VERSION is None:
            try:
                row = cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
                _PGVECTOR_VERSION = tuple(int(part) for part in re.findall(r"\d+", str((row or [""])[0] or "")))[:3]
            except Exception:
                _PGVECTOR_VERSION = ()
    return _PGVECTOR_VERSION


def _acl_principals(request: "RetrievalRequest") -> list[str]:
    """Principals of the caller, encoded like ``ai_document.acl_principals``.

    Mirrors ``rag_policy.document_is_visible``: values are compared as
    strings without stripping, exactly like the Python policy.
    """
    principals = ["*"]
    if request.user_id:
        principals.append(f"u:{request.user_id}")
    principals.extend(f"r:{role}" for role in (request.roles or []) if str(role))
    principals.extend(f"s:{site}" for site in (request.site_ids or []) if str(site))
    return principals

from database.core import get_db_connection
from ai.providers.embedding import embedding_provider
from ai.security.sanitizer import sanitize_text
from ai.services.rag_policy import document_is_visible, trust_rank
from ai.services.knowledge_metadata import canonical_cli_platform, canonical_feature, canonical_vendor
from ai.schemas.knowledge import KnowledgeQueryPlan
from ai.services.knowledge_service import _directory_filter_sql
from ai.services.product_resolver import product_resolver
from ai.services.retrieval_contract import (
    score_weights,
    BoundedReranker,
    Reranker,
    UnavailableReranker,
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
    knowledge_scope: Optional[str] = None
    directory_path: Optional[str] = None
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
        if values.get("cli_platform"):
            values["cli_platform"] = canonical_cli_platform(values["cli_platform"])
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
    # These are content-level signals, not metadata labels.  They are used
    # only when an official broad document has a legacy/inferred feature tag;
    # an explicit reviewed feature binding remains authoritative.
    _FEATURE_CONTENT_PATTERNS = {
        "vlan": (
            r"(?<![a-z0-9])vlan(?![a-z0-9])",
            r"\bswitchport\s+(?:mode\s+)?(?:access|trunk)\b",
            r"\b(?:allowed|native|private[- ]?)\s*vlan\b",
            r"\binterface\s+vlan\d*\b",
            r"\bport\s+(?:link-type\s+)?(?:access|trunk)\b",
            r"\bport\s+(?:trunk\s+)?(?:allow-pass|permit)\s+vlan\b",
            r"虚拟局域网",
        ),
        "access_port": (
            r"\bswitchport\s+(?:mode\s+)?access\b",
            r"\bswitchport\s+access\s+vlan\b",
            r"\bport\s+(?:link-type\s+)?access\b",
            r"\bport\s+(?:default|access)\s+vlan\b",
            r"\baccess[- ]port\b",
            r"接入口|接入端口",
        ),
        "port_security": (
            r"\bswitchport\s+port[- ]security\b",
            r"\bport[- ]security\b",
            r"\bmax(?:imum)?[- ]mac(?:[- ]count|[- ]num(?:ber)?)?\b",
            r"端口安全",
        ),
        "trunk": (
            r"\bswitchport\s+(?:mode\s+)?trunk\b",
            r"\bport\s+link-type\s+trunk\b",
            r"\bport\s+trunk\s+(?:allow-pass|permit)\s+vlan\b",
            r"\btrunk(?:ing)?\b",
            r"\ballowed\s+vlan\b",
            r"中继端口|trunk端口",
        ),
        "ospf": (r"(?<![a-z0-9])ospf(?![a-z0-9])",),
        "bgp": (r"(?<![a-z0-9])bgp(?![a-z0-9])",),
        "isis": (r"(?<![a-z0-9])isis(?![a-z0-9])",),
        "arp": (r"(?<![a-z0-9])arp(?![a-z0-9])",),
        "stp": (r"(?<![a-z0-9])stp(?![a-z0-9])", r"\bspanning[- ]tree\b"),
        "mstp": (r"(?<![a-z0-9])mstp(?![a-z0-9])",),
        "lacp": (
            r"(?<![a-z0-9])lacp(?![a-z0-9])",
            r"\beth[- ]trunk\b",
            r"\betherchannel\b",
            r"\bbridge[- ]aggregation\b",
        ),
        "lldp": (r"(?<![a-z0-9])lldp(?![a-z0-9])",),
        "vrrp": (r"(?<![a-z0-9])vrrp(?![a-z0-9])",),
        "hsrp": (
            r"(?<![a-z0-9])hsrp(?![a-z0-9])",
            r"\bstandby\s+\d+\s+(?:ip|priority|preempt)\b",
        ),
        "evpn": (r"(?<![a-z0-9])evpn(?![a-z0-9])",),
        "vxlan": (r"(?<![a-z0-9])vxlan(?![a-z0-9])",),
        "snmp": (r"(?<![a-z0-9])snmp(?:v3)?(?![a-z0-9])",),
        "ntp": (r"(?<![a-z0-9])ntp(?![a-z0-9])",),
        "ssh": (r"(?<![a-z0-9])(?:ssh|stelnet)(?![a-z0-9])",),
        "acl": (r"(?<![a-z0-9])acl(?![a-z0-9])", r"\baccess[- ]control list\b"),
        "loopback": (r"(?<![a-z0-9])loopback(?![a-z0-9])", r"环回接口|环回口"),
        "static_route": (r"static[- ]route", r"ip\s+route-static", r"静态路由"),
        "qos": (r"(?<![a-z0-9])qos(?![a-z0-9])", r"服务质量"),
    }

    def __init__(
        self,
        *,
        reranker: Any = None,
        cache_enabled: bool | None = None,
        candidate_pool_size: int | None = None,
        connection_factory: Any = None,
        embedder: Any = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._embedder = embedder
        self.last_debug: Dict[str, Any] = {}
        pool_size = int(
            candidate_pool_size
            if candidate_pool_size is not None
            else os.environ.get("AI_RETRIEVAL_CANDIDATE_POOL_SIZE", "30")
        )
        self.candidate_pool_size = max(5, min(pool_size, 100))
        requested_reranker_mode = str(os.environ.get("AI_RERANKER_MODE") or ("active" if reranker else "legacy")).lower().strip()
        reranker_mode = requested_reranker_mode
        self.reranker_config: Dict[str, Any] = {
            "requested_mode": requested_reranker_mode,
            "effective_mode": requested_reranker_mode,
            "status": "ready",
            "error_code": None,
        }
        if reranker_mode not in {"legacy", "shadow", "active"}:
            reranker_mode = "legacy"
            self.reranker_config.update({
                "effective_mode": reranker_mode,
                "status": "degraded",
                "error_code": "RERANKER_MODE_INVALID",
            })
        if reranker is None:
            if reranker_mode in ("shadow", "active"):
                try:
                    from ai.services.retrieval_contract import RemoteSidecarReranker
                    endpoint = os.environ.get("AI_RERANKER_ENDPOINT", "http://127.0.0.1:8004/v1/rerank")
                    timeout_ms = int(os.environ.get("AI_RERANKER_TIMEOUT_MS", "300"))
                    reranker = RemoteSidecarReranker(endpoint=endpoint, timeout_seconds=timeout_ms / 1000.0)
                except Exception:
                    reranker = UnavailableReranker()
                    self.reranker_config.update({
                        "status": "degraded",
                        "error_code": "RERANKER_ENDPOINT_INVALID",
                    })
            else:
                reranker = Reranker()

        if isinstance(reranker, BoundedReranker):
            self.reranker = reranker
            self.reranker.max_candidates = max(self.reranker.max_candidates, self.candidate_pool_size)
        else:
            self.reranker = BoundedReranker(
                reranker,
                max_candidates=self.candidate_pool_size,
                timeout_ms=int(os.environ.get("AI_RERANKER_TIMEOUT_MS", "300")),
                mode=reranker_mode,
            )
        self.reranker_config.update({
            "effective_mode": str(getattr(self.reranker, "mode", reranker_mode)),
            "name": str(getattr(getattr(self.reranker, "reranker", self.reranker), "name", type(self.reranker).__name__)),
        })
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

    @classmethod
    def _feature_content_matches(cls, feature: Any, text: Any) -> bool:
        """Return whether *text* contains evidence for a canonical feature.

        The document's ``feature`` column is deliberately not included here:
        this helper exists to detect a bad document-level label, so reusing the
        same label would make the guard circular.  Unknown features fall back
        to a conservative word-boundary match.
        """

        canonical = canonical_feature(feature)
        value = str(text or "")
        if not canonical or not value:
            return False
        patterns = cls._FEATURE_CONTENT_PATTERNS.get(canonical)
        if patterns:
            return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)
        escaped = re.escape(canonical.replace("_", " "))
        return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", value, flags=re.IGNORECASE))

    @classmethod
    def _feature_scope_is_eligible(
        cls,
        requested_feature: Any,
        metadata: Dict[str, Any] | None,
        *,
        content: Any = "",
        section: Any = "",
        document_name: Any = "",
        document_source: Any = "",
        knowledge_source_type: Any = "",
    ) -> bool:
        """Reject legacy broad-source labels with no local feature evidence.

        SQL still owns the normal metadata hard filter.  This second boundary
        is intentionally narrow: it applies to official command/configuration
        sources whose feature tag was inferred or predates the provenance
        marker.  A reviewer-provided ``feature_source=explicit`` binding is
        accepted even when the command text is terse.
        """

        requested = canonical_feature(requested_feature)
        if not requested:
            return True
        metadata = metadata if isinstance(metadata, dict) else {}
        actual = canonical_feature(metadata.get("feature"))
        if actual and actual != requested:
            return False
        # A missing chunk projection is a legacy compatibility case.  The
        # parent document's SQL feature predicate has already been applied.
        if not actual:
            return True

        source_kind = str(metadata.get("source_kind") or "").strip().lower()
        source_type = str(
            metadata.get("source_type")
            or knowledge_source_type
            or ""
        ).strip().lower()
        broad_source = source_kind in {"command_reference", "configuration_guide"}
        broad_source = broad_source or source_type in {"official_url", "official_local", "official_vendor"}
        if not broad_source:
            return True
        if str(metadata.get("feature_source") or "").strip().lower() == "explicit":
            return True

        # A title/URL binding can justify retaining a document-level label in
        # the migration, but it cannot make every chunk in that document
        # eligible.  Require evidence in the chunk's section/body so a
        # multi-feature troubleshooting or command-reference page cannot leak
        # an unrelated section into a narrow answer.
        return cls._feature_content_matches(
            requested,
            " ".join(str(value or "") for value in (section, content)),
        )

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

    _column_cache = threading.local()

    @classmethod
    def _table_columns(cls, cursor, table: str) -> set[str]:
        # Within one search the same tables are probed several times (rows,
        # accelerator scores, V2 legs); probe each table once per search.
        cache = getattr(cls._column_cache, "tables", None)
        if cache is not None and table in cache:
            return cache[table]
        cursor.execute(f"SELECT * FROM {table} WHERE 1 = 0")
        columns = {str(description[0]) for description in (cursor.description or [])}
        if cache is not None:
            cache[table] = columns
        return columns

    @staticmethod
    def _normalise_os_family(value: Any) -> str:
        """Compare OS-family aliases without weakening platform boundaries."""

        return re.sub(r"[\s_-]+", "", str(value or "").strip().lower())

    def _filter_sql(self, request: RetrievalRequest, columns: set[str]) -> tuple[str, list[Any]]:
        # Stored tenant labels describe provenance only in single-organization
        # mode. Source trust, lifecycle status, explicit filters and document
        # ACL checks below continue to govern which records may be returned.
        where = ["d.status = ?"]
        params: list[Any] = [request.status]
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
            category_val = str(request.document_category).strip().lower()
            if category_val == "command":
                # Official command references are currently projected as
                # configuration documents because executable snippets are
                # published together with configuration semantics. Keep a
                # dedicated command category preferred when present, while
                # allowing the reviewed configuration projection to satisfy
                # a command-reference query.
                where.append("LOWER(d.document_category) IN (?, ?, ?)")
                params.extend(["command", "configuration", "cli_output"])
            elif category_val == "cli_output":
                where.append("LOWER(d.document_category) IN (?, ?, ?)")
                params.extend(["cli_output", "configuration", "command"])
            elif category_val == "configuration":
                where.append("LOWER(d.document_category) IN (?, ?)")
                params.extend(["configuration", "command"])
            elif category_val == "troubleshooting":
                # A troubleshooting request may use a read-only CLI output
                # as evidence, but only after the query identifies a vendor,
                # product, OS or CLI family.  Without any identity, returning
                # every platform's output turns an ambiguous request into a
                # misleading answer (and defeats the no-match boundary).
                identity_scoped = any(
                    getattr(request, field, None)
                    for field in (
                        "vendor",
                        "product_family",
                        "product_series",
                        "product_model",
                        "os_family",
                        "os_generation",
                        "software_train",
                        "software_release",
                        "cli_platform",
                    )
                )
                if identity_scoped:
                    where.append("LOWER(d.document_category) IN (?, ?)")
                    params.extend(["troubleshooting", "cli_output"])
                else:
                    where.append("LOWER(d.document_category) = LOWER(?)")
                    params.append(request.document_category)
            else:
                where.append("LOWER(d.document_category) = LOWER(?)")
                params.append(request.document_category)

        scope_types = {
            "official": ("official_vendor", "official_url", "official_local", "official_template"),
            "enterprise": ("internal_sop", "internal_standard", "case", "user_document", "sample"),
        }.get(str(request.knowledge_scope or "").strip().lower())
        if scope_types:
            if "knowledge_source_type" not in columns:
                where.append("0 = 1")
            else:
                placeholders = ", ".join("?" for _ in scope_types)
                where.append(f"d.knowledge_source_type IN ({placeholders})")
                params.extend(scope_types)

        if request.directory_path:
            directory_path = KnowledgeQueryPlan.model_validate(
                {"directory_path": request.directory_path}
            ).directory_path
            directory_sql, directory_params = _directory_filter_sql(
                directory_path,
                columns,
            )
            where.append(directory_sql)
            params.extend(directory_params)
        for column, value in scalar_filters:
            if value is not None and column in columns:
                if column == "os_family":
                    # Catalog imports use both ``IOS XE`` and ``IOS-XE``.
                    # Separator normalization preserves the exact family
                    # match while avoiding a false no-match on formatting.
                    family_value = self._normalise_os_family(value)
                    generation = self._normalise_os_family(request.os_generation)
                    generation_suffix = "".join(re.findall(r"\d+", generation))
                    if generation_suffix and family_value and not family_value.endswith(generation_suffix):
                        # Some legacy imports put the generation in
                        # ``os_family`` (for example ``Comware 7``) while the
                        # request contract carries it in ``os_generation``.
                        # Match that explicit combined value without treating
                        # an unknown family/version as compatible.
                        where.append(
                            "REPLACE(REPLACE(REPLACE(LOWER(COALESCE(d.os_family, '')), '-', ''), ' ', ''), '_', '') IN (?, ?)"
                        )
                        params.extend([family_value, f"{family_value}{generation_suffix}"])
                    else:
                        where.append(
                            "REPLACE(REPLACE(REPLACE(LOWER(COALESCE(d.os_family, '')), '-', ''), ' ', ''), '_', '') = ?"
                        )
                        params.append(family_value)
                elif column == "os_generation":
                    generation_value = str(value)
                    family_value = self._normalise_os_family(request.os_family)
                    generation = self._normalise_os_family(value)
                    generation_suffix = "".join(re.findall(r"\d+", generation))
                    if family_value and generation_suffix:
                        # Legacy official rows may encode the generation in
                        # ``os_family`` (Comware 7 / VRP8) and leave the
                        # dedicated generation column empty. Keep the
                        # explicit version boundary in force while accepting
                        # that storage shape.
                        where.append(
                            "(LOWER(COALESCE(d.os_generation, '')) = LOWER(?) OR "
                            "REPLACE(REPLACE(REPLACE(LOWER(COALESCE(d.os_family, '')), '-', ''), ' ', ''), '_', '') = ?)"
                        )
                        params.extend([generation_value, f"{family_value}{generation_suffix}"])
                    else:
                        where.append(f"LOWER(COALESCE(d.{column}, '')) = LOWER(?)")
                        params.append(generation_value)
                elif column == "software_train" and re.fullmatch(r"V[236]\d{2}", str(value).strip(), re.IGNORECASE):
                    # A bare Huawei-style train token (for example V200) is
                    # often projected from reviewed documents as
                    # ``V200R023 / V300R024``. Keep the train boundary hard,
                    # but allow the documented release-qualified form rather
                    # than requiring a lossy exact-string match. The R-suffix
                    # and separator guards prevent V200 from matching V2000
                    # or a different train such as V300.
                    train_value = str(value).strip().lower()
                    if "metadata_json" in columns:
                        where.append(
                            "(LOWER(COALESCE(d.software_train, '')) = LOWER(?) OR "
                            "LOWER(COALESCE(d.software_train, '')) LIKE LOWER(?) OR "
                            "LOWER(COALESCE(d.software_train, '')) LIKE LOWER(?) OR "
                            "LOWER(COALESCE(d.software_train, '')) LIKE LOWER(?) OR "
                            "COALESCE(d.metadata_json -> 'applicable_software_trains', '[]'::jsonb) "
                            "@> jsonb_build_array(?))"
                        )
                        params.extend([
                            train_value,
                            f"{train_value}r%",
                            f"{train_value}/%",
                            f"{train_value} /%",
                            str(value),
                        ])
                    else:
                        where.append(
                            "(LOWER(COALESCE(d.software_train, '')) = LOWER(?) OR "
                            "LOWER(COALESCE(d.software_train, '')) LIKE LOWER(?) OR "
                            "LOWER(COALESCE(d.software_train, '')) LIKE LOWER(?) OR "
                            "LOWER(COALESCE(d.software_train, '')) LIKE LOWER(?))"
                        )
                        params.extend([
                            train_value,
                            f"{train_value}r%",
                            f"{train_value}/%",
                            f"{train_value} /%",
                        ])
                else:
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
                    prefix_meta_clause = (
                        f" OR LOWER(CAST(d.metadata_json AS TEXT)) LIKE LOWER(?)"
                        if model_prefix
                        else ""
                    )
                    where.append(f"({scalar}{prefix_clause} OR ({array_expr}){prefix_meta_clause})")
                    params.append(scalar_value)
                    if model_prefix and column in columns:
                        params.append(f"{value_text}-%")
                    params.extend([scalar_value] * len(array_keys))
                    if model_prefix:
                        params.append(f"%{value_text}%")
            else:
                where.append(scalar)
                if column in columns:
                    params.append(scalar_value)

        if request.cli_platform and "cli_platform" in columns:
            # Never allow platform=all to satisfy a concrete command,
            # configuration, or CLI-output request.  Neutral documents are
            # represented by NULL, not the string all.
            platform_value = canonical_cli_platform(request.cli_platform)
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
            key_str = str(key or "").strip()
            if not _APPLICABILITY_KEY_RE.fullmatch(key_str):
                raise ValueError("Invalid applicability filter key")
            values = requested if isinstance(requested, (list, tuple, set)) else [requested]
            for value in values:
                if value is None or "metadata_json" not in columns:
                    continue
                where.append("COALESCE(d.metadata_json -> ?, '[]'::jsonb) @> jsonb_build_array(?)")
                params.extend([key_str, str(value)])
        return " AND ".join(where), params

    def _open_connection(self):
        factory = self._connection_factory or get_db_connection
        return factory()

    def _active_embedder(self):
        return self._embedder or embedding_provider

    def _query_rows(
        self,
        request: RetrievalRequest,
        vector_top_n: int,
    ) -> tuple[list[Any], int, Dict[str, Any]]:
        with self._open_connection() as conn:
            cursor = conn.cursor()
            columns = self._table_columns(cursor, "ai_document")
            chunk_columns = self._table_columns(cursor, "ai_document_chunk")
            where_sql, params = self._filter_sql(request, columns)
            cursor.execute(
                f"SELECT COUNT(*) FROM ai_document d WHERE {where_sql}",
                params,
            )
            document_count = int((cursor.fetchone() or [0])[0] or 0)
            # Explicit product/category constraints are safety boundaries, not
            # ranking hints. A no-match must not silently fetch another platform
            # or a CLI-output document as configuration evidence.
            document_category_expr = "d.document_category" if "document_category" in columns else "NULL"
            cli_platform_expr = "d.cli_platform" if "cli_platform" in columns else "NULL"
            semantic_document_id_expr = "d.document_id" if "document_id" in columns else "NULL"
            source_expr = "d.source" if "source" in columns else "NULL"
            source_type_expr = "d.knowledge_source_type" if "knowledge_source_type" in columns else "NULL"
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
                           d.id, d.name, {source_expr}, {source_type_expr}, {document_version_expr}, d.vendor, d.platform, d.tenant_id,
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
        *,
        query_vector: Optional[Sequence[float]] = None,
    ) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
        """Run bounded PostgreSQL FTS/trigram/vector scores.

        The status and metadata query has already produced the IDs; every
        accelerator query is bounded to that candidate set. Per-document ACLs
        are enforced before candidate chunks enter the user-visible result.
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
            with self._open_connection() as conn:
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
                        active_embedder = self._active_embedder()
                        resolved_vector = (
                            list(query_vector)
                            if query_vector is not None
                            else (
                                active_embedder.embed_query(request.query)
                                if hasattr(active_embedder, "embed_query")
                                else active_embedder.embed_text(request.query)
                            )
                        )
                        vector_literal = "[" + ",".join(str(float(value)) for value in resolved_vector) + "]"
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
        try:
            max_chunks = int(os.environ.get("AI_RAG_MAX_CONTEXT_CHUNKS_PER_DOCUMENT", "4"))
        except (TypeError, ValueError):
            max_chunks = 4
        context = build_minimal_context(primary, chunks, max_chars=max_chars, max_chunks=max_chunks)
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

    @staticmethod
    def _embed_query(embedder: Any, query: str) -> list[float]:
        try:
            vector = embedder.embed_query(query) if hasattr(embedder, "embed_query") else embedder.embed_text(query)
            return list(vector or [])
        except Exception:
            return []

    def _candidates_v1(
        self,
        request: RetrievalRequest,
        candidate_hint: int,
        query_vector: Sequence[float],
    ) -> tuple[list[Any], Dict[str, Any], Dict[str, Dict[str, float]]]:
        """V1: every metadata-eligible chunk, scored in Python."""
        rows, _document_count, debug = self._query_rows(request, candidate_hint)
        accelerator_scores, accelerator_debug = self._native_accelerator_scores(
            request,
            [row[0] for row in rows],
            query_vector=query_vector if query_vector else None,
        )
        debug.update(accelerator_debug)
        debug["retrieval_engine"] = "v1"
        return rows, debug, accelerator_scores

    def _candidates_v2(
        self,
        request: RetrievalRequest,
        candidate_hint: int,
        query_vector: Sequence[float],
    ) -> tuple[list[Any], Dict[str, Any], Dict[str, Dict[str, float]]]:
        """V2: indexed recall in PostgreSQL; small candidate sets stay exact.

        When the metadata/ACL filters leave at most
        AI_RETRIEVAL_V2_EXACT_THRESHOLD chunks, scoring all of them is cheap
        and exact, so the V1 path is used.  Larger sets go through the
        bounded FTS + trigram + vector legs fused with RRF.
        """
        semantic = self._semantic_query(request) if _vector_source() == "semantic" else None
        result = self._query_rows_v2(request, query_vector, semantic=semantic)
        if result is None:
            rows, debug, scores = self._candidates_v1(request, candidate_hint, query_vector)
            debug["retrieval_engine"] = "v2_exact_small_set"
            if semantic is not None:
                self._apply_semantic_scores(rows, scores, debug, semantic)
            result = (rows, debug, scores)
        rows, debug, scores = result
        debug["vector_source"] = (
            "semantic" if semantic and semantic.get("vector") else
            "legacy_fallback" if semantic is not None else "legacy"
        )
        if semantic is not None and not semantic.get("vector"):
            debug.setdefault("capability_degraded", []).append(semantic.get("error_code") or "SEMANTIC_QUERY_EMBEDDING_UNAVAILABLE")
        return rows, debug, scores

    def _semantic_query(self, request: RetrievalRequest) -> Dict[str, Any]:
        """Query vector + column contract for the semantic vector source.

        Returns ``{"vector": [], "error_code": ...}`` when unavailable; the
        caller then keeps the legacy vector signal for *all* rows so that
        scores from two different models are never mixed.
        """
        from ai.providers.embedding import EmbeddingProviderError, semantic_embedding_provider

        try:
            provider = semantic_embedding_provider()
        except EmbeddingProviderError:
            return {"vector": [], "error_code": "SEMANTIC_PROVIDER_MISCONFIGURED"}
        if provider is None:
            return {"vector": [], "error_code": "SEMANTIC_PROVIDER_DISABLED"}
        try:
            vector = list(provider.embed_query(str(request.query or "")) or [])
        except Exception:
            return {"vector": [], "error_code": "SEMANTIC_QUERY_EMBEDDING_UNAVAILABLE"}
        return {
            "vector": vector,
            "model": str(getattr(provider, "model_id", "")),
            "version": str(getattr(provider, "version", "")),
            "error_code": None,
        }

    def _semantic_column_cast(self, cursor) -> str | None:
        cache = getattr(self._column_cache, "tables", None)
        if cache is not None and "__embedding_v2_type" in cache:
            return cache["__embedding_v2_type"]
        from ai.services.semantic_vectors import semantic_column_type

        column_type = semantic_column_type(cursor)
        cast = column_type.split("(")[0] if column_type else None
        if cache is not None:
            cache["__embedding_v2_type"] = cast
        return cast

    def _apply_semantic_scores(
        self,
        rows: Sequence[Any],
        scores: Dict[str, Dict[str, float]],
        debug: Dict[str, Any],
        semantic: Dict[str, Any],
    ) -> None:
        """Replace the vector signal of every candidate row with bge-m3 cosine.

        Rows without a current semantic vector get 0 -- never the legacy
        score, because the two models' similarities are not comparable.
        """
        if not semantic.get("vector") or not rows:
            return
        ids = [str(row[0]) for row in rows]
        computed: Dict[str, float] = {}
        try:
            with self._open_connection() as conn:
                cursor = conn.cursor()
                cast = self._semantic_column_cast(cursor)
                if cast is None:
                    semantic["vector"] = []
                    semantic["error_code"] = "SEMANTIC_COLUMN_MISSING"
                    for values in scores.values():
                        values.pop("vector", None)
                    return
                literal = "[" + ",".join(str(float(value)) for value in semantic["vector"]) + "]"
                for start in range(0, len(ids), 1000):
                    part = ids[start:start + 1000]
                    placeholders = ", ".join("?" for _ in part)
                    for chunk_id, similarity in cursor.execute(
                        f"SELECT c.id, 1 - (c.embedding_v2 <=> CAST(? AS {cast})) FROM ai_document_chunk c "
                        f"WHERE c.id IN ({placeholders}) AND c.embedding_v2 IS NOT NULL "
                        "AND c.embedding_v2_model = ? AND c.embedding_v2_version = ?",
                        [literal, *part, semantic["model"], semantic["version"]],
                    ).fetchall():
                        computed[str(chunk_id)] = max(0.0, min(1.0, float(similarity or 0.0)))
        except Exception:
            logger.warning("Semantic rescoring failed; falling back to the legacy vector signal")
            semantic["vector"] = []
            semantic["error_code"] = "SEMANTIC_RESCORE_FAILED"
            # The vector leg may already have stored bge-m3 similarities;
            # drop them so the legacy fallback never mixes two models.
            for values in scores.values():
                values.pop("vector", None)
            debug["vector_stage"] = "degraded_semantic_rescore_failed"
            return
        for chunk_id in ids:
            scores.setdefault(chunk_id, {})["vector"] = computed.get(chunk_id, 0.0)
        debug["semantic_scored_chunks"] = len(computed)
        debug["semantic_missing_chunks"] = len(ids) - len(computed)
        debug["vector_stage"] = "native_pgvector_semantic"

    @staticmethod
    def _row_select_list(columns: set[str], chunk_columns: set[str], embedding_expr: str = "c.embedding") -> str:
        """Same column order as ``_query_rows`` so ``_rank_rows`` can unpack it."""
        def expr(name: str, available: set[str], alias: str, fallback: str = "NULL") -> str:
            return f"{alias}.{name}" if name in available else fallback

        return ", ".join([
            "c.id", "c.content", embedding_expr, "c.metadata_json", "c.section",
            "d.id", "d.name", expr("source", columns, "d"), expr("knowledge_source_type", columns, "d"),
            expr("version", columns, "d"), "d.vendor", "d.platform", "d.tenant_id",
            "d.acl_json", "d.source_trust_level",
            expr("document_category", columns, "d"), expr("cli_platform", columns, "d"),
            expr("document_id", columns, "d"),
            expr("software_train", columns, "d"), expr("software_release", columns, "d"),
            "COALESCE(c.is_retrieval_candidate, 1)" if "is_retrieval_candidate" in chunk_columns else "1",
            "c.chunk_role" if "chunk_role" in chunk_columns else "'legacy'",
            expr("parent_chunk_id", chunk_columns, "c"),
            "COALESCE(c.ordinal, 0)" if "ordinal" in chunk_columns else "NULL",
            expr("embedding_model", chunk_columns, "c"),
            expr("embedding_dimensions", chunk_columns, "c"),
        ])

    @staticmethod
    def _stored_tsv_ready(cursor, chunk_columns) -> bool:
        """m0332 column is used only once its GIN index is built and valid.

        ``fts-index`` builds the index only after every row is filled, and
        the trigger keeps new rows current, so a valid index means the
        column is complete.  AI_RETRIEVAL_FTS_SOURCE=expression forces the
        m0138 expression index (rollback / comparison).
        """
        if "search_tsv" not in chunk_columns:
            return False
        if str(os.environ.get("AI_RETRIEVAL_FTS_SOURCE", "auto")).strip().lower() == "expression":
            return False
        try:
            row = cursor.execute(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = ?",
                ["ix_ai_chunk_search_tsv"],
            ).fetchone()
        except Exception:
            return False
        return bool(row and row[0])

    def _query_rows_v2(
        self,
        request: RetrievalRequest,
        query_vector: Sequence[float],
        *,
        semantic: Dict[str, Any] | None = None,
    ) -> tuple[list[Any], Dict[str, Any], Dict[str, Dict[str, float]]] | None:
        """Bounded hybrid recall; returns None when the exact path should run."""
        leg_limit = _env_int("AI_RETRIEVAL_V2_LEG_LIMIT", 50, 10, 200)
        fused_limit = _env_int("AI_RETRIEVAL_V2_FUSED_LIMIT", 150, 10, 500)
        exact_threshold = _env_int("AI_RETRIEVAL_V2_EXACT_THRESHOLD", 2000, 0, 1_000_000)
        query_text = str(request.query or "")
        debug: Dict[str, Any] = {
            "retrieval_engine": "v2_indexed",
            "index_source": "v1",
            "capability_degraded": [],
            "v2_legs": {},
        }
        with self._open_connection() as conn:
            cursor = conn.cursor()
            columns = self._table_columns(cursor, "ai_document")
            chunk_columns = self._table_columns(cursor, "ai_document_chunk")
            where_sql, params = self._filter_sql(request, columns)
            scope = f"WHERE {where_sql}"
            scope_params: list[Any] = list(params)
            if "is_retrieval_candidate" in chunk_columns:
                scope += " AND COALESCE(c.is_retrieval_candidate, 1) = 1"
            if "acl_principals" in columns:
                # NULL means "not projected yet": let it through; the Python
                # policy below still decides visibility for every row.
                scope += " AND (d.acl_principals IS NULL OR d.acl_principals && CAST(? AS TEXT[]))"
                scope_params.append(_acl_principals(request))
                debug["acl_stage"] = "sql_and_python"
            else:
                debug["acl_stage"] = "python_only"
                debug["capability_degraded"].append("ACL_PRINCIPALS_COLUMN_MISSING")
            source = "FROM ai_document_chunk c JOIN ai_document d ON c.document_id = d.id"

            stage_started = time.perf_counter()
            timing = debug.setdefault("v2_timing_ms", {})
            eligible = int((cursor.execute(f"SELECT COUNT(*) {source} {scope}", scope_params).fetchone() or [0])[0] or 0)
            timing["count"] = round((time.perf_counter() - stage_started) * 1000.0, 2)
            debug["metadata_candidate_chunks"] = eligible
            if eligible <= exact_threshold:
                return None

            ranked: Dict[str, list[str]] = {}
            leg_scores: Dict[str, Dict[str, float]] = {}

            def run_leg(name: str, setup: list[tuple[str, list[Any]]], sql: str, leg_params: list[Any]) -> None:
                # A failed leg (e.g. an invalid tsquery or a vector dimension
                # mismatch) must not abort the transaction for the other legs.
                leg_started = time.perf_counter()
                try:
                    cursor.execute("SAVEPOINT rag_v2_leg")
                    savepoint = True
                except Exception:
                    savepoint = False
                try:
                    for statement, statement_params in setup:
                        cursor.execute(statement, statement_params)
                    rows = cursor.execute(sql, leg_params).fetchall()
                    if savepoint:
                        cursor.execute("RELEASE SAVEPOINT rag_v2_leg")
                except Exception:
                    if savepoint:
                        try:
                            cursor.execute("ROLLBACK TO SAVEPOINT rag_v2_leg")
                        except Exception as exc:
                            logger.debug("ROLLBACK TO SAVEPOINT rag_v2_leg failed code=AI_RAG_SAVEPOINT_ROLLBACK_FAILED error=%s", type(exc).__name__)
                    logger.info("RAG V2 retrieval leg degraded leg=%s", name)
                    debug["capability_degraded"].append(f"{name.upper()}_LEG_FAILED")
                    debug["v2_legs"][name] = {"status": "degraded", "candidates": 0}
                    return
                ids: list[str] = []
                for row in rows:
                    chunk_id = str(row[0])
                    ids.append(chunk_id)
                    # The fts/trgm legs match loosely (any term, fuzzy
                    # words) to widen recall; their scores are kept under a
                    # separate key so they do not inflate the lexical score
                    # used for ranking (benchmark 2026-11-22: top-1 agreement
                    # with v1 went from 0.30 to 1.00 once excluded).  The
                    # vector leg is a real cosine and is used as before.
                    score_key = name if name == "vector" else f"{name}_recall"
                    leg_scores.setdefault(chunk_id, {})[score_key] = max(0.0, min(1.0, float(row[1] or 0.0)))
                ranked[name] = ids
                debug["v2_legs"][name] = {
                    "status": "ok",
                    "candidates": len(ids),
                    "ms": round((time.perf_counter() - leg_started) * 1000.0, 2),
                }

            if "search_text" in chunk_columns:
                # OR of the query's terms: a natural-language question rarely
                # contains only words that all appear in one chunk, so an
                # AND query (websearch_to_tsquery) would recall almost
                # nothing.  ts_rank_cd still favours chunks matching more
                # terms.  Only plain alphanumeric terms are used, so the
                # tsquery syntax cannot be injected.
                terms = list(dict.fromkeys(re.findall(r"[a-z0-9_]{2,}", query_text.lower())))[:32]
                if terms:
                    tsquery = " | ".join(terms)
                    # m0332 stored tsvector once its index is built (ranking
                    # reads the stored vector instead of re-parsing every
                    # match); otherwise the identical m0138 expression index.
                    use_stored = self._stored_tsv_ready(cursor, chunk_columns)
                    tsv = "c.search_tsv" if use_stored else "to_tsvector('simple', COALESCE(c.search_text, ''))"
                    debug["v2_fts_source"] = "search_tsv" if use_stored else "expression"
                    run_leg(
                        "fts",
                        [],
                        f"SELECT c.id, LEAST(1.0, ts_rank_cd({tsv}, to_tsquery('simple', ?))) {source} {scope} "
                        f"AND {tsv} @@ to_tsquery('simple', ?) "
                        "ORDER BY 2 DESC, c.id LIMIT ?",
                        [tsquery, *scope_params, tsquery, leg_limit],
                    )
                else:
                    debug["v2_legs"]["fts"] = {"status": "skipped_no_terms", "candidates": 0}
                # word_similarity compares the query with the best-matching
                # part of a chunk; whole-string similarity of a short query
                # against a long chunk is close to zero.  Uses the m0138
                # gin_trgm_ops index through the <% operator.
                word_threshold = max(0.0, min(1.0, float(os.environ.get("AI_RETRIEVAL_TRGM_WORD_THRESHOLD", "0.5"))))
                trgm_setup = [("SELECT set_config('pg_trgm.word_similarity_threshold', ?, true)", [str(word_threshold)])]
                # Modes (2026-11-22 benchmarks, 10k chunks):
                #   auto  (default) whole-query match, skipped when the query
                #         has no CJK run, model name, interface or hyphenated
                #         command: plain Latin words are covered by FTS, and
                #         the leg costs ~320 ms of a ~500 ms search.
                #   query always the whole-query match (previous default).
                #   terms one match per distinctive term (measured slower,
                #         524 ms vs 321 ms); kept for measurement.
                trgm_mode = str(os.environ.get("AI_RETRIEVAL_TRGM_MODE", "auto")).strip().lower()
                if trgm_mode not in {"auto", "query", "terms"}:
                    trgm_mode = "auto"
                trgm_terms = _trgm_terms(query_text) if trgm_mode in {"terms", "auto"} else []
                debug["v2_trgm_mode"] = trgm_mode
                if trgm_mode == "terms" and trgm_terms:
                    # Fuzzy matching is only needed where FTS is weak: model
                    # names / interfaces / hyphenated commands (S5700,
                    # Eth-Trunk, route-static) and CJK text, which the
                    # 'simple' parser cannot split.  Short distinctive terms
                    # are far more selective in the trigram index than the
                    # whole question (benchmark: ~300 ms for the whole-query
                    # leg).  Plain words are left to the FTS leg.
                    match_sql = " OR ".join("? <% c.search_text" for _ in trgm_terms)
                    score_sql = "GREATEST(" + ", ".join("word_similarity(?, COALESCE(c.search_text, ''))" for _ in trgm_terms) + ")"
                    run_leg(
                        "trgm",
                        trgm_setup,
                        f"SELECT c.id, {score_sql} {source} {scope} "
                        f"AND ({match_sql}) ORDER BY 2 DESC, c.id LIMIT ?",
                        [*trgm_terms, *scope_params, *trgm_terms, leg_limit],
                    )
                    debug["v2_trgm_terms"] = len(trgm_terms)
                elif trgm_mode == "query" or (trgm_mode == "auto" and trgm_terms):
                    trgm_text = query_text[:256]
                    run_leg(
                        "trgm",
                        trgm_setup,
                        f"SELECT c.id, word_similarity(?, COALESCE(c.search_text, '')) {source} {scope} "
                        "AND ? <% c.search_text ORDER BY 2 DESC, c.id LIMIT ?",
                        [trgm_text, *scope_params, trgm_text, leg_limit],
                    )
                else:
                    debug["v2_legs"]["trgm"] = {"status": "skipped_no_terms", "candidates": 0}
            else:
                debug["capability_degraded"].append("SEARCH_TEXT_COLUMN_MISSING")

            semantic_cast = self._semantic_column_cast(cursor) if semantic and semantic.get("vector") else None
            if semantic and semantic.get("vector") and semantic_cast is None:
                semantic["vector"] = []
                semantic["error_code"] = "SEMANTIC_COLUMN_MISSING"
            if semantic_cast is not None:
                literal = "[" + ",".join(str(float(value)) for value in semantic["vector"]) + "]"
                setup = [
                    ("SELECT set_config('hnsw.ef_search', ?, true)", [str(_env_int("AI_RETRIEVAL_HNSW_EF_SEARCH", 100, 10, 1000))]),
                ]
                if _pgvector_version(cursor) >= (0, 8):
                    setup.append(("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)", []))
                run_leg(
                    "vector",
                    setup,
                    f"SELECT c.id, 1 - (c.embedding_v2 <=> CAST(? AS {semantic_cast})) {source} {scope} "
                    "AND c.embedding_v2 IS NOT NULL AND c.embedding_v2_model = ? AND c.embedding_v2_version = ? "
                    f"ORDER BY c.embedding_v2 <=> CAST(? AS {semantic_cast}) LIMIT ?",
                    [literal, *scope_params, semantic["model"], semantic["version"], literal, leg_limit],
                )
            elif "embedding_vector" in chunk_columns and query_vector:
                vector_literal = "[" + ",".join(str(float(value)) for value in query_vector) + "]"
                setup: list[tuple[str, list[Any]]] = [
                    ("SELECT set_config('hnsw.ef_search', ?, true)", [str(_env_int("AI_RETRIEVAL_HNSW_EF_SEARCH", 100, 10, 1000))]),
                ]
                if _pgvector_version(cursor) >= (0, 8):
                    # Keep scanning the HNSW graph until enough rows pass
                    # the metadata/ACL filters (pgvector >= 0.8).
                    setup.append(("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)", []))
                model_sql = ""
                model_params: list[Any] = []
                current_model = str(getattr(self._active_embedder(), "model_id", "") or "")
                if current_model and "embedding_model" in chunk_columns:
                    model_sql = " AND (c.embedding_model IS NULL OR c.embedding_model = ?)"
                    model_params = [current_model]
                run_leg(
                    "vector",
                    setup,
                    f"SELECT c.id, 1 - (c.embedding_vector <=> CAST(? AS vector)) {source} {scope} "
                    f"AND c.embedding_vector IS NOT NULL{model_sql} "
                    "ORDER BY c.embedding_vector <=> CAST(? AS vector) LIMIT ?",
                    [vector_literal, *scope_params, *model_params, vector_literal, leg_limit],
                )
            elif "embedding_vector" not in chunk_columns:
                debug["capability_degraded"].append("EMBEDDING_VECTOR_COLUMN_MISSING")
            else:
                debug["capability_degraded"].append("QUERY_EMBEDDING_UNAVAILABLE")

            fused: Dict[str, float] = {}
            for ids in ranked.values():
                for rank, chunk_id in enumerate(ids, start=1):
                    fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
            selected = [chunk_id for chunk_id, _ in sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:fused_limit]]
            rows: list[Any] = []
            context_documents: list[str] = []
            if selected:
                placeholders = ", ".join("?" for _ in selected)
                # Context expansion needs the parent/neighbour chunks of the
                # best documents (V1 had them because it loaded everything).
                # Load whole documents, but only for the top-ranked ones.
                owner_rows = cursor.execute(
                    f"SELECT c.id, c.document_id FROM ai_document_chunk c WHERE c.id IN ({placeholders})",
                    list(selected),
                ).fetchall()
                owner = {str(row[0]): str(row[1]) for row in owner_rows}
                doc_limit = _env_int("AI_RETRIEVAL_V2_CONTEXT_DOCUMENTS", self.candidate_pool_size, 1, 100)
                for chunk_id in selected:
                    document_id = owner.get(chunk_id)
                    if document_id and document_id not in context_documents:
                        context_documents.append(document_id)
                    if len(context_documents) >= doc_limit:
                        break
                doc_placeholders = ", ".join("?" for _ in context_documents) or "NULL"
                max_rows = _env_int("AI_RETRIEVAL_V2_MAX_ROWS", 3000, 100, 50_000)
                id_filter_sql = f"AND (c.id IN ({placeholders}) OR c.document_id IN ({doc_placeholders})) "
                id_filter_params = [*selected, *context_documents]
                embedding_expr = "c.embedding"
                if semantic_cast is None and "embedding_vector" in chunk_columns and query_vector:
                    # Score every loaded row in pgvector (the vector leg only
                    # scored its own top 50).  Rows scored here do not need
                    # their JSON vector, so it is not transferred either.
                    scored_started = time.perf_counter()
                    try:
                        cursor.execute("SAVEPOINT rag_v2_vector_scores")
                        score_rows = cursor.execute(
                            f"SELECT c.id, 1 - (c.embedding_vector <=> CAST(? AS vector)) {source} {scope} "
                            f"{id_filter_sql}AND c.embedding_vector IS NOT NULL{model_sql} LIMIT ?",
                            [vector_literal, *scope_params, *id_filter_params, *model_params, max_rows],
                        ).fetchall()
                        cursor.execute("RELEASE SAVEPOINT rag_v2_vector_scores")
                        for score_row in score_rows:
                            leg_scores.setdefault(str(score_row[0]), {}).setdefault(
                                "vector", max(0.0, min(1.0, float(score_row[1] or 0.0)))
                            )
                        embedding_expr = "CASE WHEN c.embedding_vector IS NULL THEN c.embedding END"
                        debug["v2_vector_scored_rows"] = len(score_rows)
                    except Exception:
                        try:
                            cursor.execute("ROLLBACK TO SAVEPOINT rag_v2_vector_scores")
                        except Exception as exc:
                            logger.debug("ROLLBACK TO SAVEPOINT rag_v2_vector_scores failed code=AI_RAG_SAVEPOINT_ROLLBACK_FAILED error=%s", type(exc).__name__)
                        logger.info("RAG V2 vector scoring degraded; ranking falls back to Python cosine")
                        debug["capability_degraded"].append("VECTOR_SCORE_QUERY_FAILED")
                    timing["vector_scores"] = round((time.perf_counter() - scored_started) * 1000.0, 2)
                load_started = time.perf_counter()
                rows = cursor.execute(
                    f"SELECT {self._row_select_list(columns, chunk_columns, embedding_expr)} {source} {scope} "
                    f"AND (c.id IN ({placeholders}) OR c.document_id IN ({doc_placeholders})) "
                    "ORDER BY d.id, " + ("COALESCE(c.ordinal, 0)" if "ordinal" in chunk_columns else "c.id") + ", c.id "
                    "LIMIT ?",
                    [*scope_params, *selected, *context_documents, max_rows],
                ).fetchall()
                timing["load"] = round((time.perf_counter() - load_started) * 1000.0, 2)
        debug.update({
            "metadata_filter": where_sql,
            "candidate_count": len(rows),
            "vector_top_n": leg_limit,
            "v2_fused_candidates": len(selected),
            "v2_context_documents": len(context_documents),
            "fts_stage": "native_postgresql" if "fts" in ranked else "disabled",
            "trgm_stage": "native_postgresql" if "trgm" in ranked else "disabled",
            "vector_stage": "native_pgvector" if "vector" in ranked else "disabled",
            "fts_candidates": len(ranked.get("fts", [])),
            "trgm_candidates": len(ranked.get("trgm", [])),
            "vector_candidates": len(ranked.get("vector", [])),
        })
        if semantic_cast is not None and semantic and semantic.get("vector"):
            self._apply_semantic_scores(rows, leg_scores, debug, semantic)
        return rows, debug, leg_scores

    def _shadow_compare(
        self,
        request: RetrievalRequest,
        candidate_hint: int,
        query_vector: Sequence[float],
        active_embedder: Any,
        min_relevance: float,
        top_k: int,
        cache_key: Any,
        v1_ids: Sequence[str],
    ) -> Dict[str, Any]:
        """Run V2 next to V1 and report how much the answers agree.

        Never affects the served (V1) result; any V2 failure is reported
        as a stable code only.
        """
        started = time.perf_counter()
        try:
            rows, debug, scores = self._candidates_v2(request, candidate_hint, query_vector)
            v2_payload = self._rank_rows(
                request, rows, debug, scores, query_vector, active_embedder, min_relevance, top_k, cache_key,
            )
        except Exception:
            logger.warning("RAG shadow V2 retrieval failed")
            return {"status": "error", "error_code": "RETRIEVAL_V2_SHADOW_FAILED"}
        v1_ids = [str(value) for value in v1_ids]
        v2_ids = [str(item.get("document_id")) for item in v2_payload.get("results") or []]
        overlap = len(set(v1_ids) & set(v2_ids))
        report = {
            "status": "ok",
            "engine": debug.get("retrieval_engine"),
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "candidate_count": debug.get("candidate_count"),
            "document_ids": v2_ids,
            "top1_match": bool(v1_ids and v2_ids and v1_ids[0] == v2_ids[0]),
            "overlap_at_k": round(overlap / max(1, len(v1_ids)), 4) if v1_ids else (1.0 if not v2_ids else 0.0),
            "legs": debug.get("v2_legs", {}),
            "capability_degraded": debug.get("capability_degraded", []),
            "vector_source": debug.get("vector_source"),
        }
        logger.info(
            "RAG shadow comparison engine=%s top1_match=%s overlap=%.2f v2_candidates=%s v2_latency_ms=%.1f",
            report["engine"], report["top1_match"], report["overlap_at_k"], report["candidate_count"], report["latency_ms"],
        )
        return report

    def _schedule_shadow(
        self,
        request: RetrievalRequest,
        candidate_hint: int,
        query_vector: Sequence[float],
        active_embedder: Any,
        min_relevance: float,
        top_k: int,
        cache_key: Any,
        v1_payload: Dict[str, Any],
        v1_latency_ms: float,
    ) -> Dict[str, Any]:
        """Compare V2 with the served V1 result without delaying the user."""
        import random

        v1_ids = [str(item.get("document_id")) for item in v1_payload.get("results") or []]
        sample_rate = _shadow_float("AI_RETRIEVAL_SHADOW_SAMPLE_RATE", 1.0)
        if sample_rate < 1.0 and random.random() >= sample_rate:
            return {"status": "sampled_out"}
        args = (
            _dataclass_replace(request), candidate_hint, list(query_vector or []), active_embedder,
            min_relevance, top_k, cache_key, v1_ids, v1_latency_ms,
        )
        if _shadow_mode() == "sync":
            return self._shadow_job(*args)
        try:
            max_pending = max(1, int(os.environ.get("AI_RETRIEVAL_SHADOW_MAX_PENDING", "16")))
        except (TypeError, ValueError):
            max_pending = 16
        with _SHADOW_LOCK:
            if _SHADOW_STATE["pending"] >= max_pending:
                _SHADOW_STATE["dropped"] += 1
                return {"status": "dropped_busy"}
            _SHADOW_STATE["pending"] += 1
        try:
            _shadow_executor().submit(self._shadow_job_tracked, *args)
        except Exception:
            with _SHADOW_LOCK:
                _SHADOW_STATE["pending"] -= 1
                _SHADOW_STATE["dropped"] += 1
            return {"status": "dropped_unavailable"}
        return {"status": "scheduled"}

    def _shadow_job_tracked(self, *args: Any) -> None:
        try:
            self._shadow_job(*args)
        except Exception:
            logger.warning("RAG shadow job failed unexpectedly")
        finally:
            with _SHADOW_LOCK:
                _SHADOW_STATE["pending"] = max(0, _SHADOW_STATE["pending"] - 1)

    def _shadow_job(
        self,
        request: RetrievalRequest,
        candidate_hint: int,
        query_vector: Sequence[float],
        active_embedder: Any,
        min_relevance: float,
        top_k: int,
        cache_key: Any,
        v1_ids: Sequence[str],
        v1_latency_ms: float,
    ) -> Dict[str, Any]:
        # The per-search table-shape cache is thread-local; a background
        # thread needs its own.
        previous = getattr(self._column_cache, "tables", None)
        self._column_cache.tables = {}
        try:
            report = self._shadow_compare(
                request, candidate_hint, query_vector, active_embedder,
                min_relevance, top_k, cache_key, v1_ids,
            )
        finally:
            self._column_cache.tables = previous
        self._record_shadow(request, report, v1_ids, v1_latency_ms)
        return report

    def _record_shadow(
        self,
        request: RetrievalRequest,
        report: Dict[str, Any],
        v1_ids: Sequence[str],
        v1_latency_ms: float,
    ) -> None:
        """Persist one comparison (metadata only); never raises."""
        import hashlib

        query = str(request.query or "")
        preview = None
        if str(os.environ.get("AI_RETRIEVAL_SHADOW_STORE_QUERY", "0")).strip().lower() in {"1", "true", "yes", "on"}:
            from ai.security.sanitizer import sanitize_log_text

            preview = sanitize_log_text(query, limit=200)
        degraded = [str(code)[:64] for code in (report.get("capability_degraded") or [])][:20]
        values = [
            str(request.tenant_id or "tenant-default")[:128],
            hashlib.sha256(query.encode("utf-8")).hexdigest()[:32],
            preview,
            str(report.get("status") or "error")[:16],
            (str(report.get("error_code"))[:64] if report.get("error_code") else None),
            (str(report.get("engine"))[:32] if report.get("engine") else None),
            (str(report.get("vector_source"))[:32] if report.get("vector_source") else None),
            report.get("top1_match") if report.get("status") == "ok" else None,
            report.get("overlap_at_k") if report.get("status") == "ok" else None,
            len(v1_ids),
            len(report.get("document_ids") or []),
            report.get("candidate_count"),
            int(round(v1_latency_ms)),
            (int(round(float(report["latency_ms"]))) if report.get("latency_ms") is not None else None),
            [str(value)[:128] for value in v1_ids][:20],
            [str(value)[:128] for value in (report.get("document_ids") or [])][:20],
            degraded,
        ]
        try:
            with self._open_connection() as conn:
                conn.execute(
                    "INSERT INTO ai_retrieval_shadow_comparison (tenant_id, query_hash, query_preview, status, error_code, "
                    "v2_engine, vector_source, top1_match, overlap_at_k, v1_result_count, v2_result_count, "
                    "v2_candidate_count, v1_latency_ms, v2_latency_ms, v1_document_ids, v2_document_ids, capability_degraded) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
                with _SHADOW_LOCK:
                    _SHADOW_STATE["recorded"] += 1
                    prune = _SHADOW_STATE["recorded"] % _SHADOW_PRUNE_EVERY == 0
                if prune:
                    try:
                        days = max(1, int(os.environ.get("AI_RETRIEVAL_SHADOW_RETENTION_DAYS", "30")))
                    except (TypeError, ValueError):
                        days = 30
                    conn.execute(
                        "DELETE FROM ai_retrieval_shadow_comparison WHERE created_at < now() - make_interval(days => ?)",
                        [days],
                    )
                conn.commit()
        except Exception:
            with _SHADOW_LOCK:
                _SHADOW_STATE["record_failures"] += 1
                first = _SHADOW_STATE["record_failures"] == 1
            # Typically the m0333 table is missing (migrations not run).
            if first:
                logger.warning("RAG shadow comparison could not be stored code=SHADOW_RECORD_FAILED")

    def _rank_rows(
        self,
        request: RetrievalRequest,
        rows: Sequence[Any],
        debug: Dict[str, Any],
        accelerator_scores: Dict[str, Dict[str, float]],
        query_vector: Sequence[float],
        active_embedder: Any,
        min_relevance: float,
        top_k: int,
        cache_key: Any,
    ) -> Dict[str, Any]:
        """Score candidate rows and build the user-visible payload.

        Shared by the V1 and V2 engines: ACL re-check, feature/version guards,
        ScoreComponents ranking, document dedup, reranking and context
        expansion are identical; only how ``rows`` were selected differs.
        """
        query_vector = list(query_vector or [])
        semantic_vector_signal = debug.get("vector_source") == "semantic" or debug.get("vector_stage") == "native_pgvector_semantic"
        weights = score_weights()
        # AI_RETRIEVAL_NATIVE_LEXICAL=1 (diagnostic only) also lets the loose
        # V2 recall-leg scores raise the lexical score.  Default 0: V2 ranks
        # with the same lexical score as V1.
        native_lexical = str(os.getenv("AI_RETRIEVAL_NATIVE_LEXICAL", "0")).strip().lower() in {"1", "true", "yes", "on"}
        rank_started = time.perf_counter()
        # Per-stage time of the loop below (seconds), reported in
        # debug["v2_timing_ms"] as rank_<stage>.
        rank_ms = {"filter": 0.0, "keyword": 0.0, "vector": 0.0, "score": 0.0, "item": 0.0}
        python_vector_rows = 0
        scored: list[dict[str, Any]] = []
        chunks_by_document: Dict[str, list[dict[str, Any]]] = {}
        incompatible_vectors = 0
        version_conflicts = 0
        wrong_vendor_rows = 0
        feature_scope_filtered = 0
        current_model = str(getattr(active_embedder, "model_id", "") or "")
        for row in rows:
            (
                c_id, content, embedding_json, meta_json, section,
                doc_id, doc_name, document_source, knowledge_source_type, document_version, d_vendor, d_platform, d_tenant,
                acl_json, trust_level, document_category, cli_platform,
                semantic_document_id, document_software_train, document_software_release,
                _is_candidate, chunk_role,
                parent_chunk_id, ordinal, stored_embedding_model, stored_embedding_dimensions,
            ) = row
            row_started = time.perf_counter()
            document = {"id": doc_id, "tenant_id": d_tenant, "acl_json": acl_json}
            if not document_is_visible(document, tenant_id=request.tenant_id, user_id=request.user_id, roles=request.roles, site_ids=request.site_ids):
                continue
            metadata = self._parse_json(meta_json)
            requested_vendor = str(getattr(request, "vendor", "") or "").strip().lower()
            actual_vendor = str(metadata.get("vendor") or d_vendor or "").strip().lower()
            if requested_vendor and actual_vendor and requested_vendor != actual_vendor:
                wrong_vendor_rows += 1
            if not self._feature_scope_is_eligible(
                getattr(request, "feature", None),
                metadata,
                content=content,
                section=section,
                document_name=doc_name,
                document_source=document_source,
                knowledge_source_type=knowledge_source_type,
            ):
                feature_scope_filtered += 1
                continue
            filter_mark = time.perf_counter()
            rank_ms["filter"] += filter_mark - row_started
            row_started = filter_mark
            keyword_score = self._calc_keyword_relevance(
                request.query,
                str(content or ""),
                str(doc_name or ""),
                section=str(section or ""),
                metadata=metadata,
            )
            native_scores = accelerator_scores.get(str(c_id), {})
            # V1 accelerator scores (strict websearch tsquery / similarity).
            keyword_score = max(
                keyword_score,
                float(native_scores.get("fts", 0.0)),
                float(native_scores.get("trgm", 0.0)),
            )
            if native_lexical:
                keyword_score = max(
                    keyword_score,
                    float(native_scores.get("fts_recall", 0.0)),
                    float(native_scores.get("trgm_recall", 0.0)),
                )
            stage_mark = time.perf_counter()
            rank_ms["keyword"] += stage_mark - row_started
            stored_dimensions = int(stored_embedding_dimensions or 0)
            if semantic_vector_signal:
                # bge-m3 cosine computed in SQL for every candidate; rows
                # without a current semantic vector score 0.
                vector_score = float(native_scores.get("vector", 0.0))
            elif stored_embedding_model and current_model and str(stored_embedding_model) != current_model:
                vector_score = 0.0
                incompatible_vectors += 1
            elif "vector" in native_scores and not (stored_dimensions and len(query_vector) != stored_dimensions):
                # pgvector already scored this row (same model filter, the
                # fixed-dimension embedding_vector column).  Parsing the
                # 1536-float JSON copy and a pure-Python cosine cost ~1 ms
                # per row and were done even when this score existed,
                # because dict.get() evaluates its default eagerly.
                vector_score = float(native_scores["vector"])
            else:
                try:
                    chunk_vector = embedding_json if isinstance(embedding_json, list) else json.loads(str(embedding_json or "[]"))
                    if not isinstance(chunk_vector, list):
                        chunk_vector = []
                except (TypeError, ValueError):
                    chunk_vector = []
                vector_incompatible = bool(
                    stored_dimensions
                    and (len(chunk_vector) != stored_dimensions or len(query_vector) != stored_dimensions)
                )
                if vector_incompatible:
                    vector_score = 0.0
                    incompatible_vectors += 1
                else:
                    vector_score = self._cosine(query_vector, chunk_vector)
                    python_vector_rows += 1
            vector_mark = time.perf_counter()
            rank_ms["vector"] += vector_mark - stage_mark
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
                weights=weights,
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
            item_mark = time.perf_counter()
            rank_ms["score"] += item_mark - vector_mark
            item = {
                "chunk_id": c_id,
                "content": sanitize_text(str(content or "")),
                "document_name": doc_name,
                "source": document_source,
                "knowledge_source_type": knowledge_source_type,
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
                "feature": metadata.get("feature"),
                "feature_source": metadata.get("feature_source"),
                "source_kind": metadata.get("source_kind"),
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
            rank_ms["item"] += time.perf_counter() - item_mark
            if (score >= min_relevance or exact_hardware_identity) and not (exact_command_required and keyword_score < 0.55):
                scored.append(item)

        post_started = time.perf_counter()
        best_by_document: Dict[str, dict[str, Any]] = {}
        for item in scored:
            key = str(item["storage_document_id"])
            previous = best_by_document.get(key)
            if previous is None or (item["relevance_score"], item["source_trust_rank"]) > (previous["relevance_score"], previous["source_trust_rank"]):
                best_by_document[key] = item
        pool_limit = max(top_k, self.candidate_pool_size)
        candidate_documents = sorted(
            best_by_document.values(),
            key=lambda item: (item["relevance_score"], item["source_trust_rank"]),
            reverse=True,
        )[:pool_limit]
        reranked_documents, reranker_debug = self.reranker.apply(request.query, candidate_documents)
        final_results = [
            self._expand_document_context(item, chunks_by_document.get(str(item["storage_document_id"]), [item]))
            for item in reranked_documents[:top_k]
        ]
        timing = debug.setdefault("v2_timing_ms", {})
        finished = time.perf_counter()
        timing["rank"] = round((finished - rank_started) * 1000.0, 2)
        timing["rank_post"] = round((finished - post_started) * 1000.0, 2)
        for stage, seconds in rank_ms.items():
            timing[f"rank_{stage}"] = round(seconds * 1000.0, 2)
        debug["rank_python_vector_rows"] = python_vector_rows
        if len(final_results) >= 2 and reranker_debug.get("stage") in {"skipped", "legacy_pass", None}:
            from ai.providers.embedding import rerank_documents

            passages = [
                f"{item.get('document_name') or ''} {item.get('section') or ''}\n{item.get('content') or ''}"
                for item in final_results
            ]
            reranked = rerank_documents(request.query, passages, top_n=len(final_results))
            if reranked:
                ordered = []
                seen_idx = set()
                for entry in reranked:
                    idx = entry["index"]
                    if 0 <= idx < len(final_results) and idx not in seen_idx:
                        seen_idx.add(idx)
                        item_copy = dict(final_results[idx])
                        item_copy["rerank_score"] = round(float(entry["relevance_score"]), 4)
                        ordered.append(item_copy)
                for idx, item in enumerate(final_results):
                    if idx not in seen_idx:
                        ordered.append(item)
                final_results = ordered
                reranker_debug = {
                    "stage": "applied",
                    "provider": "db_openai_compatible",
                    "model": "BAAI/bge-reranker-v2-m3",
                    "reranked_count": len(final_results),
                    "top_score": round(float(reranked[0]["relevance_score"]), 4),
                }
        debug.update({
            "candidate_pool_size": len(candidate_documents),
            "dedup_document_count": len(best_by_document),
            "incompatible_embedding_chunks": incompatible_vectors,
            "version_conflict_count": version_conflicts,
            "wrong_vendor_count": wrong_vendor_rows,
            "feature_scope_filtered": feature_scope_filtered,
            "feature_scope_guard": "content_evidence_v1",
            "expanded_context_chunks": sum(int(item.get("context_chunk_count") or 0) for item in final_results),
            "final_document_ids": [item["document_id"] for item in final_results],
            "reranker": reranker_debug,
            "reranker_config": dict(self.reranker_config),
            "shadow": reranker_debug if reranker_debug.get("mode") == "shadow" else {},
            "cache": {"hit": False, "key": cache_key, "enabled": self.cache_enabled},
            "outcome": "matched" if final_results else "no_match",
        })
        explanation = build_retrieval_explanation(request, debug, final_results)
        payload = {"results": final_results, "debug": debug, "explanation": explanation}
        return payload

    def _search_once(
        self,
        request: RetrievalRequest,
        min_relevance: float = 0.20,
    ) -> Dict[str, Any]:
        """Execute one bounded retrieval (engine chosen by AI_RETRIEVAL_ENGINE)."""
        # Table shapes are probed once per search and forgotten afterwards,
        # so a schema change (or a test with its own tables) is never masked.
        self._column_cache.tables = {}
        try:
            return self._search_once_impl(request, min_relevance)
        finally:
            self._column_cache.tables = None

    def _search_once_impl(
        self,
        request: RetrievalRequest,
        min_relevance: float = 0.20,
    ) -> Dict[str, Any]:
        top_k = max(1, int(request.top_k or 3))
        candidate_hint = max(top_k * 30, 100)
        cache_key = retrieval_cache_key(
            request,
            # The feature-evidence guard changes eligibility.  A new cache
            # namespace prevents a process-local pre-fix result from being
            # served after a rolling code update.
            index_version=(
                f"retrieval-v2:{_retrieval_engine()}:{_vector_source()}:"
                + ",".join(f"{key}={value:g}" for key, value in sorted(score_weights().items()))
            ),
        )
        if self.cache_enabled:
            cached = retrieval_cache.get(cache_key)
            if cached is not None:
                cached.setdefault("debug", {})["cache"] = {"hit": True, "key": cache_key}
                self.last_debug = cached.get("debug") or {}
                return cached
        try:
            engine = _retrieval_engine()
            active_embedder = self._active_embedder()
            query_vector = self._embed_query(active_embedder, request.query)
            started = time.perf_counter()
            if engine == "v2":
                rows, debug, accelerator_scores = self._candidates_v2(request, candidate_hint, query_vector)
            else:
                rows, debug, accelerator_scores = self._candidates_v1(request, candidate_hint, query_vector)
            payload = self._rank_rows(
                request, rows, debug, accelerator_scores, query_vector,
                active_embedder, min_relevance, top_k, cache_key,
            )
            debug["retrieval_latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
            if engine == "shadow":
                try:
                    debug["shadow_v2"] = self._schedule_shadow(
                        request, candidate_hint, query_vector, active_embedder,
                        min_relevance, top_k, cache_key, payload, debug["retrieval_latency_ms"],
                    )
                except Exception:
                    # Shadow work must never fail the served V1 result.
                    logger.warning("RAG shadow scheduling failed")
                    debug["shadow_v2"] = {"status": "error", "error_code": "RETRIEVAL_V2_SHADOW_FAILED"}
            final_results = payload["results"]
            self.last_debug = debug
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
            logger.exception("RAG retrieval execution failed")
            self.last_debug = {
                "error_code": "RETRIEVAL_EXECUTION_FAILED",
                "candidate_count": 0,
                "vector_top_n": candidate_hint,
            }
            return {"results": [], "debug": self.last_debug, "explanation": build_retrieval_explanation(request, self.last_debug, [])}

    def search(self, request: RetrievalRequest, min_relevance: float = 0.20) -> Dict[str, Any]:
        """Return the user-visible result (engine chosen by AI_RETRIEVAL_ENGINE)."""
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
                tenant_id=None,
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
