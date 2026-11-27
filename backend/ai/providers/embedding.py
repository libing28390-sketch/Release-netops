"""Embedding provider abstraction used by ingestion and retrieval.

The application can swap this provider for a local model or a managed
embedding endpoint without changing the RAG contract.  The built-in fallback
is a stable, cryptographic feature vector: it is intentionally deterministic
across processes (unlike Python's process-randomised ``hash()``) and is marked
as a local/degraded model in persisted metadata.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, Sequence


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider is unavailable or incompatible."""


@dataclass(frozen=True)
class EmbeddingContract:
    """Immutable model/dimension contract pinned to a vector."""

    model_id: str
    dimensions: int
    version: str
    mode: str

    def __post_init__(self) -> None:
        if self.dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")

    @property
    def contract_version(self) -> str:
        return f"{self.model_id}:{self.version}:{self.dimensions}"


class BaseEmbeddingProvider:
    """Provider interface shared by document and query embedding paths."""

    model_id = "base"
    dimensions = 1536
    version = "v1"
    mode = "provider"
    batch_size = 32

    def embed_documents(self, texts: Sequence[str], **_: Any) -> List[List[float]]:
        return [self.embed_text(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_text(text)

    def embed_text(self, text: str, dimensions: int | None = None) -> List[float]:
        raise NotImplementedError

    def contract(self) -> EmbeddingContract:
        return EmbeddingContract(
            model_id=str(getattr(self, "model_id", "unknown")),
            dimensions=int(getattr(self, "dimensions", 0) or 0),
            version=str(getattr(self, "version", "unknown")),
            mode=str(getattr(self, "mode", "provider")),
        )


class ExternalEmbeddingProvider(BaseEmbeddingProvider):
    """Adapter for a managed embedding endpoint behind the security gateway.

    The transport is injected so tests and private deployments do not need a
    live vendor endpoint.  Every request is classified/minimized/DLP-checked
    by ``AISecurityGateway.protect_embedding`` before the transport receives it.
    """

    mode = "external"

    def __init__(
        self,
        transport: Callable[[Sequence[str], Mapping[str, Any]], Sequence[Sequence[float]]],
        *,
        model_id: str,
        dimensions: int,
        version: str = "v1",
        provider_type: str = "external",
        security_gateway: Any | None = None,
    ) -> None:
        self.transport = transport
        self.model_id = model_id
        self.dimensions = int(dimensions)
        self.version = version
        self.provider_type = provider_type
        self.security_gateway = security_gateway

    def _gateway(self) -> Any:
        if self.security_gateway is not None:
            return self.security_gateway
        from ai.security.gateway import ai_security_gateway

        return ai_security_gateway

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        tenant_id: str = "tenant-default",
        task_id: str = "embedding",
        user_id: str | None = None,
        idempotency_key: str | None = None,
        provider_id: str | None = None,
        data_region: str | None = None,
        allowed_data_classification: str | None = None,
        **_: Any,
    ) -> List[List[float]]:
        if not texts:
            return []
        secure = self._gateway().protect_embedding(
            texts,
            tenant_id=tenant_id,
            task_id=task_id,
            user_id=user_id,
            provider_type=self.provider_type,
            idempotency_key=idempotency_key,
            provider_id=provider_id,
            model_id=self.model_id,
            data_region=data_region,
            provider_allowed_classification=allowed_data_classification,
        )
        vectors = [list(vector) for vector in self.transport(secure.texts, secure.metadata)]
        if len(vectors) != len(texts):
            raise EmbeddingProviderError("Embedding provider returned an unexpected batch size")
        assert_embedding_compatible(vectors, expected_dimensions=self.dimensions)
        return vectors

    def embed_text(self, text: str, dimensions: int | None = None) -> List[float]:
        if dimensions is not None and int(dimensions) != self.dimensions:
            raise EmbeddingProviderError("External provider dimensions are immutable")
        return self.embed_documents([text])[0]


class StableLocalEmbeddingProvider(BaseEmbeddingProvider):
    """Small deterministic lexical fallback for offline/private deployments.

    It is not presented as a semantic model.  Operators can set
    ``AI_EMBEDDING_MODE=disabled`` to fail loudly instead of using degraded
    vectors, or replace ``embedding_provider`` with a real local/remote model.
    """

    model_id = "local-hybrid-feature-v2"
    version = "v2"
    mode = os.environ.get("AI_EMBEDDING_MODE", "local")
    dimensions = int(os.environ.get("AI_EMBEDDING_DIMENSIONS", "1536"))
    _ascii_token_re = re.compile(r"[A-Za-z0-9_./:-]+")
    _han_run_re = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")

    def _ensure_enabled(self) -> None:
        if str(self.mode).lower() in {"disabled", "off", "none"}:
            raise EmbeddingProviderError(
                "No embedding provider is configured; set AI_EMBEDDING_MODE=local "
                "for explicit lexical-degraded mode or configure a real provider"
            )
    @classmethod
    def _tokens(cls, text: str) -> list[str]:
        """Return position-independent English terms and Chinese n-grams.

        The previous fallback salted every token with its absolute position,
        so the same word in a query and a document almost never shared vector
        dimensions.  Chinese was also reduced to isolated characters.  The
        v2 fallback is still lexical (not a semantic model), but identical
        terms now remain comparable and two/three-character Chinese concepts
        such as ``配置`` and ``知识库`` retain useful signal.
        """

        normalized = str(text or "").lower()
        tokens = cls._ascii_token_re.findall(normalized)
        for run in cls._han_run_re.findall(normalized):
            tokens.extend(run)
            tokens.extend(run[index:index + 2] for index in range(max(0, len(run) - 1)))
            tokens.extend(run[index:index + 3] for index in range(max(0, len(run) - 2)))
        return [token for token in tokens if token]

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    def embed_text(self, text: str, dimensions: int | None = None) -> List[float]:
        self._ensure_enabled()
        size = int(dimensions or self.dimensions)
        if size <= 0:
            raise EmbeddingProviderError("Embedding dimensions must be positive")
        tokens = self._tokens(text)
        if not tokens:
            return [0.0] * size

        vector = [0.0] * size
        # Stable feature hashing uses SHA-256 only for reproducibility.  It is
        # deliberately separate from a Python hash and has no secret key.
        for token in tokens:
            digest = self._digest(token)
            for offset in range(0, len(digest), 4):
                bucket = int.from_bytes(digest[offset:offset + 4], "big") % size
                sign = 1.0 if digest[(offset // 4) % len(digest)] & 1 else -1.0
                vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return [0.0] * size
        return [round(value / norm, 8) for value in vector]


class SidecarEmbeddingProvider(BaseEmbeddingProvider):
    """Semantic embeddings from the in-cluster bge-m3 sidecar.

    Text never leaves the deployment: the endpoint host must be on a local
    allowlist (loopback / the compose service name / AI_EMBEDDING_ALLOWED_HOSTS)
    and URLs with credentials, query strings or fragments are rejected.

    Failure handling is built for the query path: a failed call opens a short
    cooldown (AI_EMBEDDING_SIDECAR_COOLDOWN_SECONDS) during which calls fail
    immediately with ``EmbeddingProviderError`` instead of waiting for the
    timeout again, so retrieval degrades to lexical recall without latency.
    """

    mode = "local_semantic"
    _DEFAULT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "embedding-sidecar"})

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        model_id: str | None = None,
        dimensions: int | None = None,
        version: str | None = None,
        token: str | None = None,
        query_timeout_seconds: float | None = None,
        batch_timeout_seconds: float | None = None,
        cooldown_seconds: float | None = None,
        batch_size: int | None = None,
        transport: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        from urllib.parse import urlparse

        raw = str(endpoint or os.environ.get("AI_EMBEDDING_SIDECAR_URL", "http://embedding-sidecar:8005")).strip().rstrip("/")
        if len(raw) > 2048:
            raise EmbeddingProviderError("Embedding sidecar endpoint is too long")
        parsed = urlparse(raw)
        try:
            host = (parsed.hostname or "").lower()
            _ = parsed.port
        except ValueError as exc:
            raise EmbeddingProviderError("Embedding sidecar endpoint is malformed") from exc
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise EmbeddingProviderError("Embedding sidecar endpoint must be an HTTP(S) URL without credentials or query parameters")
        allowed = set(self._DEFAULT_HOSTS) | {
            item.strip().lower() for item in os.environ.get("AI_EMBEDDING_ALLOWED_HOSTS", "").split(",") if item.strip()
        }
        if host not in allowed:
            raise EmbeddingProviderError("Embedding sidecar host is not in the local allowlist")
        self.endpoint = raw
        self.model_id = str(model_id or os.environ.get("AI_SEMANTIC_EMBEDDING_MODEL", "bge-m3"))
        self.dimensions = int(dimensions or os.environ.get("AI_SEMANTIC_EMBEDDING_DIMENSIONS", "1024"))
        self.version = str(version or os.environ.get("AI_SEMANTIC_EMBEDDING_VERSION", "bge-m3-int8-v1"))
        self.batch_size = max(1, min(int(batch_size or os.environ.get("AI_EMBEDDING_SIDECAR_BATCH", "32")), 64))
        self._token = token if token is not None else os.environ.get("AI_EMBEDDING_SIDECAR_TOKEN", "")
        self._query_timeout = max(0.05, min(float(query_timeout_seconds or int(os.environ.get("AI_EMBEDDING_QUERY_TIMEOUT_MS", "1500")) / 1000.0), 30.0))
        self._batch_timeout = max(1.0, min(float(batch_timeout_seconds or os.environ.get("AI_EMBEDDING_BATCH_TIMEOUT_SECONDS", "60")), 600.0))
        self._cooldown = max(0.0, float(cooldown_seconds if cooldown_seconds is not None else os.environ.get("AI_EMBEDDING_SIDECAR_COOLDOWN_SECONDS", "30")))
        self._transport = transport
        self._clock = clock
        self._lock = threading.Lock()
        self._unavailable_until = 0.0
        self._last_error: str | None = None
        self._contract_checked = False
        self._query_cache: "OrderedDict[str, list[float]]" = OrderedDict()
        self._query_cache_max = max(0, int(os.environ.get("AI_EMBEDDING_QUERY_CACHE_SIZE", "512")))
        self._client: Any = None

    # -- transport ---------------------------------------------------------
    def _http(self) -> Any:
        import httpx

        if self._client is None:
            with self._lock:
                if self._client is None:
                    # trust_env=False: never route in-cluster traffic through
                    # an inherited HTTP(S)_PROXY.
                    self._client = httpx.Client(
                        transport=self._transport,
                        trust_env=False,
                        headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
                        limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
                    )
        return self._client

    def _fail(self, code: str, exc: Exception | None = None) -> EmbeddingProviderError:
        with self._lock:
            self._unavailable_until = self._clock() + self._cooldown
            self._last_error = code
        error = EmbeddingProviderError(f"Embedding sidecar unavailable: {code}")
        if exc is not None:
            error.__cause__ = exc
        return error

    def _request(self, method: str, path: str, *, timeout: float, payload: Any = None) -> Any:
        if self._clock() < self._unavailable_until:
            raise EmbeddingProviderError(f"Embedding sidecar unavailable: {self._last_error or 'COOLDOWN'} (cooling down)")
        import httpx

        try:
            response = self._http().request(method, f"{self.endpoint}{path}", json=payload, timeout=httpx.Timeout(timeout, connect=min(timeout, 2.0)))
        except httpx.TimeoutException as exc:
            raise self._fail("TIMEOUT", exc)
        except httpx.HTTPError as exc:
            raise self._fail("CONNECTION_FAILED", exc)
        if response.status_code == 503:
            raise self._fail("NOT_READY")
        if response.status_code in (401, 403):
            raise self._fail("UNAUTHORIZED")
        if response.status_code >= 400:
            raise self._fail(f"HTTP_{response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise self._fail("INVALID_RESPONSE", exc)

    def _check_contract(self) -> None:
        if self._contract_checked:
            return
        info = self._request("GET", "/v1/info", timeout=self._query_timeout)
        if str(info.get("model_id")) != self.model_id or int(info.get("dimensions") or 0) != self.dimensions:
            # A different model behind the same URL must never be mixed into
            # an index built for another model; this is not a transient error.
            raise self._fail("MODEL_CONTRACT_MISMATCH")
        if str(info.get("version") or "") != self.version:
            raise self._fail("MODEL_VERSION_MISMATCH")
        self._contract_checked = True

    def _embed(self, texts: Sequence[str], *, kind: str, timeout: float) -> List[List[float]]:
        self._check_contract()
        payload = self._request("POST", "/v1/embeddings", timeout=timeout, payload={"input": list(texts), "kind": kind})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != len(texts):
            raise self._fail("BATCH_SIZE_MISMATCH")
        vectors: List[List[float]] = []
        for vector in data:
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise self._fail("DIMENSION_MISMATCH")
            values = [float(value) for value in vector]
            if not all(math.isfinite(value) for value in values):
                raise self._fail("NON_FINITE_VECTOR")
            vectors.append(values)
        with self._lock:
            self._last_error = None
        return vectors

    # -- provider interface ------------------------------------------------
    def embed_documents(self, texts: Sequence[str], **_: Any) -> List[List[float]]:
        values = [str(text or "") for text in texts]
        result: List[List[float]] = []
        for start in range(0, len(values), self.batch_size):
            result.extend(self._embed(values[start:start + self.batch_size], kind="document", timeout=self._batch_timeout))
        return result

    def embed_query(self, text: str) -> List[float]:
        value = str(text or "")
        key = hashlib.sha256(value.encode("utf-8")).hexdigest()
        with self._lock:
            cached = self._query_cache.get(key)
            if cached is not None:
                self._query_cache.move_to_end(key)
                return list(cached)
        vector = self._embed([value], kind="query", timeout=self._query_timeout)[0]
        if self._query_cache_max:
            with self._lock:
                self._query_cache[key] = vector
                while len(self._query_cache) > self._query_cache_max:
                    self._query_cache.popitem(last=False)
        return list(vector)

    def embed_text(self, text: str, dimensions: int | None = None) -> List[float]:
        if dimensions is not None and int(dimensions) != self.dimensions:
            raise EmbeddingProviderError("Sidecar embedding dimensions are fixed by the model")
        return self.embed_documents([text])[0]

    def status(self) -> dict[str, Any]:
        """Health for diagnostics; never raises and never returns text."""
        cooling = self._clock() < self._unavailable_until
        state = {
            "provider": "sidecar",
            "model_id": self.model_id,
            "dimensions": self.dimensions,
            "version": self.version,
            "contract_verified": self._contract_checked,
            "cooling_down": cooling,
            "last_error": self._last_error,
        }
        if not cooling:
            try:
                self._check_contract()
                state.update({"status": "ready", "contract_verified": True})
                return state
            except EmbeddingProviderError:
                state["last_error"] = self._last_error
        state["status"] = "unavailable"
        return state


embedding_provider: BaseEmbeddingProvider = StableLocalEmbeddingProvider()

# The semantic provider is separate from ``embedding_provider`` on purpose:
# the legacy ``embedding_vector`` column is vector(1536) built by the lexical
# fallback, while bge-m3 vectors (1024) go to their own column.  Mixing them
# would make every similarity meaningless.
_SEMANTIC_PROVIDER: BaseEmbeddingProvider | None = None
_SEMANTIC_PROVIDER_KEY: tuple[str, ...] | None = None
_SEMANTIC_LOCK = threading.Lock()
_DB_EMBEDDING_CHECKED_AT: float = 0.0
_DB_EMBEDDING_CACHE: "OpenAICompatibleDBEmbeddingProvider | None" = None


class OpenAICompatibleDBEmbeddingProvider(BaseEmbeddingProvider):
    """Semantic embedding provider backed by an enabled DB ai_model (model_type='embedding')."""

    mode = "provider"
    version = "v2"
    batch_size = 32

    def __init__(
        self,
        *,
        model_code: str,
        endpoint: str,
        api_key: str,
        provider_name: str,
        proxy_url: str | None = None,
        dimensions: int = 1024,
        timeout_seconds: float = 8.0,
    ) -> None:
        self.model_id = model_code
        self.endpoint = endpoint
        self._api_key = api_key
        self.provider_name = provider_name
        self.proxy_url = proxy_url
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "provider": "db_openai_compatible",
            "provider_name": self.provider_name,
            "model": self.model_id,
            "dimensions": self.dimensions,
            "available": True,
            "status": "ready",
        }

    def embed_documents(self, texts: Sequence[str], **_: Any) -> List[List[float]]:
        import httpx

        items = [str(t or "")[:4000] for t in texts]
        if not items:
            return []
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        vectors: List[List[float]] = []
        with httpx.Client(timeout=self.timeout_seconds, proxy=self.proxy_url or None) as client:
            for i in range(0, len(items), self.batch_size):
                batch = items[i : i + self.batch_size]
                resp = client.post(self.endpoint, headers=headers, json={"model": self.model_id, "input": batch})
                if resp.status_code != 200:
                    raise EmbeddingProviderError(f"DB embedding HTTP {resp.status_code}")
                data = resp.json().get("data") or []
                if len(data) != len(batch):
                    raise EmbeddingProviderError("DB embedding batch size mismatch")
                for obj in data:
                    vec = [float(x) for x in (obj.get("embedding") or [])]
                    if vec:
                        self.dimensions = len(vec)
                    vectors.append(vec)
        return vectors

    def embed_text(self, text: str, dimensions: int | None = None) -> List[float]:
        key = str(text or "")[:4000]
        with self._cache_lock:
            cached = self._query_cache.get(key)
            if cached is not None:
                self._query_cache.move_to_end(key)
                return list(cached)
        vecs = self.embed_documents([key])
        vec = vecs[0] if vecs else []
        if vec:
            with self._cache_lock:
                self._query_cache[key] = list(vec)
                while len(self._query_cache) > 256:
                    self._query_cache.popitem(last=False)
        return vec


def _load_db_embedding_provider() -> OpenAICompatibleDBEmbeddingProvider | None:
    global _DB_EMBEDDING_CHECKED_AT, _DB_EMBEDDING_CACHE
    now = time.monotonic()
    if now - _DB_EMBEDDING_CHECKED_AT < 30.0:
        return _DB_EMBEDDING_CACHE
    _DB_EMBEDDING_CHECKED_AT = now
    try:
        from database.core import get_db_connection
        from ai.security.crypto import decrypt_api_key

        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT m.model_code, p.id, p.name, p.base_url, p.api_key_encrypted, p.proxy_url
                FROM ai_model m
                JOIN ai_provider p ON p.id = m.provider_id
                WHERE LOWER(COALESCE(m.model_type, '')) = 'embedding'
                  AND m.enabled = 1 AND p.enabled = 1
                ORDER BY m.priority DESC, m.updated_at DESC
                LIMIT 1
                """
            ).fetchone()
        if not row or not row[0] or not row[3]:
            _DB_EMBEDDING_CACHE = None
            return None
        base_url = str(row[3]).rstrip("/")
        endpoint = base_url if base_url.endswith("/embeddings") else f"{base_url}/embeddings"
        api_key = decrypt_api_key(row[4], provider_id=str(row[1])) if row[4] else ""
        proxy_url = str(row[5]).strip() if row[5] else None
        _DB_EMBEDDING_CACHE = OpenAICompatibleDBEmbeddingProvider(
            model_code=str(row[0]),
            endpoint=endpoint,
            api_key=str(api_key or ""),
            provider_name=str(row[2] or "provider"),
            proxy_url=proxy_url,
        )
        return _DB_EMBEDDING_CACHE
    except Exception:
        _DB_EMBEDDING_CACHE = None
        return None


def semantic_embedding_provider() -> BaseEmbeddingProvider | None:
    """Configured semantic provider, or None when semantic vectors are off.

    ``AI_SEMANTIC_EMBEDDING_PROVIDER``: ``auto``/``none`` (checks enabled DB
    embedding model first), ``off``/``disabled`` (strictly off), or ``sidecar``.
    """
    global _SEMANTIC_PROVIDER, _SEMANTIC_PROVIDER_KEY
    kind = str(os.environ.get("AI_SEMANTIC_EMBEDDING_PROVIDER", "auto") or "auto").strip().lower()
    if kind in {"off", "disabled"}:
        return None
    if kind in {"", "none", "auto"}:
        return _load_db_embedding_provider()
    if kind != "sidecar":
        raise EmbeddingProviderError("AI_SEMANTIC_EMBEDDING_PROVIDER must be 'auto', 'none', 'off', or 'sidecar'")
    key = tuple(
        str(os.environ.get(name, ""))
        for name in (
            "AI_EMBEDDING_SIDECAR_URL", "AI_SEMANTIC_EMBEDDING_MODEL", "AI_SEMANTIC_EMBEDDING_DIMENSIONS",
            "AI_SEMANTIC_EMBEDDING_VERSION", "AI_EMBEDDING_SIDECAR_TOKEN", "AI_EMBEDDING_ALLOWED_HOSTS",
        )
    )
    with _SEMANTIC_LOCK:
        if _SEMANTIC_PROVIDER is None or _SEMANTIC_PROVIDER_KEY != key:
            _SEMANTIC_PROVIDER = SidecarEmbeddingProvider()
            _SEMANTIC_PROVIDER_KEY = key
        return _SEMANTIC_PROVIDER


def semantic_embedding_status() -> dict[str, Any]:
    try:
        provider = semantic_embedding_provider()
    except EmbeddingProviderError:
        return {"provider": "invalid", "status": "misconfigured"}
    if provider is None:
        return {"provider": "none", "status": "disabled"}
    status = getattr(provider, "status", None)
    return status() if callable(status) else {"provider": type(provider).__name__, "status": "unknown"}


def rerank_documents(
    query: str,
    documents: Sequence[str],
    *,
    top_n: int | None = None,
    model: str | None = None,
    timeout_seconds: float = 5.0,
) -> list[dict[str, Any]] | None:
    """Rerank candidate passages via the configured OpenAI-compatible /rerank endpoint (e.g., SiliconFlow BAAI/bge-reranker-v2-m3).

    Returns a list of ``{"index": int, "relevance_score": float}`` sorted by
    descending relevance, or ``None`` when no compatible provider is configured
    or the call fails (callers gracefully fall back to the existing ranking).
    """
    if not query or len(documents) < 2:
        return None
    if str(os.environ.get("AI_RERANKER_ENABLED", "true")).strip().lower() in {"0", "false", "off", "disabled"}:
        return None
    provider = _load_db_embedding_provider()
    if provider is None:
        return None
    base = provider.endpoint
    if base.endswith("/embeddings"):
        rerank_url = base[: -len("/embeddings")] + "/rerank"
    else:
        rerank_url = base.rstrip("/") + "/rerank"
    rerank_model = str(model or os.environ.get("AI_RERANKER_MODEL") or "BAAI/bge-reranker-v2-m3").strip()
    headers = {"Content-Type": "application/json"}
    if getattr(provider, "_api_key", ""):
        headers["Authorization"] = f"Bearer {provider._api_key}"
    payload: dict[str, Any] = {
        "model": rerank_model,
        "query": str(query)[:1000],
        "documents": [str(doc or "")[:2000] for doc in documents],
    }
    if top_n is not None and top_n > 0:
        payload["top_n"] = min(int(top_n), len(documents))
    try:
        import httpx

        with httpx.Client(timeout=timeout_seconds, proxy=provider.proxy_url or None) as client:
            resp = client.post(rerank_url, headers=headers, json=payload)
        if resp.status_code != 200:
            return None
        results = resp.json().get("results")
        if not isinstance(results, list) or not results:
            return None
        ranked = [
            {
                "index": int(item["index"]),
                "relevance_score": float(item.get("relevance_score") or 0.0),
            }
            for item in results
            if isinstance(item, dict) and isinstance(item.get("index"), int)
        ]
        ranked.sort(key=lambda x: x["relevance_score"], reverse=True)
        return ranked or None
    except Exception:
        return None



_EMBEDDING_IDEMPOTENCY_CACHE: dict[str, list[float]] = {}
_EMBEDDING_IDEMPOTENCY_CACHE_MAX = 4096


def embedding_contract(provider: BaseEmbeddingProvider | None = None) -> EmbeddingContract:
    active = provider or embedding_provider
    return active.contract()


def embedding_metadata() -> dict[str, object]:
    """Return the immutable model contract persisted with every vector."""

    contract = embedding_contract()
    return {
        "embedding_model": contract.model_id,
        "embedding_dimensions": contract.dimensions,
        "embedding_version": contract.version,
        "embedding_mode": contract.mode,
        "embedding_contract_version": contract.contract_version,
    }


def assert_embedding_compatible(
    document_vectors: Iterable[Sequence[float]],
    *,
    expected_dimensions: int | None = None,
    allow_empty: bool = True,
) -> None:
    expected = int(expected_dimensions or getattr(embedding_provider, "dimensions", 0) or 0)
    if expected <= 0:
        raise EmbeddingProviderError("Embedding dimensions must be positive")
    for vector in document_vectors:
        if not vector and not allow_empty:
            raise EmbeddingProviderError("Empty embedding vector is not allowed")
        if vector and len(vector) != expected:
            raise EmbeddingProviderError(
                f"Embedding dimension mismatch: expected {expected}, got {len(vector)}"
            )


def assert_pgvector_column_compatible(
    cursor: Any,
    *,
    table: str = "ai_document_chunk",
    column: str = "embedding",
    expected_dimensions: int | None = None,
) -> None:
    """Fail closed when a real PostgreSQL vector(n) column disagrees.

    V1 uses a TEXT/JSON compatibility column, so the probe is a no-op for that
    legacy shape.  When a later migration promotes the column to pgvector, the
    typmod is inspected before the first write and a mismatch cannot be
    silently stored.
    """

    expected = int(expected_dimensions or getattr(embedding_provider, "dimensions", 0) or 0)
    if expected <= 0:
        raise EmbeddingProviderError("Embedding dimensions must be positive")
    try:
        cursor.execute(
            "SELECT format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relname = ? "
            "AND a.attname = ? AND NOT a.attisdropped",
            (table, column),
        )
        row = cursor.fetchone()
    except Exception as exc:
        raise EmbeddingProviderError("Unable to inspect pgvector column contract") from exc
    type_name = str((row or [""])[0] or "").lower()
    match = re.search(r"\bvector\((\d+)\)", type_name)
    if match and int(match.group(1)) != expected:
        raise EmbeddingProviderError(
            f"pgvector column dimension mismatch: expected {expected}, got {match.group(1)}"
        )


def embed_documents_batch(
    texts: Sequence[str],
    *,
    provider: BaseEmbeddingProvider | None = None,
    tenant_id: str = "tenant-default",
    task_id: str = "knowledge-ingestion",
    user_id: str | None = None,
    batch_size: int | None = None,
    max_retries: int = 2,
    rate_limit_per_second: float = 0.0,
    idempotency_namespace: str = "default",
    sleep_fn: Callable[[float], None] = time.sleep,
    cache: dict[str, list[float]] | None = None,
) -> List[List[float]]:
    """Embed a deterministic batch with retries, rate limiting and idempotency.

    The function never returns a partial batch: a provider error after all
    retries is raised before persistence can begin.  The cache key includes
    model/version/dimensions and the content hash, so a reindex run can safely
    replay identical input without duplicate external requests.
    """

    active = provider or embedding_provider
    values = [str(text or "") for text in texts]
    if not values:
        return []
    if any(not value.strip() for value in values):
        raise EmbeddingProviderError("Embedding input must not be empty")
    size = int(batch_size or getattr(active, "batch_size", 32) or 32)
    if size <= 0:
        raise EmbeddingProviderError("batch_size must be positive")
    retries = max(0, int(max_retries))
    interval = 1.0 / float(rate_limit_per_second) if rate_limit_per_second > 0 else 0.0
    idempotency_cache = cache if cache is not None else _EMBEDDING_IDEMPOTENCY_CACHE
    contract = embedding_contract(active)
    result: list[list[float] | None] = [None] * len(values)
    last_request_at = 0.0

    def key_for(text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{idempotency_namespace}:{contract.contract_version}:{digest}"

    for start in range(0, len(values), size):
        indexes = list(range(start, min(start + size, len(values))))
        missing_indexes = [index for index in indexes if key_for(values[index]) not in idempotency_cache]
        if missing_indexes:
            request_texts = [values[index] for index in missing_indexes]
            vectors: list[list[float]] | None = None
            last_error: Exception | None = None
            succeeded = False
            for attempt in range(retries + 1):
                if interval and last_request_at:
                    elapsed = time.monotonic() - last_request_at
                    if elapsed < interval:
                        sleep_fn(interval - elapsed)
                try:
                    kwargs = {
                        "tenant_id": tenant_id,
                        "task_id": task_id,
                        "user_id": user_id,
                        "idempotency_key": f"{idempotency_namespace}:{start}",
                    }
                    vectors = [list(vector) for vector in active.embed_documents(request_texts, **kwargs)]
                    last_request_at = time.monotonic()
                    if len(vectors) != len(request_texts):
                        raise EmbeddingProviderError("Embedding provider returned an unexpected batch size")
                    assert_embedding_compatible(vectors, expected_dimensions=contract.dimensions, allow_empty=False)
                    succeeded = True
                    break
                except Exception as exc:  # provider boundary; retry then expose a stable error
                    last_error = exc
                    if exc.__class__.__name__ == "SecurityBlocked":
                        break
                    if isinstance(exc, EmbeddingProviderError) and (
                        "dimension mismatch" in str(exc).lower()
                        or "empty embedding" in str(exc).lower()
                    ):
                        break
                    if attempt >= retries:
                        break
                    sleep_fn(min(0.5 * (2**attempt), 2.0))
            if not succeeded or vectors is None:
                if isinstance(last_error, EmbeddingProviderError) and (
                    "dimension mismatch" in str(last_error).lower()
                    or "empty embedding" in str(last_error).lower()
                ):
                    raise last_error
                if last_error is not None and last_error.__class__.__name__ == "SecurityBlocked":
                    raise last_error
                raise EmbeddingProviderError(f"Embedding batch failed after {retries + 1} attempts") from last_error
            for index, vector in zip(missing_indexes, vectors):
                key = key_for(values[index])
                idempotency_cache[key] = vector
                if len(idempotency_cache) > _EMBEDDING_IDEMPOTENCY_CACHE_MAX:
                    idempotency_cache.pop(next(iter(idempotency_cache)))
        for index in indexes:
            result[index] = list(idempotency_cache[key_for(values[index])])

    return [vector for vector in result if vector is not None]
