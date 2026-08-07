"""
Agent Runner Loop for executing multi-step Autonomous Reasoning and READ_ONLY Tool Calls
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection
from ai.gateway.llm_gateway import llm_gateway
from ai.tools.registry import tool_registry


class AgentRunner:
    """Executes multi-step Agent reasoning loops and records step persistence."""

    async def run(
        self,
        agent_code: str,
        question: str,
        max_steps: int = 6,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        
        # 1. Save Run Record
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ai_agent_run (id, agent_id, user_id, question, status, risk_level, started_at)
                VALUES (?, ?, ?, ?, 'running', 'R0', ?)
                """,
                (run_id, agent_code, user_id, question, now_iso)
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
            {"role": "user", "content": f"Troubleshooting Request: {question}"}
        ]

        steps_executed = []
        final_result = ""

        # Step Loop
        for step_no in range(1, max_steps + 1):
            step_id = f"step_{uuid.uuid4().hex[:12]}"
            step_start = datetime.now(timezone.utc).isoformat()
            
            try:
                llm_res = await llm_gateway.chat(scene="agent", messages=messages, response_format={"type": "json_object"}, user_id=user_id)
                content = llm_res.get("content", "")
                
                clean_json = content.strip()
                if clean_json.startswith("```json"): clean_json = clean_json[7:]
                if clean_json.startswith("```"): clean_json = clean_json[3:]
                if clean_json.endswith("```"): clean_json = clean_json[:-3]
                
                parsed = json.loads(clean_json.strip())
                action = parsed.get("action")

                if action == "tool_call":
                    t_name = parsed.get("tool_name")
                    t_args = parsed.get("arguments", {})
                    
                    # Execute tool
                    tool_res = tool_registry.execute_tool(t_name, t_args)
                    step_finish = datetime.now(timezone.utc).isoformat()
                    
                    step_info = {
                        "step_no": step_no,
                        "tool_name": t_name,
                        "tool_input": t_args,
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
                                step_id, run_id, step_no, t_name, json.dumps(t_args, ensure_ascii=False),
                                json.dumps(tool_res, ensure_ascii=False), "success", step_start, step_finish
                            )
                        )
                        conn.commit()

                    # Feed tool output back to agent history
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Tool '{t_name}' Output:\n{json.dumps(tool_res, ensure_ascii=False)}"})

                elif action == "final_answer" or "result" in parsed:
                    final_result = parsed.get("result", content)
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
                    final_result = content
                    break
            except Exception as exc:
                final_result = f"Agent step execution error: {exc}"
                break

        # Finalize Run Record
        finished_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE ai_agent_run SET status = 'finished', finished_at = ?, final_result = ?
                WHERE id = ?
                """,
                (finished_iso, final_result, run_id)
            )
            conn.commit()

        return {
            "run_id": run_id,
            "agent_code": agent_code,
            "question": question,
            "status": "finished",
            "steps": steps_executed,
            "final_result": final_result
        }


agent_runner = AgentRunner()
