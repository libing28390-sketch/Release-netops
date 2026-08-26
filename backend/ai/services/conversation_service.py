"""Tenant-scoped conversation and task state for the V1 AI contract."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from database.core import get_db_connection
from ai.security.classification import DataLevel, classify_text
from ai.security.minimizer import minimize
from ai.security.tokenization import opaque_user_id, tokenize_text, token_vault


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


TASK_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "timeout", "budget_exceeded", "step_limit"})
TASK_ACTIVE_STATES = frozenset({"queued", "running", "cancelling"})


def _safe_message_content(content: str, *, tenant_id: str, scope_id: str, role: str = "user") -> str:
    text = str(content or "")[:200_000]
    findings = classify_text(text)
    if any(item.level >= DataLevel.L4_PROHIBITED for item in findings):
        raise ValueError("message contains prohibited secret or full configuration data")
    if any(item.level >= DataLevel.L3_SENSITIVE for item in findings):
        text = str(minimize(text, max_text_chars=8000))
    # Assistant output has already passed the outbound security gateway. Keep
    # its identifiers readable in persisted history so links, addresses, and
    # CLI examples remain useful after the in-memory token vault expires.
    if role == "assistant":
        return text
    return tokenize_text(text, tenant_id=tenant_id, task_id=scope_id, vault=token_vault)


def create_conversation(*, tenant_id: str, user_id: str, title: str | None = None, context_budget: int = 32768, selected_model_id: str | None = None, model_locked: bool = False) -> dict[str, Any]:
    conversation_id = f"conv_{uuid.uuid4().hex[:20]}"
    now = _now()
    with get_db_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO ai_conversations
                    (id, tenant_id, user_id_opaque, title, status, context_budget, selected_model_id, model_locked, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                """,
                (conversation_id, tenant_id, opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner"), (title or "")[:200], max(4096, min(int(context_budget), 131072)), selected_model_id, int(model_locked), now, now),
            )
        except Exception:
            conn.execute(
                "INSERT INTO ai_conversations (id, tenant_id, user_id_opaque, title, status, context_budget, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (conversation_id, tenant_id, opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner"), (title or "")[:200], max(4096, min(int(context_budget), 131072)), now, now),
            )
        conn.commit()
    return {"id": conversation_id, "tenant_id": tenant_id, "title": (title or "")[:200], "status": "active", "context_budget": max(4096, min(int(context_budget), 131072)), "selected_model_id": selected_model_id, "model_locked": model_locked, "created_at": now, "updated_at": now}


def list_conversations(*, tenant_id: str, user_id: str, page: int = 1, page_size: int = 20, include_archived: bool = False, search: str = "") -> dict[str, Any]:
    page = max(1, int(page)); page_size = max(1, min(int(page_size), 100))
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner")
    status_clause = "" if include_archived else " AND status = 'active'"
    normalized_search = str(search or "").strip()[:200]
    search_clause = ""
    search_params: list[Any] = []
    if normalized_search:
        search_clause = " AND (LOWER(COALESCE(title, '')) LIKE LOWER(?) OR EXISTS (SELECT 1 FROM ai_messages m WHERE m.conversation_id = ai_conversations.id AND LOWER(COALESCE(m.content_safe, '')) LIKE LOWER(?)))"
        pattern = f"%{normalized_search}%"
        search_params = [pattern, pattern]
    with get_db_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM ai_conversations WHERE tenant_id = ? AND user_id_opaque = ?{status_clause}{search_clause}", (tenant_id, opaque, *search_params)).fetchone()["c"]
        rows = conn.execute(
            f"SELECT id, tenant_id, title, status, context_budget, selected_model_id, model_locked, created_at, updated_at FROM ai_conversations WHERE tenant_id = ? AND user_id_opaque = ?{status_clause}{search_clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (tenant_id, opaque, *search_params, page_size, (page - 1) * page_size),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": int(total or 0), "page": page, "page_size": page_size, "search": normalized_search}


