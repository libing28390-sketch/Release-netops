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
from typing import Iterable, List, Sequence


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider is unavailable or incompatible."""


class BaseEmbeddingProvider:
    """Provider interface shared by document and query embedding paths."""

    model_id = "base"
    dimensions = 1536
    version = "v1"
    mode = "provider"

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [self.embed_text(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_text(text)

    def embed_text(self, text: str, dimensions: int | None = None) -> List[float]:
        raise NotImplementedError


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


def embedding_metadata() -> dict[str, object]:
    """Return the immutable model contract persisted with every vector."""

    return {
        "embedding_model": getattr(embedding_provider, "model_id", "unknown"),
        "embedding_dimensions": int(getattr(embedding_provider, "dimensions", 0) or 0),
        "embedding_version": getattr(embedding_provider, "version", "unknown"),
        "embedding_mode": getattr(embedding_provider, "mode", "provider"),
    }


def assert_embedding_compatible(document_vectors: Iterable[Sequence[float]]) -> None:
    expected = int(getattr(embedding_provider, "dimensions", 0) or 0)
    for vector in document_vectors:
        if vector and len(vector) != expected:
            raise EmbeddingProviderError(
                f"Embedding dimension mismatch: expected {expected}, got {len(vector)}"
            )
