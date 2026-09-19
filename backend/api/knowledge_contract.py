"""Canonical Knowledge Engine V1 API boundary manifest."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


router = APIRouter(prefix="/knowledge", tags=["knowledge-contract"])


@router.get("", response_model=dict[str, Any])
def knowledge_contract() -> dict[str, Any]:
    """Expose the single supported Knowledge Engine boundary."""
    return {
        "contract": "nxa.kb.v1",
        "version": "1.0",
        "canonical_prefix": "/api/knowledge",
        "compatibility_prefix": None,
        "compatibility_policy": "single_supported_boundary",
        "v1_ai_prefix": "/api/v1/ai",
        "v1_ai_contract": "nxa.ai.v1",
        "resource_groups": [
            "sources",
            "documents",
            "catalog",
            "collections",
            "ingestion",
            "evaluation",
            "retrieval-traces",
        ],
        "request_id_header": "X-Request-ID",
    }