def _get_conversation(conn, conversation_id: str, *, tenant_id: str, user_id: str):
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner")
    return conn.execute("SELECT * FROM ai_conversations WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?", (conversation_id, tenant_id, opaque)).fetchone()


def _conversation_result(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "title": row["title"] or "",
        "status": row["status"],
        "context_budget": int(row["context_budget"] or 32768),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "selected_model_id": row["selected_model_id"] if "selected_model_id" in row.keys() else None,
        "model_locked": bool(row["model_locked"]) if "model_locked" in row.keys() and row["model_locked"] is not None else False,
    }


def set_conversation_model(*, conversation_id: str, tenant_id: str, user_id: str, model_id: str, locked: bool = True) -> dict[str, Any]:
    now = _now()
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        try:
            conn.execute("UPDATE ai_conversations SET selected_model_id = ?, model_locked = ?, updated_at = ? WHERE id = ?", (model_id, int(locked), now, conversation_id))
        except Exception as exc:
            raise RuntimeError("conversation model persistence requires m0139") from exc
        conn.commit()
        return _conversation_result(conn.execute("SELECT * FROM ai_conversations WHERE id = ?", (conversation_id,)).fetchone())


def rename_conversation(*, conversation_id: str, tenant_id: str, user_id: str, title: str) -> dict[str, Any]:
    normalized_title = str(title or "").strip()[:200] or "新对话"
    now = _now()
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        conn.execute("UPDATE ai_conversations SET title = ?, updated_at = ? WHERE id = ?", (normalized_title, now, conversation_id))
        conn.commit()
        row = conn.execute("SELECT id, tenant_id, title, status, context_budget, created_at, updated_at FROM ai_conversations WHERE id = ?", (conversation_id,)).fetchone()
    return _conversation_result(row)


def archive_conversation(*, conversation_id: str, tenant_id: str, user_id: str, archived: bool = True) -> dict[str, Any]:
    now = _now()
    status = "archived" if archived else "active"
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        conn.execute("UPDATE ai_conversations SET status = ?, updated_at = ? WHERE id = ?", (status, now, conversation_id))
        conn.commit()
        row = conn.execute("SELECT id, tenant_id, title, status, context_budget, created_at, updated_at FROM ai_conversations WHERE id = ?", (conversation_id,)).fetchone()
    return _conversation_result(row)


def delete_conversation(*, conversation_id: str, tenant_id: str, user_id: str) -> bool:
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        result = conn.execute("DELETE FROM ai_conversations WHERE id = ?", (conversation_id,))
        conn.commit()
    return bool(result.rowcount)


