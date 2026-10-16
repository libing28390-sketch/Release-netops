"""
Agent Runner Loop for executing multi-step Autonomous Reasoning and READ_ONLY Tool Calls
"""

from __future__ import annotations

import json
import uuid
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import ValidationError
from database.core import get_db_connection
from ai.gateway.exceptions import AISecurityBlockedException
from ai.gateway.llm_gateway import llm_gateway
from ai.tools.registry import tool_registry
from ai.security.classification import DataLevel, classify_text
from ai.security.sanitizer import sanitize_text
from ai.security.tokenization import token_vault, tokenize_text
from ai.security.tokenization import opaque_user_id
from ai.services.metrics import ai_metrics
from ai.schemas.tool import AgentResponse


class AgentNotFoundError(ValueError):
    """Raised when a requested Agent code is not registered and enabled."""


def _agent_json_candidate(content: Any) -> str:
    """Extract one bounded JSON object for strict AgentResponse validation."""

    text = str(content or "").strip()[:20_000]
    if not text:
        raise ValueError("agent response is empty")
    decoder = json.JSONDecoder()
    candidate = None
    for offset, char in enumerate(text):
        if char != "{":
            continue
        try:
            _value, end = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        candidate = text[offset:offset + end]
        try:
            AgentResponse.model_validate_json(candidate)
            return candidate
        except ValidationError:
            continue
    if candidate:
        return candidate
    raise ValueError("agent response is not a JSON object")


def _resolve_agent_id(agent_code: str) -> str:
    """Resolve the public Agent code to the primary key required by the FK."""

    code = str(agent_code or "").strip()
    if not code:
        raise AgentNotFoundError("Agent code is required")

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, enabled FROM ai_agent WHERE code = ? LIMIT 1",
            (code,),
        ).fetchone()

    if not row:
        raise AgentNotFoundError(f"Agent '{code}' is not registered")
    if not bool(row[1]):
        raise AgentNotFoundError(f"Agent '{code}' is disabled")
    return str(row[0])


def _safe_text(value: Any, *, tenant_id: str, task_id: str) -> str:
    text = str(value or "")[:200_000]
    findings = classify_text(text)
    if any(item.level >= DataLevel.L4_PROHIBITED for item in findings):
        raise ValueError("agent input contains prohibited data")
    if any(item.level >= DataLevel.L3_SENSITIVE for item in findings):
        raise ValueError("agent input contains sensitive data")
    return tokenize_text(sanitize_text(text), tenant_id=tenant_id, task_id=task_id, vault=token_vault)


def _resolve_agent_tokens(value: Any, *, tenant_id: str, task_id: str) -> Any:
    """Resolve only the current run's opaque tokens before local tool calls."""

    if isinstance(value, str):
        return token_vault.resolve_text(value, tenant_id=tenant_id, task_id=task_id)
    if isinstance(value, list):
        return [_resolve_agent_tokens(item, tenant_id=tenant_id, task_id=task_id) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_agent_tokens(item, tenant_id=tenant_id, task_id=task_id) for item in value)
    if isinstance(value, dict):
        return {
            key: _resolve_agent_tokens(item, tenant_id=tenant_id, task_id=task_id)
            for key, item in value.items()
        }
    return value


