"""KUI-016 PostgreSQL RAG evaluation and regression result API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from core.rbac import require_permission
from services.knowledge_evaluation_service import (
    KnowledgeEvaluationError,
    get_gold_400_fixture_summary,
    get_evaluation_report,
    run_evaluation,
)
from ai.services.ai_experiment_service import ExperimentPersistenceError, get_experiment_observability


router = APIRouter(prefix="/knowledge/evaluation", tags=["knowledge-evaluation"])


class EvaluationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: str = Field(default="v1_baseline_postgresql", min_length=1, max_length=64)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KnowledgeEvaluationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    except ExperimentPersistenceError as exc:
        raise HTTPException(status_code=503, detail={"code": "EVAL_OBSERVABILITY_UNAVAILABLE", "message": "Experiment observability is unavailable"}) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail={"code": "EVAL_OBSERVABILITY_NOT_FOUND", "message": "Experiment observability was not found"}) from exc
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


@router.get("/fixtures/gold-400")
def api_get_gold_400_fixture_summary(
    user=require_permission("knowledge_source", "read"),
):
    """Expose aggregate fixture metadata without exposing evaluation answers."""

    return {"success": True, "data": _call(get_gold_400_fixture_summary, user), "message": ""}


@router.get("/observability")
def api_get_experiment_observability(
    limit: int = Query(default=50, ge=1, le=100),
    user=require_permission("knowledge_source", "read"),
):
    tenant_id = str(user.get("tenant_id") or "tenant-default")[:128]
    return {
        "success": True,
        "data": _call(get_experiment_observability, tenant_id=tenant_id, limit=limit),
        "message": "",
    }
