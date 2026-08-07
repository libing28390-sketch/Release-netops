"""
Abstract Embedding Provider for vectorizing text chunks
"""

from __future__ import annotations

import math
from typing import List, Optional


class BaseEmbeddingProvider:
    """Base class for generating vector embeddings."""

    def embed_text(self, text: str, dimensions: int = 1536) -> List[float]:
        """Simple deterministic fallback vector embedding when OpenAI/bge embedding is offline."""
        if not text:
            return [0.0] * dimensions
        
        # Simple hash-seeded pseudo embedding for testing / fallback
        vec = []
        for i in range(dimensions):
            val = math.sin(hash(text + str(i)) % 10000)
            vec.append(round(val, 6))
        return vec


embedding_provider = BaseEmbeddingProvider()