def _public_tool_descriptor(item: Dict[str, Any]) -> Dict[str, Any]:
    """Expose planning metadata and a bounded argument schema to the model."""

    descriptor = {
        key: item.get(key)
        for key in ("name", "description", "category", "risk_level", "read_only")
        if item.get(key) is not None
    }
    source_schema = item.get("input_schema")
    if isinstance(source_schema, dict):
        properties: dict[str, dict[str, Any]] = {}
        for property_name, property_schema in list((source_schema.get("properties") or {}).items())[:20]:
            if not isinstance(property_name, str) or not isinstance(property_schema, dict):
                continue
            schema_type = property_schema.get("type")
            if not isinstance(schema_type, str):
                any_of = property_schema.get("anyOf")
                schema_type = next(
                    (candidate.get("type") for candidate in (any_of or []) if isinstance(candidate, dict) and isinstance(candidate.get("type"), str)),
                    "string",
                )
            properties[property_name[:64]] = {"type": schema_type[:24]}
        descriptor["input_schema"] = {
            "type": str(source_schema.get("type") or "object")[:24],
            "required": [str(value)[:64] for value in (source_schema.get("required") or [])[:20] if value],
            "properties": properties,
        }
    return descriptor


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
        agent_code = str(agent_code or "").strip()
        agent_id = _resolve_agent_id(agent_code)
        now_iso = datetime.now(timezone.utc).isoformat()
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        tenant = tenant_id or "tenant-default"
        owner_opaque = opaque_user_id(user_id, tenant_id=tenant, task_id="agent-owner")
        max_steps = max(1, min(int(max_steps or 1), 50))
        max_tool_calls = max(1, min(int(max_tool_calls or 1), 200))
        timeout_seconds = max(5, min(int(timeout_seconds or 5), 3600))
        try:
            safe_question = _safe_text(question, tenant_id=tenant, task_id=run_id)
        except ValueError:
            return {
                "run_id": run_id,
                "agent_code": agent_code,
                "question": "",
                "status": "blocked",
                "steps": [],
                "final_result": "Agent input blocked by security policy",
                "error_code": "AI_SECURITY_POLICY_BLOCKED",
            }
        
        # 1. Save Run Record
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO ai_agent_run (id, agent_id, tenant_id, user_id_opaque, user_id, question, status, risk_level,
                                             max_steps, max_tool_calls, deadline_at, cancel_requested, started_at)
                    VALUES (?, ?, ?, ?, NULL, ?, 'running', 'R0', ?, ?, ?, 0, ?)
                    """,
                    (run_id, agent_id, tenant, owner_opaque, safe_question, max_steps, max_tool_calls,
                     (datetime.now(timezone.utc).timestamp() + timeout_seconds), now_iso)
                )
            except Exception:
                # Keep old V1 installations bootable while m0146 is being
                # applied; new installations always take the scoped branch.
                conn.rollback()
                cursor.execute(
                    """
                    INSERT INTO ai_agent_run (id, agent_id, user_id, question, status, risk_level,
                                             max_steps, max_tool_calls, deadline_at, cancel_requested, started_at)
                    VALUES (?, ?, ?, ?, 'running', 'R0', ?, ?, ?, 0, ?)
                    """,
                    (run_id, agent_id, user_id, safe_question, max_steps, max_tool_calls,
                     (datetime.now(timezone.utc).timestamp() + timeout_seconds), now_iso)
                )
            conn.commit()

        # Agents only receive the read-only catalogue. Write-capable tools can
        # be planned by the registry, but are never offered as an autonomous
        # next step without the separate approval/change-order flow.
        tools_catalog = [
            _public_tool_descriptor(item)
            for item in tool_registry.list_tools()
            if item.get("read_only") is True
        ]
        tools_prompt_str = json.dumps(tools_catalog, ensure_ascii=False)

        sys_prompt = (
            f"You are an Autonomous Network Troubleshooting Agent ('{agent_code}').\n"
            f"Available READ_ONLY Tools:\n{tools_prompt_str}\n\n"
            "Execution Workflow:\n"
            "If you need to execute a tool, reply ONLY with a JSON object: {\"action\": \"tool_call\", \"tool_name\": \"<name>\", \"arguments\": { ... }}\n"
            "Use the exact input_schema for the selected tool; never invent argument names. "
            "Do not repeat an identical tool call. If a tool returns an error or empty evidence, explain the gap and move to final_answer. "
            "You have a bounded tool budget, so after at most five useful tool calls you MUST synthesize a final answer from the evidence already returned.\n"
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
        error_code: str | None = None
        tool_call_signatures: set[str] = set()

        # Reserve the last trajectory slot for a bounded synthesis response.
        # Without this guard a model can spend every allowed step planning a
        # read-only call and leave the UI with STEP_LIMIT but no diagnosis.
        tool_step_limit = max_steps if max_steps <= 1 else max_steps - 1

        # Step Loop
        for step_no in range(1, tool_step_limit + 1):
            step_id = f"step_{uuid.uuid4().hex[:12]}"
            step_start = datetime.now(timezone.utc).isoformat()
            
            try:
                control = self._read_control(run_id, tenant_id=tenant, user_id_opaque=owner_opaque)
                if control.get("cancel_requested"):
                    run_status = "cancelled"
                    final_result = "Agent run cancelled by the requester"
                    break
                if control.get("deadline_at") and float(control["deadline_at"]) <= datetime.now(timezone.utc).timestamp():
                    run_status = "timeout"
                    final_result = "Agent run timed out"
                    break
                llm_res = await asyncio.wait_for(
                    llm_gateway.chat(scene="agent", messages=messages, response_format={"type": "json_object"}, user_id=user_id, tenant_id=tenant, task_id=run_id, data_classification="PUBLIC"),
                    timeout=timeout_seconds,
                )
                content = llm_res.get("content", "")
                
                parsed = AgentResponse.model_validate_json(_agent_json_candidate(content))
                action = parsed.action

                if action == "tool_call":
                    tool_calls += 1
                    if tool_calls > max_tool_calls:
                        run_status = "budget_exceeded"
                        final_result = "Agent tool-call budget exceeded"
                        break
                    t_name = parsed.tool_name
                    t_args = _resolve_agent_tokens(parsed.arguments, tenant_id=tenant, task_id=run_id)

                    # Do not waste a bounded step or duplicate external work
                    # on the exact same tool request. The model receives a
                    # stable error and can synthesize from the evidence it
                    # already has.
                    signature = json.dumps(
                        {"tool_name": t_name, "arguments": t_args},
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )[:20_000]
                    if signature in tool_call_signatures:
                        tool_res = {
                            "success": False,
                            "error_code": "AGENT_DUPLICATE_TOOL_CALL",
                            "message": "This exact read-only tool call was already executed; use the existing evidence and return final_answer.",
                        }
                    else:
                        tool_call_signatures.add(signature)
                        # Execute tool
                        tool_res = tool_registry.execute_tool(
                            t_name,
                            t_args,
                            tenant_id=tenant,
                            user_id=user_id,
                            permissions=permissions,
                            task_id=run_id,
                        )
                    step_finish = datetime.now(timezone.utc).isoformat()
                    
                    step_info = {
                        "step_no": step_no,
                        "step_type": "tool_call",
                        "tool_name": t_name,
                        "tool_input": {"keys": sorted(str(key) for key in t_args)},
                        "tool_output": tool_res,
                        "status": "success" if tool_res.get("success") else "error"
                    }
                    steps_executed.append(step_info)

                    self._persist_tool_evidence(
                        run_id=run_id,
                        tenant_id=tenant,
                        user_id_opaque=owner_opaque,
                        step_no=step_no,
                        tool_name=str(t_name or ""),
                        arguments=t_args,
                        result=tool_res,
                    )

                    # Save step to DB
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        try:
                            cursor.execute(
                                """
                                INSERT INTO ai_agent_step (id, run_id, tenant_id, user_id_opaque, step_no, step_type, tool_name, tool_input, tool_output, status, started_at, finished_at)
                                VALUES (?, ?, ?, ?, ?, 'tool_call', ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    step_id, run_id, tenant, owner_opaque, step_no, t_name, json.dumps({"keys": sorted(str(key) for key in t_args)}, ensure_ascii=False),
                                    json.dumps(tool_res, ensure_ascii=False), "success" if tool_res.get("success") else "error", step_start, step_finish
                                )
                            )
                        except Exception:
                            conn.rollback()
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
                    feedback = f"Tool '{t_name}' Output:\n{json.dumps(tool_res, ensure_ascii=False)}"
                    if not tool_res.get("success"):
                        feedback += "\nThis call was not successful. Do not repeat the same invalid call; use the exact schema or return a bounded final_answer with the evidence gap."
                    messages.append({"role": "user", "content": feedback})

                elif action == "final_answer":
                    final_result = sanitize_text(str(parsed.result or content or ""))
                    step_finish = datetime.now(timezone.utc).isoformat()
                    steps_executed.append({"step_no": step_no, "step_type": "final_answer", "output": final_result})
                    
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        try:
                            cursor.execute(
                                """
                                INSERT INTO ai_agent_step (id, run_id, tenant_id, user_id_opaque, step_no, step_type, tool_output, status, started_at, finished_at)
                                VALUES (?, ?, ?, ?, ?, 'final_answer', ?, 'success', ?, ?)
                                """,
                                (step_id, run_id, tenant, owner_opaque, step_no, final_result, step_start, step_finish)
                            )
                        except Exception:
                            conn.rollback()
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
            except AISecurityBlockedException as exc:
                run_status = "blocked"
                final_result = "Agent request blocked by security policy"
                error_code = str(getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"))[:64]
                break
            except asyncio.TimeoutError:
                run_status = "timeout"
                final_result = "Agent provider request timed out"
                break
            except Exception:
                run_status = "error"
                final_result = "Agent step execution failed"
                break

        if not final_result and run_status == "finished" and max_steps > 1:
            # Final synthesis is deliberately a separate provider turn but
            # does not authorize another tool call. It occupies the reserved
            # last trajectory slot and keeps max_steps a hard UI/audit bound.
            final_step_no = max_steps
            final_step_id = f"step_{uuid.uuid4().hex[:12]}"
            final_step_start = datetime.now(timezone.utc).isoformat()
            try:
                messages.append({
                    "role": "user",
                    "content": (
                        "Final synthesis required now. Do not call another tool. "
                        "Using only the evidence already returned, reply ONLY as "
                        "{\"action\": \"final_answer\", \"result\": \"...\"}. "
                        "If the evidence is insufficient, state that explicitly and list the missing evidence."
                    ),
                })
                llm_res = await asyncio.wait_for(
                    llm_gateway.chat(
                        scene="agent",
                        messages=messages,
                        response_format={"type": "json_object"},
                        user_id=user_id,
                        tenant_id=tenant,
                        task_id=run_id,
                        data_classification="PUBLIC",
                    ),
                    timeout=timeout_seconds,
                )
                parsed_final = AgentResponse.model_validate_json(_agent_json_candidate(llm_res.get("content", "")))
                if parsed_final.action != "final_answer":
                    raise ValueError("agent final synthesis returned a tool call")
                final_result = sanitize_text(str(parsed_final.result or ""))
                if not final_result:
                    raise ValueError("agent final synthesis is empty")
                final_step_finish = datetime.now(timezone.utc).isoformat()
                steps_executed.append({"step_no": final_step_no, "step_type": "final_answer", "output": final_result})
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    try:
                        cursor.execute(
                            """
                            INSERT INTO ai_agent_step (id, run_id, tenant_id, user_id_opaque, step_no, step_type, tool_output, status, started_at, finished_at)
                            VALUES (?, ?, ?, ?, ?, 'final_answer', ?, 'success', ?, ?)
                            """,
                            (final_step_id, run_id, tenant, owner_opaque, final_step_no, final_result, final_step_start, final_step_finish)
                        )
                    except Exception:
                        conn.rollback()
                        cursor.execute(
                            """
                            INSERT INTO ai_agent_step (id, run_id, step_no, step_type, tool_output, status, started_at, finished_at)
                            VALUES (?, ?, ?, 'final_answer', ?, 'success', ?, ?)
                            """,
                            (final_step_id, run_id, final_step_no, final_result, final_step_start, final_step_finish)
                        )
                    conn.commit()
            except AISecurityBlockedException as exc:
                run_status = "blocked"
                error_code = str(getattr(exc, "reason_code", "AI_SECURITY_BLOCKED"))[:64]
                final_result = "Agent request blocked by security policy"
            except asyncio.TimeoutError:
                run_status = "timeout"
                final_result = "Agent final synthesis timed out"
            except Exception:
                run_status = "step_limit"
                final_result = "Agent could not produce a final diagnosis from the collected evidence"

        if not final_result and run_status == "finished":
            run_status = "step_limit"
            final_result = "Agent step limit reached before a final answer"

        # Finalize Run Record
        finished_iso = datetime.now(timezone.utc).isoformat()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE ai_agent_run SET status = ?, finished_at = ?, final_result = ?
                    WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                    """,
                    (run_status, finished_iso, final_result, run_id, tenant, owner_opaque)
                )
            except Exception:
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
            "final_result": final_result,
            "error_code": error_code,
        }

    @staticmethod
    def _persist_tool_evidence(*, run_id: str, tenant_id: str, user_id_opaque: str, step_no: int, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        """Persist only bounded, already-sanitized tool/evidence projections."""
        tool_call_id = f"{run_id}_tool_{step_no}"
        output = result.get("output") if isinstance(result, dict) else {}
        output = output if isinstance(output, dict) else {}
        safe_input = {"keys": sorted(str(key) for key in (arguments or {}))[:50]}
        safe_result = {
            "success": bool(result.get("success")) if isinstance(result, dict) else False,
            "error_code": str(result.get("error_code") or "")[:120] if isinstance(result, dict) else "TOOL_EXECUTION_FAILED",
            "evidence_count": len(output.get("evidence") or []) if isinstance(output.get("evidence"), list) else 0,
        }
        with get_db_connection() as conn:
            try:
                conn.execute(
                    """INSERT INTO ai_tool_calls
                       (id, task_id, tenant_id, user_id_opaque, step_no, tool_name,
                        input_safe_json, result_safe_json, source, freshness, status,
                        policy_decision, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (tool_call_id, run_id, tenant_id, user_id_opaque, step_no, tool_name[:120],
                     json.dumps(safe_input, ensure_ascii=False), json.dumps(safe_result, ensure_ascii=False),
                     str(output.get("source") or "agent_tool")[:120], str(output.get("freshness") or "")[:120],
                     "success" if safe_result["success"] else "error", "allow" if safe_result["success"] else "deny", datetime.now(timezone.utc).isoformat()),
                )
                evidence_items = output.get("evidence") if isinstance(output.get("evidence"), list) else []
                for evidence in evidence_items[:50]:
                    if not isinstance(evidence, dict):
                        continue
                    conn.execute(
                        """INSERT INTO ai_evidence
                           (id, task_id, tool_call_id, tenant_id, user_id_opaque,
                            source_type, source_id, citation, fact_json, confidence, collected_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (f"{tool_call_id}_ev_{uuid.uuid4().hex[:8]}", run_id, tool_call_id, tenant_id, user_id_opaque,
                         str(evidence.get("source_type") or "tool")[:80], str(evidence.get("source_id") or "")[:160],
                         str(evidence.get("citation") or "")[:240], json.dumps({"keys": sorted(str(key) for key in evidence if key not in {"content", "raw"})[:30]}, ensure_ascii=False),
                         max(0.0, min(float(evidence.get("confidence") or 0), 1.0)), datetime.now(timezone.utc).isoformat()),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _read_control(run_id: str, *, tenant_id: str, user_id_opaque: str) -> dict[str, Any]:
        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT cancel_requested, deadline_at FROM ai_agent_run WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?",
                    (run_id, tenant_id, user_id_opaque),
                ).fetchone()
                return dict(row) if row else {}
        except Exception:
            return {}


agent_runner = AgentRunner()
