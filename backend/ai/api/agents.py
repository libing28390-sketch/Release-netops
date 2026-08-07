"""
FastAPI Router for Tool Registry, Agent Execution & Step Trace
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from database.core import get_db_connection
from ai.security.permissions import require_ai_permission
from ai.tools.registry import tool_registry
from ai.agents.runner import agent_runner

router = APIRouter(prefix="/agents", tags=["AI Agents & Tools"])


class AgentRunRequest(BaseModel):
    agent_code: str = Field("troubleshooting_agent", description="Agent code identifier")
    question: str = Field(..., description="Troubleshooting problem description")
    max_steps: int = Field(6, ge=1, le=15)


@router.get("/tools")
def list_registered_tools(user=Depends(require_ai_permission("ai.view"))):
    """List all registered tools in Nexora Tool Registry."""
    return tool_registry.list_tools()


@router.post("/run")
async def run_agent(req: AgentRunRequest, user=Depends(require_ai_permission("ai.agent.use"))):
    """Execute Multi-step READ_ONLY Autonomous Agent Loop."""
    user_id = user.get("username", "user")
    return await agent_runner.run(
        agent_code=req.agent_code,
        question=req.question,
        max_steps=req.max_steps,
        user_id=user_id
    )


@router.get("/runs/{run_id}/trace")
def get_agent_run_trace(run_id: str, user=Depends(require_ai_permission("ai.view"))):
    """Get step-by-step execution trace for an Agent run."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, agent_id, question, status, started_at, finished_at, final_result FROM ai_agent_run WHERE id = ?", (run_id,))
        run_row = cursor.fetchone()
        if not run_row:
            raise HTTPException(status_code=404, detail=f"Agent run '{run_id}' not found.")
        
        cursor.execute(
            """
            SELECT step_no, step_type, tool_name, tool_input, tool_output, status, started_at, finished_at
            FROM ai_agent_step WHERE run_id = ? ORDER BY step_no ASC
            """,
            (run_id,)
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

        return {
            "run_id": run_row[0],
            "agent_id": run_row[1],
            "question": run_row[2],
            "status": run_row[3],
            "started_at": run_row[4],
            "finished_at": run_row[5],
            "final_result": run_row[6],
            "steps": steps
        }
