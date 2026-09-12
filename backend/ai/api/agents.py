"""
FastAPI Router for Tool Registry, Agent Execution & Step Trace
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from database.core import get_db_connection
from ai.security.permissions import ROLE_AI_PERMISSIONS, require_ai_permission
from ai.tools.registry import tool_registry
from ai.agents.runner import AgentNotFoundError, agent_runner
from ai.security.tokenization import opaque_user_id

router = APIRouter(prefix="/agents", tags=["AI Agents & Tools"])


class AgentRunRequest(BaseModel):
    agent_code: str = Field("troubleshooting_agent", description="Agent code identifier")
    question: str = Field(..., description="Troubleshooting problem description")
    max_steps: int = Field(6, ge=1, le=50)
    max_tool_calls: int = Field(12, ge=1, le=200)
    timeout_seconds: int = Field(180, ge=5, le=3600)


@router.get("/tools")
def list_registered_tools(user=Depends(require_ai_permission("ai.view"))):
    """List all registered tools in Nexora Tool Registry."""
    return tool_registry.list_tools()


@router.post("/run")
async def run_agent(req: AgentRunRequest, user=Depends(require_ai_permission("ai.agent.use"))):
    """Execute Multi-step READ_ONLY Autonomous Agent Loop."""
    user_id = str(user.get("username") or "user")
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    try:
        return await agent_runner.run(
            agent_code=req.agent_code,
            question=req.question,
            max_steps=req.max_steps,
            max_tool_calls=req.max_tool_calls,
            timeout_seconds=req.timeout_seconds,
            user_id=user_id,
            tenant_id=tenant_id,
            permissions=set(user.get("permissions") or ROLE_AI_PERMISSIONS.get(user.get("role", "Viewer"), set())),
        )
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
def cancel_agent_run(run_id: str, user=Depends(require_ai_permission("ai.agent.use"))):
    """Request cancellation; the runner observes it between provider/tool steps."""
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    owner_opaque = opaque_user_id(str(user.get("username") or "user"), tenant_id=tenant_id, task_id="agent-owner")
    with get_db_connection() as conn:
        row = conn.execute("SELECT id, status FROM ai_agent_run WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?", (run_id, tenant_id, owner_opaque)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Agent run '{run_id}' not found.")
        if row[1] in {"finished", "error", "cancelled", "timeout", "budget_exceeded", "step_limit"}:
            return {"run_id": run_id, "status": row[1], "cancel_requested": False}
        conn.execute("UPDATE ai_agent_run SET cancel_requested = 1 WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?", (run_id, tenant_id, owner_opaque))
        conn.commit()
    return {"run_id": run_id, "status": "cancelling", "cancel_requested": True}


@router.get("/runs/{run_id}/trace")
def get_agent_run_trace(run_id: str, user=Depends(require_ai_permission("ai.view"))):
    """Get step-by-step execution trace for an Agent run."""
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    owner_opaque = opaque_user_id(str(user.get("username") or "user"), tenant_id=tenant_id, task_id="agent-owner")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, agent_id, question, status, started_at, finished_at, final_result FROM ai_agent_run WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?",
            (run_id, tenant_id, owner_opaque),
        )
        run_row = cursor.fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail=f"Agent run '{run_id}' not found.")
        
        cursor.execute(
            """
            SELECT s.step_no, s.step_type, s.tool_name, s.tool_input, s.tool_output, s.status, s.started_at, s.finished_at
            FROM ai_agent_step s
            JOIN ai_agent_run r ON r.id = s.run_id
            WHERE s.run_id = ? AND r.tenant_id = ? AND r.user_id_opaque = ?
            ORDER BY s.step_no ASC
            """,
            (run_id, tenant_id, owner_opaque)
        )
        step_rows = cursor.fetchall()
        steps = []
        for s in step_rows:
            steps.append({
                "step_no": s[0],
                "step_type": s[1],
                "tool_name": s[2],
                "tool_input": json.loads(s[3]) if s[3] else None,
                "tool_output": json.loads(s[4]) if s[4] else None,
                "status": s[5],
                "started_at": s[6],
                "finished_at": s[7],
            })

        trace = {
            "run_id": run_row[0],
            "agent_id": run_row[1],
            "question": run_row[2],
            "status": run_row[3],
            "started_at": run_row[4],
            "finished_at": run_row[5],
            "final_result": run_row[6],
            "steps": steps
        }
        try:
            tool_rows = cursor.execute(
                """SELECT id, step_no, tool_name, status, policy_decision, source, freshness
                   FROM ai_tool_calls
                   WHERE task_id = ? AND tenant_id = ? AND user_id_opaque = ?
                   ORDER BY step_no ASC, id ASC""",
                (run_id, tenant_id, owner_opaque),
            ).fetchall()
            evidence_rows = cursor.execute(
                """SELECT id, tool_call_id, source_type, source_id, citation, confidence, collected_at
                   FROM ai_evidence
                   WHERE task_id = ? AND tenant_id = ? AND user_id_opaque = ?
                   ORDER BY collected_at ASC, id ASC""",
                (run_id, tenant_id, owner_opaque),
            ).fetchall()
            trace["tool_calls"] = [
                {"id": row[0], "step_no": row[1], "tool_name": row[2], "status": row[3], "policy_decision": row[4], "source": row[5], "freshness": row[6]}
                for row in tool_rows
            ]
            trace["evidence"] = [
                {"id": row[0], "tool_call_id": row[1], "source_type": row[2], "source_id": row[3], "citation": row[4], "confidence": row[5], "collected_at": row[6]}
                for row in evidence_rows
            ]
        except Exception:
            # Older V1 databases do not have the additive audit projections;
            # the scoped run/step trace remains available.
            trace["tool_calls"] = []
            trace["evidence"] = []
        return trace
