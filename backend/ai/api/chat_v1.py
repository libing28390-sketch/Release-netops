"""Stable V1 AI chat contract with normalized SSE events."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ai.gateway.exceptions import AIException, AISecurityBlockedException
from ai.gateway.llm_gateway import llm_gateway
from ai.security.permissions import require_ai_permission
from ai.services.conversation_service import (
    append_message,
    archive_conversation,
    clear_messages,
    create_conversation,
    create_task,
    delete_conversation,
    get_context,
    get_task,
    import_messages,
    list_conversations,
    rename_conversation,
    request_cancel,
)


router = APIRouter(prefix="/api/v1/ai", tags=["AI V1 Chat"])


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant|tool)$")
    content: str = Field(default="", max_length=200_000)
    name: str | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=100)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=131072)
    tools: list[dict[str, Any]] | None = Field(default=None, max_length=32)
    thinking: bool = False
    reasoning_effort: str | None = Field(default=None, pattern="^(low|medium|high)$")
    response_format: dict[str, Any] | None = None
    conversation_id: str | None = None


def _event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    user_id = str(user.get("username") or "anonymous")
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    messages = [item.model_dump(exclude_none=True) for item in payload.messages]
    if payload.conversation_id:
        try:
            context = get_context(conversation_id=payload.conversation_id, tenant_id=tenant_id, user_id=user_id)
            messages = [{"role": item["role"], "content": item["content"]} for item in context["messages"]] + messages
            append_message(conversation_id=payload.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=payload.messages[-1].content)
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="conversation context is not available") from exc

    async def events():
        collected: list[str] = []
        yield _event("meta", {"contract": "nxa.ai.v1", "model": payload.model, "stream": True})
        try:
            async for token in llm_gateway.chat_stream(
                scene="chat",
                messages=messages,
                model_id=payload.model,
                temperature=payload.temperature,
                max_tokens=payload.max_tokens,
                user_id=user_id,
                tenant_id=tenant_id,
                tools=payload.tools,
                response_format=payload.response_format,
                thinking=payload.thinking,
                reasoning_effort=payload.reasoning_effort,
            ):
                if token:
                    collected.append(token)
                    yield _event("token", {"content": token})
            if payload.conversation_id and collected:
                try:
                    append_message(conversation_id=payload.conversation_id, tenant_id=tenant_id, user_id=user_id, role="assistant", content="".join(collected))
                except (LookupError, ValueError):
                    # The provider response remains available; the failure is
                    # represented only as a stable event and never raw text.
                    yield _event("warning", {"code": "CONVERSATION_PERSIST_FAILED"})
            yield _event("done", {"finish_reason": "stop"})
        except AISecurityBlockedException as exc:
            yield _event("error", {"code": exc.code, "request_id": exc.request_id})
            yield _event("done", {"finish_reason": "security_blocked"})
        except AIException as exc:
            yield _event("error", {"code": exc.code, "request_id": exc.request_id})
            yield _event("done", {"finish_reason": "error"})
        except Exception:
            yield _event("error", {"code": "AI_INTERNAL_ERROR"})
            yield _event("done", {"finish_reason": "error"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/chat")
async def chat(payload: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    user_id = str(user.get("username") or "anonymous")
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    messages = [item.model_dump(exclude_none=True) for item in payload.messages]
    if payload.conversation_id:
        try:
            context = get_context(conversation_id=payload.conversation_id, tenant_id=tenant_id, user_id=user_id)
            messages = [{"role": item["role"], "content": item["content"]} for item in context["messages"]] + messages
            append_message(conversation_id=payload.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=payload.messages[-1].content)
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="conversation context is not available") from exc
    result = await llm_gateway.chat(
        scene="chat",
        messages=messages,
        model_id=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        tools=payload.tools,
        response_format=payload.response_format,
        thinking=payload.thinking,
        reasoning_effort=payload.reasoning_effort,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    if payload.conversation_id:
        try:
            append_message(conversation_id=payload.conversation_id, tenant_id=tenant_id, user_id=user_id, role="assistant", content=result.get("content", ""))
        except (LookupError, ValueError):
            pass
    return {
        "contract": "nxa.ai.v1",
        "content": result.get("content", ""),
        "tool_calls": result.get("tool_calls") or [],
        "finish_reason": result.get("finish_reason"),
        "usage": {"input_tokens": result.get("input_tokens", 0), "output_tokens": result.get("output_tokens", 0)},
        "request_id": result.get("request_id"),
    }


class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    context_budget: int = Field(default=32768, ge=4096, le=131072)


@router.post("/conversations")
def create_conversation_api(payload: ConversationCreateRequest, user=Depends(require_ai_permission("ai.assistant"))):
    return create_conversation(tenant_id=str(user.get("tenant_id") or "tenant-default"), user_id=str(user.get("username") or "anonymous"), title=payload.title, context_budget=payload.context_budget)


@router.get("/conversations")
def list_conversations_api(
    page: int = 1,
    page_size: int = 20,
    include_archived: bool = Query(False),
    user=Depends(require_ai_permission("ai.assistant")),
):
    return list_conversations(
        tenant_id=str(user.get("tenant_id") or "tenant-default"),
        user_id=str(user.get("username") or "anonymous"),
        page=page,
        page_size=page_size,
        include_archived=include_archived,
    )


@router.get("/conversations/{conversation_id}")
def get_conversation_api(conversation_id: str, user=Depends(require_ai_permission("ai.assistant"))):
    try:
        return get_context(conversation_id=conversation_id, tenant_id=str(user.get("tenant_id") or "tenant-default"), user_id=str(user.get("username") or "anonymous"))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


class ConversationRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ConversationArchiveRequest(BaseModel):
    archived: bool = True


@router.put("/conversations/{conversation_id}")
def rename_conversation_api(conversation_id: str, payload: ConversationRenameRequest, user=Depends(require_ai_permission("ai.assistant"))):
    try:
        return rename_conversation(
            conversation_id=conversation_id,
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            user_id=str(user.get("username") or "anonymous"),
            title=payload.title,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


@router.post("/conversations/{conversation_id}/archive")
def archive_conversation_api(conversation_id: str, payload: ConversationArchiveRequest, user=Depends(require_ai_permission("ai.assistant"))):
    try:
        return archive_conversation(
            conversation_id=conversation_id,
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            user_id=str(user.get("username") or "anonymous"),
            archived=payload.archived,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


@router.delete("/conversations/{conversation_id}")
def delete_conversation_api(conversation_id: str, user=Depends(require_ai_permission("ai.assistant"))):
    try:
        delete_conversation(
            conversation_id=conversation_id,
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            user_id=str(user.get("username") or "anonymous"),
        )
        return {"id": conversation_id, "deleted": True}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


@router.delete("/conversations/{conversation_id}/messages")
def clear_conversation_messages_api(conversation_id: str, user=Depends(require_ai_permission("ai.assistant"))):
    try:
        return clear_messages(
            conversation_id=conversation_id,
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            user_id=str(user.get("username") or "anonymous"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


class ConversationImportRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1, max_length=200)


@router.post("/conversations/{conversation_id}/messages/import")
def import_conversation_messages_api(conversation_id: str, payload: ConversationImportRequest, user=Depends(require_ai_permission("ai.assistant"))):
    try:
        return import_messages(
            conversation_id=conversation_id,
            tenant_id=str(user.get("tenant_id") or "tenant-default"),
            user_id=str(user.get("username") or "anonymous"),
            messages=[item.model_dump() for item in payload.messages],
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


class TaskCreateRequest(BaseModel):
    scene: str = Field(..., min_length=1, max_length=80)
    conversation_id: str | None = None
    max_steps: int = Field(default=8, ge=1, le=100)
    max_tool_calls: int = Field(default=12, ge=1, le=200)
    timeout_seconds: int = Field(default=300, ge=1, le=86400)


@router.post("/tasks")
def create_task_api(payload: TaskCreateRequest, user=Depends(require_ai_permission("ai.assistant"))):
    return create_task(tenant_id=str(user.get("tenant_id") or "tenant-default"), user_id=str(user.get("username") or "anonymous"), scene=payload.scene, conversation_id=payload.conversation_id, max_steps=payload.max_steps, max_tool_calls=payload.max_tool_calls, timeout_seconds=payload.timeout_seconds)


@router.get("/tasks/{task_id}")
def get_task_api(task_id: str, user=Depends(require_ai_permission("ai.assistant"))):
    result = get_task(task_id=task_id, tenant_id=str(user.get("tenant_id") or "tenant-default"), user_id=str(user.get("username") or "anonymous"))
    if not result:
        raise HTTPException(status_code=404, detail="task not found")
    return result


@router.post("/tasks/{task_id}/cancel")
def cancel_task_api(task_id: str, user=Depends(require_ai_permission("ai.assistant"))):
    ok = request_cancel(task_id=task_id, tenant_id=str(user.get("tenant_id") or "tenant-default"), user_id=str(user.get("username") or "anonymous"))
    if not ok:
        raise HTTPException(status_code=404, detail="task not found")
    return {"id": task_id, "state": "cancelling"}
