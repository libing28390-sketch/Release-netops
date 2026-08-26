"""Read-only network diagnostic plan and execution endpoints for Copilot."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.security.security_service import ensure_diagnostic_case_access, persist_diagnostic_run
from services.diagnostic_orchestrator import (
    DiagnosticOrchestrationError,
    diagnostic_orchestrator,
    parse_cli_output,
)
from api.knowledge_v2_contracts import DiagnosticContext, DiagnosticPlanPayload

router = APIRouter(prefix="/diagnostics", tags=["AI Read-only Diagnostics"])


class DiagnosticPlanRequest(BaseModel):
    symptom: str = Field(..., min_length=1, max_length=1000)
    playbook: str = Field("unreachable", max_length=64)
    vendor: Optional[str] = Field(default=None, max_length=64)
    platform: Optional[str] = Field(default=None, max_length=64)
    target: str = Field(..., min_length=1, max_length=160)
    device_id: Optional[str] = Field(default=None, max_length=120)
    context: DiagnosticContext = Field(default_factory=DiagnosticContext)


class DiagnosticRunRequest(BaseModel):
    plan: DiagnosticPlanPayload
    authorized_steps: List[int] = Field(default_factory=list, max_length=20)
    context: DiagnosticContext = Field(default_factory=DiagnosticContext)


class PastedCliRequest(BaseModel):
    output: str = Field(..., min_length=1, max_length=200000)
    vendor: Optional[str] = Field(default=None, max_length=64)
    platform: Optional[str] = Field(default=None, max_length=64)
    purpose: str = Field("interface_status", max_length=64)


@router.post("/plan")
def create_diagnostic_plan(payload: DiagnosticPlanRequest, user=Depends(require_ai_permission("ai.diagnostics.run"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    cmdb_context: Dict[str, Any] = {}
    if payload.device_id:
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT d.id, d.tenant_id, d.hostname, d.site_id, d.site,
                       d.vendor, d.platform, d.model, d.version, d.os_version,
                       d.platform_profile_id, p.platform_code, p.parser_platform
                FROM devices d
                LEFT JOIN platform_profiles p ON p.id = d.platform_profile_id
                WHERE d.id = ? AND d.tenant_id = ?
                """,
                (str(payload.device_id), tenant_id),
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="device is outside the current tenant scope")
        cmdb_context = {
            "device_id": row[0],
            "site_id": row[3] or row[4],
            "vendor": row[5],
            "platform": row[6] or row[12] or row[11],
            "model": row[7],
            "version": row[8] or row[9],
            "source": "cmdb",
        }
    # CMDB is authoritative for identity/platform; user-supplied context may
    # add alert/topology/change hints but cannot override those fields.
    context = {**payload.context.model_dump(exclude_none=True), **cmdb_context}
    try:
        plan = diagnostic_orchestrator.build_plan(
            symptom=payload.symptom,
            playbook=payload.playbook,
            vendor=context.get("vendor") or payload.vendor,
            platform=context.get("platform") or payload.platform,
            target=payload.target,
            device_id=payload.device_id,
        )
        plan["context_sources"] = sorted({str(value) for value in (context.get("source"), "alerts" if context.get("alert_ids") else None, "topology" if context.get("topology_neighbors") else None, "changes" if context.get("recent_changes") else None) if value})
        plan["scope"] = {key: str(context[key])[:160] for key in ("device_id", "site_id", "model", "version") if context.get(key)}
        return plan
    except DiagnosticOrchestrationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code.value, "message": exc.user_message}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="unsupported diagnostic playbook") from exc


@router.post("/run")
async def run_diagnostic_plan(payload: DiagnosticRunRequest, user=Depends(require_ai_permission("ai.diagnostics.run"))):
    plan = payload.plan.model_dump(exclude_none=True)
    plan["tenant_id"] = str(user.get("tenant_id") or "tenant-default")
    user_id = str(user.get("username") or "anonymous")
    context = payload.context.model_dump(exclude_none=True)
    if context.get("case_id"):
        try:
            ensure_diagnostic_case_access(tenant_id=plan["tenant_id"], case_id=str(context["case_id"]), user_id=user_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="diagnostic case not found") from exc
    result = await diagnostic_orchestrator.run(plan=plan, authorized_steps=payload.authorized_steps, context=context)
    try:
        persist_diagnostic_run(
            tenant_id=plan["tenant_id"],
            user_id=user_id,
            case_id=payload.context.case_id,
            result=result,
            playbook_code=str(plan.get("playbook") or "unknown"),
            vendor=plan.get("vendor"), platform=plan.get("platform"), device_id=plan.get("device_id"),
        )
        result["persisted"] = True
    except Exception:
        # The read-only answer remains useful; the endpoint never reports
        # raw database details.  Operators can retry the same run safely.
        result["persisted"] = False
    return result


@router.post("/paste")
def parse_pasted_cli(payload: PastedCliRequest, user=Depends(require_ai_permission("ai.diagnostics.run"))):
    try:
        evidence = parse_cli_output(payload.output, vendor=payload.vendor, platform=payload.platform, purpose=payload.purpose)
        return {"status": "parsed", "read_only": True, "evidence": evidence, "external_call": False}
    except DiagnosticOrchestrationError as exc:
        return {"status": "failed", "error_code": exc.code.value, "user_message": exc.user_message, "external_call": False}
