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
import time
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


embedding_provider: BaseEmbeddingProvider = StableLocalEmbeddingProvider()

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
        # SQLite and legacy adapters have no pg_catalog; compatibility mode is
        # validated by the vector length guard above.  A real PostgreSQL
        # inspection failure must not be treated as a successful check.
        if "sqlite" in type(cursor).__module__.lower():
            return
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
