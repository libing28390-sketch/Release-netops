"""Nexora Independent BGE Reranker Sidecar Service.

Standalone microservice exposing standard reranking endpoints:
- GET  /health
- POST /v1/rerank

Designed to run in an isolated container/process without polluting the main NetOps process.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, List, Optional

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class CandidateItem(BaseModel if HAS_FASTAPI else object):
    candidate_id: str = Field(..., min_length=1, max_length=160) if HAS_FASTAPI else ""
    text: str = Field(..., min_length=1, max_length=12_000) if HAS_FASTAPI else ""
    metadata: Optional[dict[str, Any]] = None


class RerankRequest(BaseModel if HAS_FASTAPI else object):
    query: str = Field(..., min_length=1, max_length=4_096) if HAS_FASTAPI else ""
    candidates: List[CandidateItem] = Field(..., min_items=1, max_items=100) if HAS_FASTAPI else []
    top_n: Optional[int] = Field(default=None, ge=1, le=100) if HAS_FASTAPI else None


class RerankResultItem(BaseModel if HAS_FASTAPI else object):
    candidate_id: str = Field(..., min_length=1, max_length=160) if HAS_FASTAPI else ""
    score: float = Field(..., ge=0.0, le=1.0) if HAS_FASTAPI else 0.0
    rank: int = Field(..., ge=1, le=100) if HAS_FASTAPI else 1


class RerankResponse(BaseModel if HAS_FASTAPI else object):
    model: str
    results: List[RerankResultItem]
    latency_ms: int


class RerankerEngine:
    def __init__(self) -> None:
        self.model_name = os.environ.get("BGE_MODEL_NAME", "BAAI/bge-reranker-base")
        self.device = os.environ.get("BGE_DEVICE", "cpu")
        self.reranker = None
        self.is_real_model = False

        # 尝试加载真正的 FlagEmbedding 模型（如果环境中已安装）
        try:
            from FlagEmbedding import FlagReranker
            self.reranker = FlagReranker(self.model_name, use_fp16=(self.device != "cpu"))
            self.is_real_model = True
        except Exception:
            # 轻量/本地回退评分引擎：基于精确词法与网络领域关键词相关性
            self.reranker = None
            self.is_real_model = False

    def score_pair(self, query: str, text: str) -> float:
        if self.is_real_model and self.reranker:
            try:
                raw_score = self.reranker.compute_score([query, text])
                # 将 logit 转换到 0.0 ~ 1.0 范围
                import math
                return 1.0 / (1.0 + math.exp(-float(raw_score)))
            except Exception:
                pass

        # 确定性领域语义相关性评分回退
        q_tokens = set(re.findall(r"[a-z0-9_\-]+", query.lower()))
        t_tokens = set(re.findall(r"[a-z0-9_\-]+", text.lower()))
        if not q_tokens or not t_tokens:
            return 0.0
        overlap = len(q_tokens & t_tokens) / len(q_tokens)
        return min(1.0, max(0.0, overlap))

    def rerank(self, query: str, candidates: list[dict[str, Any]], top_n: int | None = None) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query or len(query) > 4_096:
            raise ValueError("query is empty or exceeds 4096 characters")
        if not candidates or len(candidates) > 100:
            raise ValueError("candidate count is outside the supported range")
        scored = []
        seen_ids: set[str] = set()
        for item in candidates:
            c_id = str(item.get("candidate_id") or "")
            text = str(item.get("text") or "")
            if not c_id or len(c_id) > 160 or c_id in seen_ids:
                raise ValueError("candidate IDs must be non-empty, bounded and unique")
            if not text or len(text) > 12_000:
                raise ValueError("candidate text is empty or exceeds 12000 characters")
            seen_ids.add(c_id)
            score = self.score_pair(query, text)
            scored.append({"candidate_id": c_id, "score": round(score, 4)})

        # 按重排分由高到低排序
        scored.sort(key=lambda x: x["score"], reverse=True)
        limit = min(top_n, len(scored)) if top_n and top_n > 0 else len(scored)
        results = []
        for rank, item in enumerate(scored[:limit], start=1):
            results.append({
                "candidate_id": item["candidate_id"],
                "score": item["score"],
                "rank": rank,
            })
        return results


engine = RerankerEngine()

if HAS_FASTAPI:
    from fastapi import Header, HTTPException, Response, status

    app = FastAPI(title="Nexora BGE Reranker Sidecar", version="1.0.0")

    def _verify_auth(x_internal_token: str | None = Header(default=None)):
        expected_key = os.environ.get("BGE_API_KEY", "").strip()
        if not expected_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Internal token is not configured",
            )
        if x_internal_token != expected_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")

    @app.get("/health")
    def health_check():
        return {
            "status": "ready" if engine.is_real_model else "degraded",
            "model": engine.model_name,
            "device": engine.device,
            "is_real_model": engine.is_real_model,
            "engine": "bge_flagembedding" if engine.is_real_model else "lexical_fallback",
        }

    @app.get("/ready")
    def readiness_check(response: Response):
        if not engine.is_real_model:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "ready": False,
                "reason": "FlagEmbedding model not loaded, running in degraded lexical fallback mode",
            }
        return {"ready": True, "model": engine.model_name}

    @app.post("/v1/rerank", response_model=RerankResponse)
    def rerank_endpoint(
        request: RerankRequest,
        x_internal_token: str | None = Header(default=None),
    ):
        _verify_auth(x_internal_token)
        started = time.perf_counter()
        candidates_dict = [c.dict() if hasattr(c, "dict") else c.__dict__ for c in request.candidates]
        results = engine.rerank(request.query, candidates_dict, request.top_n)
        latency = int((time.perf_counter() - started) * 1000)
        return {
            "model": engine.model_name,
            "results": results,
            "latency_ms": latency,
        }


def run_standalone(host: str = "127.0.0.1", port: int = 8004):
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_standalone()
