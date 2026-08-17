"""KUI-016 PostgreSQL RAG evaluation and regression result API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from services.knowledge_evaluation_service import (
    KnowledgeEvaluationError,
    get_evaluation_report,
    run_evaluation,
)


router = APIRouter(prefix="/knowledge-v2/evaluation", tags=["knowledge-v2-evaluation"])


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: str = Field(default="v1_baseline_postgresql", min_length=1, max_length=64)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KnowledgeEvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:  # pragma: no cover - defensive API boundary
        raise HTTPException(status_code=500, detail={"code": "EVAL_API_ERROR", "message": "Evaluation operation failed"}) from exc


@router.get("")
@router.get("/")
def api_get_evaluation(
    include_cases: bool = Query(default=True),
    user=require_permission("knowledge_source", "read"),
):
    return {"success": True, "data": _call(get_evaluation_report, user, include_cases=include_cases), "message": ""}


@router.post("/run")
def api_run_evaluation(
    payload: EvaluationRunRequest,
    user=require_permission("knowledge_source", "read"),
):
    if payload.suite != "v1_baseline_postgresql":
        raise HTTPException(status_code=422, detail={"code": "EVAL_SUITE_NOT_SUPPORTED", "message": "Evaluation suite is not supported"})
    return {"success": True, "data": _call(run_evaluation, user), "message": "PostgreSQL evaluation completed"}