def clear_messages(*, conversation_id: str, tenant_id: str, user_id: str) -> dict[str, Any]:
    now = _now()
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        conn.execute("DELETE FROM ai_messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("UPDATE ai_conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
        row = conn.execute("SELECT id, tenant_id, title, status, context_budget, created_at, updated_at FROM ai_conversations WHERE id = ?", (conversation_id,)).fetchone()
    return _conversation_result(row)


def import_messages(*, conversation_id: str, tenant_id: str, user_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Safely migrate legacy browser messages into a server conversation.

    Only user/assistant messages are accepted. Every item goes through the
    classifier/minimizer; user content is tokenized while assistant content
    remains readable for links and copy/paste. Unsafe legacy items are skipped
    instead of being written in raw form.
    """
    imported = 0
    skipped = 0
    for item in list(messages or [])[:200]:
        role = str(item.get("role") or "")
        if role not in {"user", "assistant"}:
            skipped += 1
            continue
        try:
            append_message(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                role=role,
                content=str(item.get("content") or "")[:200_000],
            )
            imported += 1
        except ValueError:
            skipped += 1
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
    if not conversation:
        raise LookupError("conversation not found")
    return {"conversation": _conversation_result(conversation), "imported": imported, "skipped": skipped}


def append_message(*, conversation_id: str, tenant_id: str, user_id: str, role: str, content: str, citations: list[dict[str, Any]] | None = None, reasoning_internal: str | None = None, requested_model_id: str | None = None, actual_model_id: str | None = None, provider_id: str | None = None, route_reason: str | None = None, fallback_used: bool = False, execution_mode: str | None = None, external_egress: bool | None = None, input_tokens: int | None = None, output_tokens: int | None = None, latency_ms: int | None = None, token_source: str | None = None) -> dict[str, Any]:
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError("unsupported conversation role")
    safe_content = _safe_message_content(content, tenant_id=tenant_id, scope_id=conversation_id, role=role)
    allowed_execution_modes = {"local_knowledge", "local_operation", "provider_generated", "local_fallback", "legacy_unknown"}
    safe_execution_mode = execution_mode if execution_mode in allowed_execution_modes else None
    safe_input_tokens = max(0, int(input_tokens)) if input_tokens is not None else None
    safe_output_tokens = max(0, int(output_tokens)) if output_tokens is not None else None
    safe_latency_ms = max(0, int(latency_ms)) if latency_ms is not None else None
    safe_token_source = token_source if token_source in {"provider_reported", "estimated", "local_zero"} else None
    message_id = f"msg_{uuid.uuid4().hex[:20]}"
    now = _now()
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        next_seq = conn.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 AS n FROM ai_messages WHERE conversation_id = ?", (conversation_id,)).fetchone()["n"]
        token_count = max(1, len(safe_content) // 3)
        try:
            conn.execute(
                """
                INSERT INTO ai_messages
                    (id, conversation_id, sequence_no, role, content_safe, reasoning_internal, tool_calls_json, citations_json, token_count, requested_model_id, actual_model_id, provider_id, route_reason, fallback_used, execution_mode, external_egress, input_tokens, output_tokens, latency_ms, token_source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, conversation_id, int(next_seq), role, safe_content, (reasoning_internal or "")[:10000] or None, json.dumps(citations or [], ensure_ascii=False), token_count, requested_model_id, actual_model_id, provider_id, route_reason, int(fallback_used), safe_execution_mode, int(external_egress) if external_egress is not None else None, safe_input_tokens, safe_output_tokens, safe_latency_ms, safe_token_source, now),
            )
        except Exception:
            conn.execute(
                "INSERT INTO ai_messages (id, conversation_id, sequence_no, role, content_safe, reasoning_internal, tool_calls_json, citations_json, token_count, created_at) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)",
                (message_id, conversation_id, int(next_seq), role, safe_content, (reasoning_internal or "")[:10000] or None, json.dumps(citations or [], ensure_ascii=False), token_count, now),
            )
        conn.execute("UPDATE ai_conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
    return {"id": message_id, "conversation_id": conversation_id, "sequence_no": int(next_seq), "role": role, "content": safe_content, "citations": citations or [], "token_count": token_count, "execution_mode": safe_execution_mode, "external_egress": external_egress, "input_tokens": safe_input_tokens, "output_tokens": safe_output_tokens, "latency_ms": safe_latency_ms, "token_source": safe_token_source, "created_at": now}


def get_context(*, conversation_id: str, tenant_id: str, user_id: str, max_messages: int = 20) -> dict[str, Any]:
    max_messages = max(1, min(int(max_messages), 100))
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        try:
            rows = conn.execute(
                "SELECT id, sequence_no, role, content_safe, citations_json, token_count, requested_model_id, actual_model_id, provider_id, route_reason, fallback_used, execution_mode, external_egress, input_tokens, output_tokens, latency_ms, token_source, created_at FROM ai_messages WHERE conversation_id = ? ORDER BY sequence_no DESC LIMIT ?",
                (conversation_id, max_messages),
            ).fetchall()
        except Exception:
            rows = conn.execute(
                "SELECT id, sequence_no, role, content_safe, citations_json, token_count, created_at FROM ai_messages WHERE conversation_id = ? ORDER BY sequence_no DESC LIMIT ?",
                (conversation_id, max_messages),
            ).fetchall()
    items = []
    for row in reversed(rows):
        item = dict(row)
        try:
            item["citations"] = json.loads(item.pop("citations_json") or "[]")
        except Exception:
            item["citations"] = []
        # Conversation content is tokenized at rest. The caller has already
        # passed the tenant/user ownership check above, so resolve only the
        # exact token scope for this conversation before returning it to the
        # authorized UI or reusing it as model history.
        item["content"] = token_vault.resolve_text(
            item.pop("content_safe"),
            tenant_id=tenant_id,
            task_id=conversation_id,
        )
        if "external_egress" in item:
            item["external_egress"] = None if item["external_egress"] is None else bool(item["external_egress"])
        items.append(item)
    return {"conversation": _conversation_result(conversation), "messages": items}


def create_task(*, tenant_id: str, user_id: str, scene: str, conversation_id: str | None = None, max_steps: int = 8, max_tool_calls: int = 12, timeout_seconds: int = 300) -> dict[str, Any]:
    task_id = f"aitask_{uuid.uuid4().hex[:20]}"
    now = datetime.now(timezone.utc)
    with get_db_connection() as conn:
        if conversation_id and not _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id):
            raise LookupError("conversation not found")
        bounded_steps = max(1, min(int(max_steps), 100))
        bounded_tools = max(1, min(int(max_tool_calls), 200))
        deadline = (now + timedelta(seconds=max(1, min(int(timeout_seconds), 86400)))).isoformat()
        owner = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
        try:
            conn.execute(
                """
                INSERT INTO ai_tasks
                    (id, conversation_id, tenant_id, user_id_opaque, scene, state,
                     max_steps, max_tool_calls, deadline_at, cancel_requested,
                     current_steps, current_tool_calls, version, updated_at, created_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, 0, 0, 0, 0, ?, ?)
                """,
                (task_id, conversation_id, tenant_id, owner, str(scene)[:80], bounded_steps, bounded_tools, deadline, now.replace(microsecond=0).isoformat(), now.replace(microsecond=0).isoformat()),
            )
        except Exception:
            conn.rollback()
            conn.execute(
                """
                INSERT INTO ai_tasks
                    (id, conversation_id, tenant_id, user_id_opaque, scene, state, max_steps, max_tool_calls, deadline_at, created_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
                """,
                (task_id, conversation_id, tenant_id, owner, str(scene)[:80], bounded_steps, bounded_tools, deadline, now.replace(microsecond=0).isoformat()),
            )
        conn.commit()
    return {"id": task_id, "state": "queued", "scene": str(scene)[:80], "max_steps": bounded_steps, "max_tool_calls": bounded_tools, "deadline_at": deadline, "created_at": now.replace(microsecond=0).isoformat()}


def get_task(*, task_id: str, tenant_id: str, user_id: str) -> dict[str, Any] | None:
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    with get_db_connection() as conn:
        try:
            row = conn.execute("""SELECT id, conversation_id, scene, state, max_steps, max_tool_calls,
                                      current_steps, current_tool_calls, deadline_at, cancel_requested,
                                      started_at, finished_at, error_code, version, updated_at,
                                      cancel_requested_at, created_at
                               FROM ai_tasks
                               WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?""", (task_id, tenant_id, opaque)).fetchone()
        except Exception:
            conn.rollback()
            row = conn.execute("SELECT id, conversation_id, scene, state, max_steps, max_tool_calls, deadline_at, cancel_requested, started_at, finished_at, error_code, created_at FROM ai_tasks WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?", (task_id, tenant_id, opaque)).fetchone()
    return dict(row) if row else None


def request_cancel(*, task_id: str, tenant_id: str, user_id: str) -> bool:
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    now = _now()
    with get_db_connection() as conn:
        try:
            result = conn.execute(
                """UPDATE ai_tasks
                   SET cancel_requested = 1,
                       cancel_requested_at = COALESCE(cancel_requested_at, ?),
                       state = CASE WHEN state IN ('queued', 'running') THEN 'cancelling' ELSE state END,
                       updated_at = ?, version = COALESCE(version, 0) + 1
                   WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                     AND state IN ('queued', 'running', 'cancelling')""",
                (now, now, task_id, tenant_id, opaque),
            )
        except Exception:
            conn.rollback()
            result = conn.execute(
                "UPDATE ai_tasks SET cancel_requested = 1, state = CASE WHEN state IN ('queued', 'running') THEN 'cancelling' ELSE state END WHERE id = ? AND tenant_id = ? AND user_id_opaque = ? AND state IN ('queued', 'running', 'cancelling')",
                (task_id, tenant_id, opaque),
            )
        conn.commit()
        return bool(result.rowcount)


def claim_task(*, task_id: str, tenant_id: str, user_id: str) -> dict[str, Any] | None:
    """Atomically claim one queued task and return a private execution token."""
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    now = _now()
    token = f"exec_{uuid.uuid4().hex}"
    with get_db_connection() as conn:
        try:
            result = conn.execute(
                """UPDATE ai_tasks
                   SET state = 'running', started_at = COALESCE(started_at, ?),
                       execution_token = ?, updated_at = ?, version = COALESCE(version, 0) + 1
                   WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                     AND state = 'queued' AND COALESCE(cancel_requested, 0) = 0
                     AND (deadline_at IS NULL OR deadline_at > ?)""",
                (now, token, now, task_id, tenant_id, opaque, now),
            )
        except Exception as exc:
            conn.rollback()
            raise RuntimeError("task execution guards require m0147") from exc
        if not result.rowcount:
            # A queued task whose deadline elapsed is terminalized exactly once;
            # cancellation wins when both signals race.
            conn.execute(
                """UPDATE ai_tasks
                   SET state = CASE WHEN COALESCE(cancel_requested, 0) = 1 THEN 'cancelled' ELSE 'timeout' END,
                       finished_at = COALESCE(finished_at, ?),
                       error_code = CASE WHEN COALESCE(cancel_requested, 0) = 1 THEN 'TASK_CANCELLED' ELSE 'TASK_TIMEOUT' END,
                       updated_at = ?, version = COALESCE(version, 0) + 1
                   WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                     AND state IN ('queued', 'cancelling')
                     AND (COALESCE(cancel_requested, 0) = 1 OR (deadline_at IS NOT NULL AND deadline_at <= ?))""",
                (now, now, task_id, tenant_id, opaque, now),
            )
            conn.commit()
            return None
        conn.commit()
    return {"task_id": task_id, "execution_token": token, "state": "running", "started_at": now}


def reconcile_task(*, task_id: str, tenant_id: str, user_id: str) -> dict[str, Any] | None:
    """Apply cancellation/timeout terminal state with one atomic update."""
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    now = _now()
    with get_db_connection() as conn:
        try:
            conn.execute(
                """UPDATE ai_tasks
                   SET state = CASE WHEN COALESCE(cancel_requested, 0) = 1 THEN 'cancelled' ELSE 'timeout' END,
                       finished_at = COALESCE(finished_at, ?),
                       error_code = CASE WHEN COALESCE(cancel_requested, 0) = 1 THEN 'TASK_CANCELLED' ELSE 'TASK_TIMEOUT' END,
                       updated_at = ?, version = COALESCE(version, 0) + 1
                   WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                     AND state IN ('queued', 'running', 'cancelling')
                     AND (COALESCE(cancel_requested, 0) = 1 OR (deadline_at IS NOT NULL AND deadline_at <= ?))""",
                (now, now, task_id, tenant_id, opaque, now),
            )
        except Exception as exc:
            conn.rollback()
            raise RuntimeError("task execution guards require m0147") from exc
        conn.commit()
    return get_task(task_id=task_id, tenant_id=tenant_id, user_id=user_id)


def _consume_budget(*, task_id: str, tenant_id: str, user_id: str, execution_token: str, counter: str, limit_column: str, terminal_state: str, error_code: str) -> dict[str, Any] | None:
    if counter not in {"current_steps", "current_tool_calls"} or limit_column not in {"max_steps", "max_tool_calls"}:
        raise ValueError("unsupported task budget counter")
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    now = _now()
    with get_db_connection() as conn:
        try:
            result = conn.execute(
                f"""UPDATE ai_tasks
                    SET {counter} = COALESCE({counter}, 0) + 1,
                        state = CASE WHEN COALESCE({counter}, 0) + 1 >= {limit_column} THEN ? ELSE state END,
                        finished_at = CASE WHEN COALESCE({counter}, 0) + 1 >= {limit_column} THEN COALESCE(finished_at, ?) ELSE finished_at END,
                        error_code = CASE WHEN COALESCE({counter}, 0) + 1 >= {limit_column} THEN ? ELSE error_code END,
                        updated_at = ?, version = COALESCE(version, 0) + 1
                    WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                      AND state = 'running' AND execution_token = ?
                      AND COALESCE(cancel_requested, 0) = 0
                      AND (deadline_at IS NULL OR deadline_at > ?)
                      AND COALESCE({counter}, 0) < {limit_column}""",
                (terminal_state, now, error_code, now, task_id, tenant_id, opaque, execution_token, now),
            )
        except Exception as exc:
            conn.rollback()
            raise RuntimeError("task execution guards require m0147") from exc
        conn.commit()
    return get_task(task_id=task_id, tenant_id=tenant_id, user_id=user_id) if result.rowcount else reconcile_task(task_id=task_id, tenant_id=tenant_id, user_id=user_id)


def consume_task_step(*, task_id: str, tenant_id: str, user_id: str, execution_token: str) -> dict[str, Any] | None:
    return _consume_budget(task_id=task_id, tenant_id=tenant_id, user_id=user_id, execution_token=execution_token, counter="current_steps", limit_column="max_steps", terminal_state="step_limit", error_code="TASK_STEP_LIMIT")


def consume_task_tool_call(*, task_id: str, tenant_id: str, user_id: str, execution_token: str) -> dict[str, Any] | None:
    return _consume_budget(task_id=task_id, tenant_id=tenant_id, user_id=user_id, execution_token=execution_token, counter="current_tool_calls", limit_column="max_tool_calls", terminal_state="budget_exceeded", error_code="TASK_TOOL_LIMIT")


def complete_task(*, task_id: str, tenant_id: str, user_id: str, execution_token: str, result: str = "") -> bool:
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    now = _now()
    with get_db_connection() as conn:
        try:
            update = conn.execute(
                """UPDATE ai_tasks
                   SET state = 'completed', finished_at = ?, error_code = NULL,
                       updated_at = ?, version = COALESCE(version, 0) + 1
                   WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                     AND state = 'running' AND execution_token = ?
                     AND COALESCE(cancel_requested, 0) = 0
                     AND (deadline_at IS NULL OR deadline_at > ?)""",
                (now, now, task_id, tenant_id, opaque, execution_token, now),
            )
        except Exception as exc:
            conn.rollback()
            raise RuntimeError("task execution guards require m0147") from exc
        conn.commit()
    return bool(update.rowcount)


def fail_task(*, task_id: str, tenant_id: str, user_id: str, execution_token: str, error_code: str = "TASK_FAILED") -> bool:
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    now = _now()
    with get_db_connection() as conn:
        try:
            update = conn.execute(
                """UPDATE ai_tasks
                   SET state = 'failed', finished_at = ?, error_code = ?,
                       updated_at = ?, version = COALESCE(version, 0) + 1
                   WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?
                     AND state = 'running' AND COALESCE(cancel_requested, 0) = 0
                     AND execution_token = ?""",
                (now, str(error_code or "TASK_FAILED")[:120], now, task_id, tenant_id, opaque, execution_token),
            )
        except Exception as exc:
            conn.rollback()
            raise RuntimeError("task execution guards require m0147") from exc
        conn.commit()
    return bool(update.rowcount)
