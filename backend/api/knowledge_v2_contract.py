"""Canonical Knowledge Engine V2 API boundary manifest."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


router = APIRouter(prefix="/knowledge-v2", tags=["knowledge-v2-contract"])


@router.get("", response_model=dict[str, Any])
def knowledge_v2_contract() -> dict[str, Any]:
    """Expose the stable version boundary without touching tenant data."""
    return {
        "contract": "nxa.kb.v2",
        "version": "2.0",
        "canonical_prefix": "/api/v2/kb",
        "compatibility_prefix": "/api/knowledge-v2",
        "compatibility_policy": "read_and_write_alias_until_v2_cutover",
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
