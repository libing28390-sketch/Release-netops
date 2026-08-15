"""
Agent Runner Loop for executing multi-step Autonomous Reasoning and READ_ONLY Tool Calls
"""

from __future__ import annotations

import json
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection
from ai.gateway.llm_gateway import llm_gateway
from ai.tools.registry import tool_registry
from ai.security.classification import DataLevel, classify_text
from ai.security.minimizer import minimize
from ai.security.sanitizer import sanitize_text
from ai.security.tokenization import token_vault, tokenize_text
from ai.services.metrics import ai_metrics


def _safe_text(value: Any, *, tenant_id: str, task_id: str) -> str:
    text = str(value or "")[:200_000]
    findings = classify_text(text)
    if any(item.level >= DataLevel.L4_PROHIBITED for item in findings):
        raise ValueError("agent input contains prohibited data")
    if any(item.level >= DataLevel.L3_SENSITIVE for item in findings):
        text = str(minimize(text, max_text_chars=8000))
    return tokenize_text(sanitize_text(text), tenant_id=tenant_id, task_id=task_id, vault=token_vault)


class AgentRunner:
    """Executes multi-step Agent reasoning loops and records step persistence."""

    async def run(
        self,
        agent_code: str,
        question: str,
        max_steps: int = 6,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        permissions: set[str] | None = None,
        max_tool_calls: int = 12,
        timeout_seconds: int = 180,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        tenant = tenant_id or "tenant-default"
        max_steps = max(1, min(int(max_steps or 1), 50))
        max_tool_calls = max(1, min(int(max_tool_calls or 1), 200))
        timeout_seconds = max(5, min(int(timeout_seconds or 5), 3600))
        try:
            safe_question = _safe_text(question, tenant_id=tenant, task_id=run_id)
        except ValueError:
            return {"run_id": run_id, "agent_code": agent_code, "question": "", "status": "blocked", "steps": [], "final_result": "Agent input blocked by security policy"}
        
        # 1. Save Run Record
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ai_agent_run (id, agent_id, user_id, question, status, risk_level,
                                         max_steps, max_tool_calls, deadline_at, cancel_requested, started_at)
                VALUES (?, ?, ?, ?, 'running', 'R0', ?, ?, ?, 0, ?)
                """,
                (run_id, agent_code, user_id, safe_question, max_steps, max_tool_calls,
                 (datetime.now(timezone.utc).timestamp() + timeout_seconds), now_iso)
            )
            conn.commit()

        tools_catalog = tool_registry.list_tools()
        tools_prompt_str = json.dumps(tools_catalog, ensure_ascii=False)

        sys_prompt = (
            f"You are an Autonomous Network Troubleshooting Agent ('{agent_code}').\n"
            f"Available READ_ONLY Tools:\n{tools_prompt_str}\n\n"
            "Execution Workflow:\n"
            "If you need to execute a tool, reply ONLY with a JSON object: {\"action\": \"tool_call\", \"tool_name\": \"<name>\", \"arguments\": { ... }}\n"
            "If you have gathered enough evidence, reply with JSON: {\"action\": \"final_answer\", \"result\": \"<your detailed summary>\"}"
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Troubleshooting Request: {safe_question}"}
        ]

        steps_executed = []
        final_result = ""
        tool_calls = 0
        run_status = "finished"

        # Step Loop
        for step_no in range(1, max_steps + 1):
            step_id = f"step_{uuid.uuid4().hex[:12]}"
            step_start = datetime.now(timezone.utc).isoformat()
            
            try:
                control = self._read_control(run_id)
                if control.get("cancel_requested"):
                    run_status = "cancelled"
                    final_result = "Agent run cancelled by the requester"
                    break
                if control.get("deadline_at") and float(control["deadline_at"]) <= datetime.now(timezone.utc).timestamp():
                    run_status = "timeout"
                    final_result = "Agent run timed out"
                    break
                llm_res = await asyncio.wait_for(
                    llm_gateway.chat(scene="agent", messages=messages, response_format={"type": "json_object"}, user_id=user_id, tenant_id=tenant, task_id=run_id),
                    timeout=timeout_seconds,
                )
                content = llm_res.get("content", "")
                
                clean_json = content.strip()
                if clean_json.startswith("```json"): clean_json = clean_json[7:]
                if clean_json.startswith("```"): clean_json = clean_json[3:]
                if clean_json.endswith("```"): clean_json = clean_json[:-3]
                
                parsed = json.loads(clean_json.strip())
                action = parsed.get("action")

                if action == "tool_call":
                    tool_calls += 1
                    if tool_calls > max_tool_calls:
                        run_status = "budget_exceeded"
                        final_result = "Agent tool-call budget exceeded"
                        break
                    t_name = parsed.get("tool_name")
                    t_args = parsed.get("arguments", {})
                    
                    # Execute tool
                    tool_res = tool_registry.execute_tool(t_name, t_args, tenant_id=tenant, user_id=user_id, permissions=permissions)
                    step_finish = datetime.now(timezone.utc).isoformat()
                    
                    step_info = {
                        "step_no": step_no,
                        "tool_name": t_name,
                        "tool_input": {"keys": sorted(str(key) for key in t_args)},
                        "tool_output": tool_res,
                        "status": "success" if tool_res.get("success") else "error"
                    }
                    steps_executed.append(step_info)

                    # Save step to DB
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO ai_agent_step (id, run_id, step_no, step_type, tool_name, tool_input, tool_output, status, started_at, finished_at)
                            VALUES (?, ?, ?, 'tool_call', ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                step_id, run_id, step_no, t_name, json.dumps({"keys": sorted(str(key) for key in t_args)}, ensure_ascii=False),
                                json.dumps(tool_res, ensure_ascii=False), "success" if tool_res.get("success") else "error", step_start, step_finish
                            )
                        )
                        conn.commit()

                    # Feed tool output back to agent history
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Tool '{t_name}' Output:\n{json.dumps(tool_res, ensure_ascii=False)}"})

                elif action == "final_answer" or "result" in parsed:
                    final_result = sanitize_text(str(parsed.get("result", content) or ""))
                    step_finish = datetime.now(timezone.utc).isoformat()
                    steps_executed.append({"step_no": step_no, "step_type": "final_answer", "output": final_result})
                    
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            INSERT INTO ai_agent_step (id, run_id, step_no, step_type, tool_output, status, started_at, finished_at)
                            VALUES (?, ?, ?, 'final_answer', ?, 'success', ?, ?)
                            """,
                            (step_id, run_id, step_no, final_result, step_start, step_finish)
                        )
                        conn.commit()
                    break
                else:
                    final_result = sanitize_text(content)
                    break
            except asyncio.TimeoutError:
                run_status = "timeout"
                final_result = "Agent provider request timed out"
                break
            except Exception:
                run_status = "error"
                final_result = "Agent step execution failed"
                break

        if not final_result and run_status == "finished" and len(steps_executed) >= max_steps:
            run_status = "step_limit"
            final_result = "Agent step limit reached before a final answer"

        # Finalize Run Record
        finished_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE ai_agent_run SET status = ?, finished_at = ?, final_result = ?
                WHERE id = ?
                """,
                (run_status, finished_iso, final_result, run_id)
            )
            conn.commit()

        ai_metrics.agent_finished(run_status)

        return {
            "run_id": run_id,
            "agent_code": agent_code,
            "question": safe_question,
            "status": run_status,
            "steps": steps_executed,
            "final_result": final_result
        }

    @staticmethod
    def _read_control(run_id: str) -> dict[str, Any]:
        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT cancel_requested, deadline_at FROM ai_agent_run WHERE id = ?",
                    (run_id,),
                ).fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}


agent_runner = AgentRunner()
