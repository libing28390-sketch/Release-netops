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


def _safe_message_content(content: str, *, tenant_id: str, scope_id: str) -> str:
    text = str(content or "")[:200_000]
    findings = classify_text(text)
    if any(item.level >= DataLevel.L4_PROHIBITED for item in findings):
        raise ValueError("message contains prohibited secret or full configuration data")
    if any(item.level >= DataLevel.L3_SENSITIVE for item in findings):
        text = str(minimize(text, max_text_chars=8000))
    return tokenize_text(text, tenant_id=tenant_id, task_id=scope_id, vault=token_vault)


def create_conversation(*, tenant_id: str, user_id: str, title: str | None = None, context_budget: int = 32768) -> dict[str, Any]:
    conversation_id = f"conv_{uuid.uuid4().hex[:20]}"
    now = _now()
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_conversations
                (id, tenant_id, user_id_opaque, title, status, context_budget, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (conversation_id, tenant_id, opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner"), (title or "")[:200], max(4096, min(int(context_budget), 131072)), now, now),
        )
        conn.commit()
    return {"id": conversation_id, "tenant_id": tenant_id, "title": (title or "")[:200], "status": "active", "context_budget": max(4096, min(int(context_budget), 131072)), "created_at": now, "updated_at": now}


def list_conversations(*, tenant_id: str, user_id: str, page: int = 1, page_size: int = 20, include_archived: bool = False) -> dict[str, Any]:
    page = max(1, int(page)); page_size = max(1, min(int(page_size), 100))
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id="conversation-owner")
    status_clause = "" if include_archived else " AND status = 'active'"
    with get_db_connection() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM ai_conversations WHERE tenant_id = ? AND user_id_opaque = ?{status_clause}", (tenant_id, opaque)).fetchone()["c"]
        rows = conn.execute(
            f"SELECT id, tenant_id, title, status, context_budget, created_at, updated_at FROM ai_conversations WHERE tenant_id = ? AND user_id_opaque = ?{status_clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (tenant_id, opaque, page_size, (page - 1) * page_size),
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": int(total or 0), "page": page, "page_size": page_size}


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
    }


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

    Only user/assistant messages are accepted.  Every item goes through the
    same classifier/minimizer/tokenizer as normal chat persistence; unsafe
    legacy items are skipped instead of being written in raw form.
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


def append_message(*, conversation_id: str, tenant_id: str, user_id: str, role: str, content: str, citations: list[dict[str, Any]] | None = None, reasoning_internal: str | None = None) -> dict[str, Any]:
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError("unsupported conversation role")
    safe_content = _safe_message_content(content, tenant_id=tenant_id, scope_id=conversation_id)
    message_id = f"msg_{uuid.uuid4().hex[:20]}"
    now = _now()
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
        next_seq = conn.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 AS n FROM ai_messages WHERE conversation_id = ?", (conversation_id,)).fetchone()["n"]
        token_count = max(1, len(safe_content) // 3)
        conn.execute(
            """
            INSERT INTO ai_messages
                (id, conversation_id, sequence_no, role, content_safe, reasoning_internal, tool_calls_json, citations_json, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
            """,
            (message_id, conversation_id, int(next_seq), role, safe_content, (reasoning_internal or "")[:10000] or None, json.dumps(citations or [], ensure_ascii=False), token_count, now),
        )
        conn.execute("UPDATE ai_conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
    return {"id": message_id, "conversation_id": conversation_id, "sequence_no": int(next_seq), "role": role, "content": safe_content, "citations": citations or [], "token_count": token_count, "created_at": now}


def get_context(*, conversation_id: str, tenant_id: str, user_id: str, max_messages: int = 20) -> dict[str, Any]:
    max_messages = max(1, min(int(max_messages), 100))
    with get_db_connection() as conn:
        conversation = _get_conversation(conn, conversation_id, tenant_id=tenant_id, user_id=user_id)
        if not conversation:
            raise LookupError("conversation not found")
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
        item["content"] = item.pop("content_safe")
        items.append(item)
    return {"conversation": _conversation_result(conversation), "messages": items}


def create_task(*, tenant_id: str, user_id: str, scene: str, conversation_id: str | None = None, max_steps: int = 8, max_tool_calls: int = 12, timeout_seconds: int = 300) -> dict[str, Any]:
    task_id = f"aitask_{uuid.uuid4().hex[:20]}"
    now = datetime.now(timezone.utc)
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO ai_tasks
                (id, conversation_id, tenant_id, user_id_opaque, scene, state, max_steps, max_tool_calls, deadline_at, created_at)
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)
            """,
            (task_id, conversation_id, tenant_id, opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id), str(scene)[:80], max(1, min(int(max_steps), 100)), max(1, min(int(max_tool_calls), 200)), (now + timedelta(seconds=max(1, min(int(timeout_seconds), 86400)))).isoformat(), now.replace(microsecond=0).isoformat()),
        )
        conn.commit()
    return {"id": task_id, "state": "queued", "scene": str(scene)[:80], "created_at": now.replace(microsecond=0).isoformat()}


def get_task(*, task_id: str, tenant_id: str, user_id: str) -> dict[str, Any] | None:
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    with get_db_connection() as conn:
        row = conn.execute("SELECT id, conversation_id, scene, state, max_steps, max_tool_calls, deadline_at, cancel_requested, started_at, finished_at, error_code, created_at FROM ai_tasks WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?", (task_id, tenant_id, opaque)).fetchone()
    return dict(row) if row else None


def request_cancel(*, task_id: str, tenant_id: str, user_id: str) -> bool:
    opaque = opaque_user_id(user_id, tenant_id=tenant_id, task_id=task_id)
    with get_db_connection() as conn:
        result = conn.execute("UPDATE ai_tasks SET cancel_requested = 1, state = CASE WHEN state IN ('queued', 'running') THEN 'cancelling' ELSE state END WHERE id = ? AND tenant_id = ? AND user_id_opaque = ?", (task_id, tenant_id, opaque))
        conn.commit()
        return bool(result.rowcount)
