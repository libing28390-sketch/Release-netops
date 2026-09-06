"""
FastAPI Router for AI Assistant Copilot, Natural Query, IP/MAC Location, and Knowledge Base
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field
from ai.gateway.exceptions import AISecurityBlockedException
from ai.security.classification import request_policy_findings
from ai.security.gateway import ai_security_gateway
from ai.security.permissions import require_ai_permission
from ai.services.assistant import (
    _SSE_CONTEXT as _ASSISTANT_SSE_CONTEXT,
    _SSEEventContext as _AssistantSSEEventContext,
    _done_event as _assistant_done_event,
    _sse_event as _assistant_sse_event,
    ai_assistant_service,
)
from ai.services.sse_stream_registry import (
    SSEStreamConflict,
    SSEStreamReplayExpired,
    event_payload,
    event_sequence,
    request_fingerprint,
    split_sse_events,
    sse_stream_registry,
)
from ai.services.intent_parser import intent_parser
from ai.security.sanitizer import sanitize_text
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.knowledge_service import KnowledgeDocumentActionError, knowledge_service
from ai.services.knowledge_export_service import (
    KnowledgeExportError,
    knowledge_export_service,
)
from ai.services.knowledge_bundle_import_service import (
    KnowledgeBundleImportError,
    import_knowledge_bundle,
)
from ai.services.metadata_confirmation_service import (
    MetadataConfirmationError,
    preview_document_metadata,
    validate_metadata_confirmation,
)
from ai.services.knowledge_reindex_service import knowledge_reindex_service
from ai.services.conversation_service import (
    ConversationSecurityError,
    append_message,
    clear_clarification_state,
    get_context,
    set_clarification_state,
    set_conversation_model,
)
from ai.security.security_service import (
    create_diagnostic_case,
    create_security_incident,
    handoff_case,
    record_feedback,
    record_security_event,
)
from api.knowledge_contracts import (
    ChatHistoryMessage,
    CopilotContext,
    CopilotPlanItem,
    KnowledgeBaseCreateRequest,
    KnowledgeDirectoryCreateRequest,
    KnowledgeDirectoryRenameRequest,
    KnowledgeDocumentCreateRequest,
    KnowledgeMetadataPreviewRequest,
    KnowledgeReindexRequest,
    SearchContract,
)
from api.knowledge_response import DOCUMENT_SUMMARY_FIELDS, PaginationMeta, attach_pagination, project_summary_items

router = APIRouter(prefix="/assistant", tags=["AI Copilot & Knowledge"])


_SECURITY_BLOCK_MESSAGE = "请求被安全策略拦截，未执行任何设备操作。请减少敏感内容后重试。"


def _security_block_result(*, request_id: str, code: str = "AI_SECURITY_SENSITIVE_DATA") -> dict[str, Any]:
    """Return a safe, stable response when history retention rejects user input."""

    return {
        "answer": _SECURITY_BLOCK_MESSAGE,
        "intent": "security_violation",
        "facts_retrieved": False,
        "citations": [],
        "request_id": request_id,
        "security_result": "blocked",
        "security": {"decision": "block", "result_code": code},
        "error_code": code,
        "execution_mode": "local_security_block",
        "external_egress": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "token_source": "local_zero",
        "fallback_used": False,
    }


async def _security_block_events(*, stream_state: Any, request_id: str, code: str) -> Any:
    """Emit a versioned SSE security decision without storing raw user input."""

    context_token = _ASSISTANT_SSE_CONTEXT.set(
        _AssistantSSEEventContext(stream_state.stream_id, request_id)
    )
    started_at = time.perf_counter()
    try:
        events = (
            _assistant_sse_event(
                "error",
                {
                    "code": code,
                    "message": _SECURITY_BLOCK_MESSAGE,
                    "retryable": False,
                },
            ),
            _assistant_done_event(
                started_at,
                extra={
                    "finish_reason": "security_blocked",
                    "security_result": "blocked",
                    "external_egress": False,
                    "execution_mode": "local_security_block",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "token_source": "local_zero",
                },
            ),
        )
        for event in events:
            if sse_stream_registry.record(stream_state, event):
                yield event
        sse_stream_registry.complete(stream_state)
    finally:
        if stream_state.active:
            sse_stream_registry.close(stream_state)
        _ASSISTANT_SSE_CONTEXT.reset(context_token)


def _security_block_stream_response(*, stream_state: Any, request_id: str, code: str) -> StreamingResponse:
    return StreamingResponse(
        _security_block_events(stream_state=stream_state, request_id=request_id, code=code),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Stream-ID": stream_state.stream_id,
        },
    )


def _request_security_block(*, message: str, tenant_id: str) -> tuple[str, list[str]] | None:
    """Return a stable block decision before local action or provider routing."""

    findings = request_policy_findings(
        [{"role": "user", "content": message}],
        tenant_id=tenant_id,
    )
    if not findings:
        return None
    return "AI_SECURITY_SENSITIVE_DATA", sorted({item.category for item in findings})


def _record_preflight_security_block(
    *,
    request_id: str,
    tenant_id: str,
    user_id: str,
    code: str,
    categories: list[str],
) -> None:
    """Persist metadata-only evidence for blocks made before model routing."""

    try:
        record_security_event(
            request_id=request_id or "-",
            tenant_id=tenant_id,
            user_id=user_id,
            policy_version=ai_security_gateway.policy.policy_version,
            classification="SECRET",
            data_region="unknown",
            decision="BLOCK",
            disposition="blocked",
            finding_categories=categories,
            error_code=code,
        )
        create_security_incident(
            tenant_id=tenant_id,
            incident_type="policy_violation",
            severity="high",
            category="gateway",
            task_id=request_id or "-",
            request_id=request_id or "-",
            evidence={
                "request_id": request_id or "-",
                "classification": "SECRET",
                "decision": "BLOCK",
                "error_code": code,
                "finding_categories": categories,
            },
        )
    except Exception:
        # The user-facing block is fail-closed even if a legacy deployment does
        # not yet have the extended audit tables.
        return


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_id: Optional[str] = Field(default=None, max_length=80)
    revision: Optional[int] = Field(default=None, ge=0, le=100_000)
    values: Dict[str, str] = Field(default_factory=dict, max_length=12)
    action: Literal["submit", "cancel"] = "submit"


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., description="User question or prompt")
    history: Optional[List[ChatHistoryMessage]] = None
    conversation_id: Optional[str] = None
    model_id: Optional[str] = None
    context: CopilotContext = Field(default_factory=CopilotContext)
    clarification: Optional[ClarificationAnswer] = None
    stream_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,128}$")
    last_event_id: Optional[int] = Field(default=None, ge=0, le=10_000_000)


class CopilotFeedbackRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=120)
    message_id: str = Field(..., min_length=1, max_length=120)
    rating: str = Field(..., pattern="^(positive|negative)$")
    reasons: List[str] = Field(default_factory=list, max_length=8)
    comment: str = Field(default="", max_length=500)


class DiagnosticCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=160)
    symptom: str = Field(default="", max_length=2000)
    conversation_id: Optional[str] = Field(default=None, max_length=120)
    context: CopilotContext = Field(default_factory=CopilotContext)
    plan: List[CopilotPlanItem] = Field(default_factory=list, max_length=20)


class DiagnosticHandoffRequest(BaseModel):
    summary: str = Field(default="", max_length=2000)
    assignee: str = Field(default="", max_length=120)
    ticket_draft: str = Field(default="", max_length=3000)


class IPLocationRequest(BaseModel):
    ip: str = Field(..., description="Target IP Address to trace")


class MACLocationRequest(BaseModel):
    mac: str = Field(..., description="Target MAC Address to trace")


class RetrievalTestRequest(SearchContract):
    """Admin search contract with an explicit allowlisted filter object."""


class KnowledgeBatchDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_ids: List[str] = Field(..., min_length=1, max_length=100)
    confirm: bool = Field(default=False, description="Explicit destructive-action confirmation")
    reason: str = Field(default="", max_length=1024)


class KnowledgeDocumentActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = Field(default=False, description="Explicit action confirmation")
    reason: str = Field(default="", max_length=1024)


def _sync_clarification_state(
    *,
    conversation_id: str | None,
    tenant_id: str,
    user_id: str,
    result: Dict[str, Any],
    pending: Dict[str, Any] | None,
    cancel_requested: bool = False,
) -> None:
    """Persist only the bounded policy result, retaining safe old state on errors."""

    if not conversation_id:
        return
    current = pending if isinstance(pending, dict) else {}
    expected_revision = current.get("revision")
    expected_state_id = current.get("state_id")
    clarification = result.get("clarification")
    try:
        if cancel_requested:
            clear_clarification_state(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                expected_revision=int(expected_revision) if expected_revision is not None else None,
                expected_state_id=str(expected_state_id) if expected_state_id else None,
            )
        elif isinstance(clarification, dict) and clarification.get("required"):
            persisted = set_clarification_state(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                state=clarification,
                expected_revision=int(expected_revision) if expected_revision is not None else None,
                expected_state_id=str(expected_state_id) if expected_state_id else None,
            )
            # The service canonicalizes the revision while holding the row
            # lock.  Keep the in-memory REST response consistent with it.
            result["clarification"] = persisted
            if isinstance(result.get("copilot"), dict):
                result["copilot"]["clarification"] = persisted
        elif current and str(result.get("intent") or ""):
            clear_clarification_state(
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                expected_revision=int(expected_revision) if expected_revision is not None else None,
                expected_state_id=str(expected_state_id) if expected_state_id else None,
            )
    except (LookupError, RuntimeError, ValueError):
        # A state write must not turn a valid read-only answer into a failed
        # request.  The next conversation load will expose the previous state
        # and the user can retry without losing knowledge content.
        return


from fastapi.responses import StreamingResponse
from core.context import request_id_var

@router.post("/chat")
async def chat_assistant(req: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """AI Assistant Copilot Chat Endpoint."""
    user_id = user.get("username", "user")
    tenant_id = user.get("tenant_id") or "tenant-default"
    request_id = request_id_var.get("-")
    history = [item.model_dump() for item in req.history] if req.history else None
    pending_clarification: Optional[Dict[str, Any]] = None
    clarification_response = req.clarification.model_dump(exclude_none=True) if req.clarification else None
    cancel_requested = bool(req.clarification and req.clarification.action == "cancel")
    requested_model_id = req.model_id
    model_selection_source = "message_explicit_model" if req.model_id else None
    request_security_block = _request_security_block(message=req.message, tenant_id=tenant_id)
    if request_security_block:
        request_security_code, categories = request_security_block
        _record_preflight_security_block(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=str(user_id),
            code=request_security_code,
            categories=categories,
        )
        return _security_block_result(request_id=request_id, code=request_security_code)
    if req.conversation_id:
        try:
            context = get_context(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id)
            history = [{"role": item["role"], "content": item["content"]} for item in context["messages"]]
            pending_clarification = context.get("conversation", {}).get("pending_clarification")
            if not requested_model_id and context.get("conversation", {}).get("selected_model_id"):
                requested_model_id = context["conversation"]["selected_model_id"]
                model_selection_source = "session_model"
            append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=req.message, requested_model_id=requested_model_id)
            if req.model_id:
                try:
                    set_conversation_model(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, model_id=req.model_id, locked=True)
                except (RuntimeError, LookupError):
                    pass
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except ConversationSecurityError as exc:
            return _security_block_result(
                request_id=request_id,
                code=getattr(exc, "code", "AI_SECURITY_SENSITIVE_DATA"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="message cannot be stored safely") from exc

    try:
        result = await ai_assistant_service.chat(
            req.message,
            history=history,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[str(user.get("role"))] if user.get("role") else [],
            site_ids=user.get("site_ids") or [],
            model_id=requested_model_id,
            model_selection_source=model_selection_source,
            context=req.context.model_dump(exclude_none=True),
            request_id=request_id_var.get("-"),
            pending_clarification=pending_clarification,
            clarification_response=clarification_response,
        )
    except AISecurityBlockedException as exc:
        return _security_block_result(
            request_id=exc.request_id or request_id,
            code=exc.code,
        )
    if req.conversation_id:
        _sync_clarification_state(
            conversation_id=req.conversation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            result=result,
            pending=pending_clarification,
            cancel_requested=cancel_requested,
        )
        try:
            append_message(
                conversation_id=req.conversation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                role="assistant",
                content=result.get("answer", ""),
                citations=result.get("citations") or [],
                requested_model_id=result.get("requested_model_id") or requested_model_id,
                actual_model_id=result.get("model_id"),
                provider_id=result.get("provider_id"),
                route_reason=result.get("route_reason"),
                fallback_used=bool(result.get("fallback_used")),
                execution_mode=result.get("execution_mode"),
                external_egress=result.get("external_egress"),
                input_tokens=result.get("input_tokens"),
                output_tokens=result.get("output_tokens"),
                latency_ms=result.get("latency_ms"),
                token_source=result.get("token_source"),
            )
        except (LookupError, ValueError):
            # Do not discard a valid model answer when the safe-history write
            # rejects provider output or the client disconnects during cleanup.
            pass
    return result


@router.post("/chat-stream")
async def chat_assistant_stream(req: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """AI Assistant Copilot Real-time Streaming SSE Endpoint."""
    user_id = str(user.get("username") or "user")
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    history = [item.model_dump() for item in req.history] if req.history else None
    pending_clarification: Optional[Dict[str, Any]] = None
    requested_model_id = req.model_id
    model_selection_source = "message_explicit_model" if req.model_id else None
    fingerprint = request_fingerprint(
        {
            "message": req.message,
            "history": history or [],
            "conversation_id": req.conversation_id,
            "model_id": req.model_id,
            "context": req.context.model_dump(exclude_none=True),
            "clarification": req.clarification.model_dump(exclude_none=True) if req.clarification else None,
        }
    )
    try:
        stream_state = sse_stream_registry.open(
            stream_id=req.stream_id,
            tenant_id=tenant_id,
            user_id=user_id,
            fingerprint=fingerprint,
            last_event_id=req.last_event_id or 0,
        )
    except SSEStreamConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": SSEStreamConflict.code, "message": "stream 已被其他请求占用或请求范围不一致"},
        ) from exc
    except SSEStreamReplayExpired as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": SSEStreamReplayExpired.code, "message": "stream 重连位置已超出保留窗口，请重新发起请求"},
        ) from exc

    if not stream_state.completed:
        request_security_block = _request_security_block(message=req.message, tenant_id=tenant_id)
        if request_security_block:
            request_security_code, categories = request_security_block
            _record_preflight_security_block(
                request_id=request_id_var.get("-") or "-",
                tenant_id=tenant_id,
                user_id=user_id,
                code=request_security_code,
                categories=categories,
            )
            return _security_block_stream_response(
                stream_state=stream_state,
                request_id=request_id_var.get("-") or "-",
                code=request_security_code,
            )

    if req.conversation_id and not stream_state.completed:
        try:
            context = get_context(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id)
            pending_clarification = context.get("conversation", {}).get("pending_clarification")
            context_messages = list(context["messages"])
            if stream_state.user_message_persisted and context_messages:
                last_message = context_messages[-1]
                if last_message.get("role") == "user" and last_message.get("content") == req.message:
                    context_messages = context_messages[:-1]
            history = [{"role": item["role"], "content": item["content"]} for item in context_messages]
            if not requested_model_id and context.get("conversation", {}).get("selected_model_id"):
                requested_model_id = context["conversation"]["selected_model_id"]
                model_selection_source = "session_model"
            if not stream_state.user_message_persisted:
                append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=req.message, requested_model_id=requested_model_id)
                stream_state.user_message_persisted = True
                if req.model_id:
                    try:
                        set_conversation_model(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, model_id=req.model_id, locked=True)
                    except (RuntimeError, LookupError):
                        pass
        except LookupError as exc:
            sse_stream_registry.close(stream_state)
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except ConversationSecurityError as exc:
            return _security_block_stream_response(
                stream_state=stream_state,
                request_id=request_id_var.get("-") or "-",
                code=getattr(exc, "code", "AI_SECURITY_SENSITIVE_DATA"),
            )
        except ValueError as exc:
            sse_stream_registry.close(stream_state)
            raise HTTPException(status_code=400, detail="message cannot be stored safely") from exc

    async def events():
        route_meta: dict[str, Any] = {}
        last_event_id = req.last_event_id or 0
        try:
            if stream_state.completed:
                for cached_event in sse_stream_registry.replay(stream_state, after=last_event_id):
                    yield cached_event.rstrip() + "\n\n"
                sse_stream_registry.close(stream_state)
                return

            async for event in ai_assistant_service.chat_stream(
                req.message,
                history=history,
                user_id=user_id,
                tenant_id=tenant_id,
                roles=[str(user.get("role"))] if user.get("role") else [],
                site_ids=user.get("site_ids") or [],
                model_id=requested_model_id,
                model_selection_source=model_selection_source,
                context=req.context.model_dump(exclude_none=True),
                stream_id=stream_state.stream_id,
                request_id=request_id_var.get("-"),
                pending_clarification=pending_clarification,
                clarification_response=req.clarification.model_dump(exclude_none=True) if req.clarification else None,
            ):
                for part in split_sse_events(event):
                    sequence = event_sequence(part)
                    was_new = sse_stream_registry.record(stream_state, part)
                    payload = event_payload(part)
                    if isinstance(payload, dict):
                        for key in (
                            "intent", "clarification", "requested_model_id", "model_id", "provider_id", "route_reason",
                            "fallback_used", "execution_mode", "external_egress", "input_tokens",
                            "output_tokens", "latency_ms", "duration_ms", "token_source",
                        ):
                            if key in payload and payload[key] is not None:
                                route_meta[key] = payload[key]
                    if sequence is None:
                        if was_new:
                            yield part.rstrip() + "\n\n"
                        continue
                    _, sequence_number = sequence
                    if sequence_number <= last_event_id:
                        continue
                    # A rerun after cancellation can regenerate a sequence
                    # already cached by the first attempt. Replay the cached
                    # bytes instead of appending a second token.
                    cached_event = stream_state.events.get(sequence_number, part)
                    yield cached_event.rstrip() + "\n\n"

            if req.conversation_id:
                _sync_clarification_state(
                    conversation_id=req.conversation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    result={
                        "intent": route_meta.get("intent"),
                        "clarification": route_meta.get("clarification"),
                    },
                    pending=pending_clarification,
                    cancel_requested=bool(req.clarification and req.clarification.action == "cancel"),
                )

            if req.conversation_id and stream_state.assistant_content and not stream_state.assistant_message_persisted:
                try:
                    append_message(
                        conversation_id=req.conversation_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        role="assistant",
                        content=stream_state.assistant_content,
                        requested_model_id=route_meta.get("requested_model_id") or requested_model_id,
                        actual_model_id=route_meta.get("model_id"),
                        provider_id=route_meta.get("provider_id"),
                        route_reason=route_meta.get("route_reason"),
                        fallback_used=bool(route_meta.get("fallback_used")),
                        execution_mode=route_meta.get("execution_mode"),
                        external_egress=route_meta.get("external_egress"),
                        input_tokens=route_meta.get("input_tokens"),
                        output_tokens=route_meta.get("output_tokens"),
                        latency_ms=route_meta.get("latency_ms") or route_meta.get("duration_ms"),
                        token_source=route_meta.get("token_source"),
                    )
                    stream_state.assistant_message_persisted = True
                except (LookupError, ValueError):
                    pass
            sse_stream_registry.complete(stream_state)
        finally:
            if stream_state.active:
                sse_stream_registry.close(stream_state)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "X-Stream-ID": stream_state.stream_id},
    )


@router.post("/feedback")
def submit_copilot_feedback(payload: CopilotFeedbackRequest, user=Depends(require_ai_permission("ai.copilot.feedback"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    try:
        return record_feedback(
            tenant_id=tenant_id,
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
            user_id=str(user.get("username") or "anonymous"),
            rating=payload.rating,
            reasons=payload.reasons,
            comment=payload.comment,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation message not found") from exc


@router.post("/cases")
def create_copilot_case(payload: DiagnosticCaseRequest, user=Depends(require_ai_permission("ai.assistant"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    try:
        return create_diagnostic_case(
            tenant_id=tenant_id,
            user_id=str(user.get("username") or "anonymous"),
            title=payload.title,
            symptom=payload.symptom,
            conversation_id=payload.conversation_id,
            scope=payload.context.model_dump(exclude_none=True),
            plan=[item.model_dump(exclude_none=True) for item in payload.plan],
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


@router.post("/cases/{case_id}/handoff")
def handoff_copilot_case(case_id: str, payload: DiagnosticHandoffRequest, user=Depends(require_ai_permission("ai.assistant"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    try:
        return handoff_case(
            tenant_id=tenant_id,
            case_id=case_id,
            user_id=str(user.get("username") or "anonymous"),
            handoff=payload.model_dump() if hasattr(payload, "model_dump") else payload.dict(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="diagnostic case not found") from exc


@router.post("/knowledge-retrieval-test")
def knowledge_retrieval_test(
    payload: RetrievalTestRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    """Admin-only retrieval inspection surface for RET-021.

    It returns normalized entities, server-owned hard filters, bounded resolver
    candidates, final chunk evidence and the redacted RET explanation object.
    It never returns provider credentials, raw SQL or unbounded document data.
    """

    tenant_id = str(user.get("tenant_id") or "tenant-default")
    user_id = str(user.get("username") or "")
    roles = [str(user.get("role"))] if user.get("role") else []
    metadata = intent_parser.parse_knowledge_metadata(payload.query)
    requested_filters = {
        key: value
        for key, value in payload.filters.model_dump(exclude_none=True).items()
        if key in {
            "knowledge_scope", "directory_path",
            "vendor", "product_family", "product_series", "product_model",
            "os_family", "os_generation", "software_train", "software_release",
            "cli_platform", "document_category", "feature_domain", "feature",
            "subfeature", "risk_level", "verification_level", "rag_priority",
            "applicability",
        }
    }
    metadata.update({key: value for key, value in requested_filters.items() if value not in (None, "", [], {})})
    result = ai_assistant_service.retrieve_knowledge(
        payload.query,
        {"knowledge_intent": metadata},
        tenant_id=tenant_id,
        user_id=user_id,
        roles=roles,
        site_ids=user.get("site_ids") or [],
        request_id=request_id_var.get("-"),
    )
    request = result.get("request")
    resolution = result.get("resolution")
    resolution_data = resolution.to_dict() if hasattr(resolution, "to_dict") else dict(resolution or {})
    results = result.get("results") or []
    final_chunks = [
        {
            "chunk_id": item.get("chunk_id"),
            "document_id": item.get("document_id"),
            "document_name": item.get("document_name"),
            "source": item.get("source"),
            "knowledge_source_type": item.get("knowledge_source_type"),
            "vendor": item.get("vendor"),
            "product_series": item.get("product_series"),
            "section": item.get("section"),
            "platform": item.get("platform"),
            "score": item.get("relevance_score"),
            "score_components": item.get("score_components"),
            "version_evidence": item.get("version_evidence"),
            "content": sanitize_text(str(item.get("content") or ""))[:12000],
            "context_chunk_ids": item.get("context_chunk_ids") or [],
        }
        for item in results[:20]
    ]
    return {
        "contract_version": "ret-admin-test-v1",
        "normalized_query": resolution_data.get("normalized_query"),
        "entities": resolution_data.get("metadata") or metadata,
        "filters": {
            key: getattr(request, key, value)
            for key, value in requested_filters.items()
        },
        "resolution": {
            "outcome": resolution_data.get("outcome"),
            "ambiguous": bool(resolution_data.get("ambiguous")),
            "candidates": resolution_data.get("candidates") or [],
            "platform_candidates": resolution_data.get("platform_candidates") or [],
            "match_method": resolution_data.get("match_method"),
            "match_score": resolution_data.get("match_score"),
        },
        "final_chunks": final_chunks,
        "explanation": result.get("explanation") or {},
        "debug": result.get("debug") or {},
        "request_id": result.get("request_id") or request_id_var.get("-"),
    }


@router.post("/ip-location")
async def locate_ip(req: IPLocationRequest, user=Depends(require_ai_permission("ai.use"))):
    """Intelligent IP Location & Troubleshooting Endpoint."""
    user_id = user.get("username", "user")
    tenant_id = user.get("tenant_id") or "tenant-default"
    return await ip_troubleshooting_service.troubleshoot_ip(
        req.ip,
        user_id=user_id,
        tenant_id=tenant_id,
    )


@router.post("/mac-location")
async def locate_mac(req: MACLocationRequest, user=Depends(require_ai_permission("ai.use"))):
    """Intelligent MAC Location Endpoint."""
    user_id = user.get("username", "user")
    tenant_id = user.get("tenant_id") or "tenant-default"
    return await mac_troubleshooting_service.troubleshoot_mac(
        req.mac,
        user_id=user_id,
        tenant_id=tenant_id,
    )


# --- Knowledge Base & Document Chunking Endpoints ---
@router.get("/knowledge-bases")
def list_knowledge_bases(user=Depends(require_ai_permission("ai.view"))):
    """List Knowledge Bases."""
    return knowledge_service.list_knowledge_bases(tenant_id=user.get("tenant_id") or "tenant-default")


@router.post("/knowledge-bases")
def create_knowledge_base(payload: KnowledgeBaseCreateRequest, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Create a new Knowledge Base."""
    return knowledge_service.create_knowledge_base(
        name=payload.name,
        description=payload.description,
        created_by=user.get("username", "admin"),
        tenant_id=user.get("tenant_id") or "tenant-default",
        acl=payload.acl,
    )


@router.get("/knowledge-stats")
def get_knowledge_stats(user=Depends(require_ai_permission("ai.view"))):
    """Get metrics on Total Documents, Chunks, Vendors, Ready Indexes."""
    return knowledge_service.get_knowledge_stats(tenant_id=user.get("tenant_id") or "tenant-default")


@router.get("/knowledge-options")
def get_knowledge_options(user=Depends(require_ai_permission("ai.view"))):
    """Return vendor/platform choices synchronized from network asset inventory."""
    return knowledge_service.list_asset_vendor_platform_options()


@router.post("/knowledge-reindex")
def start_knowledge_reindex(payload: KnowledgeReindexRequest | None = None, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Start a metadata/chunk/embedding reindex without deleting source docs."""
    payload = payload or KnowledgeReindexRequest()
    scope = {
        key: getattr(payload, key)
        for key in ("vendor", "directory_path", "document_id")
        if getattr(payload, key)
    }
    return knowledge_reindex_service.create_job(
        tenant_id=user.get("tenant_id") or "tenant-default",
        scope=scope,
        dry_run=payload.dry_run,
        run_async=payload.run_async,
        # DB-022 legacy marker: the former Dict boundary used
        # ``batch_size=payload.get(...)``; this typed boundary reads the
        # validated field directly with the same bounded semantics.
        batch_size=payload.batch_size,
    )


@router.get("/knowledge-reindex/{job_id}")
def get_knowledge_reindex_status(job_id: str, user=Depends(require_ai_permission("ai.view"))):
    status = knowledge_reindex_service.get_status(job_id)
    if not status or status.get("tenant_id") not in {user.get("tenant_id"), "tenant-default"}:
        raise HTTPException(status_code=404, detail="reindex job not found")
    return status


@router.post("/knowledge-reindex/{job_id}/retry")
def retry_knowledge_reindex(job_id: str, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    try:
        status = knowledge_reindex_service.get_status(job_id)
        if not status or status.get("tenant_id") not in {user.get("tenant_id"), "tenant-default"}:
            raise KeyError(job_id)
        return knowledge_reindex_service.retry(job_id, run_async=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="reindex job not found") from exc


@router.get("/knowledge-directories")
def list_knowledge_directories(user=Depends(require_ai_permission("ai.view"))):
    """Return the tenant's nested import directory tree."""
    tenant_id = user.get("tenant_id") or "tenant-default"
    knowledge_base = knowledge_service.get_or_create_default_knowledge_base(
        tenant_id=tenant_id,
        created_by=user.get("username", "admin"),
    )
    return knowledge_service.list_knowledge_directories(
        knowledge_base_id=knowledge_base["id"],
        tenant_id=tenant_id,
        created_by=user.get("username", "admin"),
    )


@router.post("/knowledge-directories")
def create_knowledge_directory(payload: KnowledgeDirectoryCreateRequest, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Create a root directory or a child below an existing directory."""
    tenant_id = user.get("tenant_id") or "tenant-default"
    try:
        knowledge_base = knowledge_service.get_or_create_default_knowledge_base(
            tenant_id=tenant_id,
            created_by=user.get("username", "admin"),
        )
        return knowledge_service.create_knowledge_directory(
            knowledge_base_id=knowledge_base["id"],
            name=payload.name,
            parent_id=payload.parent_id,
            tenant_id=tenant_id,
            created_by=user.get("username", "admin"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "KNOWLEDGE_DIRECTORY_INVALID", "message": "Knowledge directory name or parent is invalid"},
        ) from exc


@router.patch("/knowledge-directories/{directory_id}")
def rename_knowledge_directory(directory_id: str, payload: KnowledgeDirectoryRenameRequest, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Rename a directory and update descendant paths."""
    try:
        return knowledge_service.rename_knowledge_directory(
            directory_id=directory_id,
            name=payload.name,
            tenant_id=user.get("tenant_id") or "tenant-default",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "KNOWLEDGE_DIRECTORY_INVALID", "message": "Knowledge directory name or scope is invalid"},
        ) from exc


@router.delete("/knowledge-directories/{directory_id}")
def delete_knowledge_directory(directory_id: str, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Delete a directory subtree without deleting uploaded documents."""
    try:
        return knowledge_service.delete_knowledge_directory(
            directory_id=directory_id,
            tenant_id=user.get("tenant_id") or "tenant-default",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "KNOWLEDGE_DIRECTORY_NOT_FOUND", "message": "Knowledge directory was not found"},
        ) from exc


@router.get("/documents")
def list_documents(
    source_type: Optional[str] = Query(default=None, max_length=64),
    search: str = Query(default="", max_length=200),
    directory_path: Optional[str] = Query(default=None, max_length=500),
    knowledge_scope: Optional[str] = Query(default=None, max_length=32),
    vendor: str = Query(default="", max_length=128),
    product_family: str = Query(default="", max_length=256),
    product_series: str = Query(default="", max_length=256),
    product_model: str = Query(default="", max_length=256),
    os_family: str = Query(default="", max_length=128),
    os_generation: str = Query(default="", max_length=128),
    software_train: str = Query(default="", max_length=128),
    software_release: str = Query(default="", max_length=128),
    cli_platform: str = Query(default="", max_length=128),
    document_category: str = Query(default="", max_length=128),
    feature_domain: str = Query(default="", max_length=128),
    status: str = Query(default="active", max_length=32),
    source_trust_level: str = Query(default="", max_length=32),
    metadata_governance_status: str = Query(default="", max_length=32),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at", max_length=64),
    sort_order: str = Query(default="desc", pattern="^(?i:asc|desc)$"),
    user=Depends(require_ai_permission("ai.view")),
):
    """List documents with server-side filtering and pagination."""
    result = knowledge_service.list_documents(
        knowledge_source_type=source_type,
        directory_path=directory_path,
        knowledge_scope=knowledge_scope,
        search=search,
        vendor=vendor,
        product_family=product_family,
        product_series=product_series,
        product_model=product_model,
        os_family=os_family,
        os_generation=os_generation,
        software_train=software_train,
        software_release=software_release,
        cli_platform=cli_platform,
        document_category=document_category,
        feature_domain=feature_domain,
        status=status,
        source_trust_level=source_trust_level,
        metadata_governance_status=metadata_governance_status,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        tenant_id=user.get("tenant_id") or "tenant-default",
    )
    allowed_sort_fields = {"created_at", "name", "vendor", "platform", "status", "chunk_count"}
    normalized_sort = sort_by.strip().lower() if sort_by.strip().lower() in allowed_sort_fields else "created_at"
    normalized_order = "asc" if sort_order.strip().lower() == "asc" else "desc"
    return attach_pagination(
        project_summary_items(result, item_key="items", fields=DOCUMENT_SUMMARY_FIELDS),
        PaginationMeta(
            page=int(result.get("page") or 1),
            page_size=int(result.get("page_size") or page_size),
            total=int(result.get("total") or 0),
            total_pages=int(result.get("total_pages") or 1),
            sort_by=normalized_sort,
            sort_order=normalized_order,
        ),
        filters={
            "source_type": source_type, "search": search, "directory_path": directory_path,
            "knowledge_scope": knowledge_scope, "vendor": vendor, "product_family": product_family,
            "product_series": product_series, "product_model": product_model, "os_family": os_family,
            "os_generation": os_generation, "software_train": software_train, "software_release": software_release,
            "cli_platform": cli_platform, "document_category": document_category, "feature_domain": feature_domain,
            "status": status, "source_trust_level": source_trust_level,
            "metadata_governance_status": metadata_governance_status,
        },
    )


@router.get("/knowledge-export")
def export_knowledge_documents(
    source_type: Optional[str] = Query(default=None, max_length=64),
    search: str = Query(default="", max_length=200),
    directory_path: Optional[str] = Query(default=None, max_length=500),
    knowledge_scope: Optional[str] = Query(default=None, max_length=32),
    vendor: str = Query(default="", max_length=128),
    product_family: str = Query(default="", max_length=256),
    product_series: str = Query(default="", max_length=256),
    product_model: str = Query(default="", max_length=256),
    os_family: str = Query(default="", max_length=128),
    os_generation: str = Query(default="", max_length=128),
    software_train: str = Query(default="", max_length=128),
    software_release: str = Query(default="", max_length=128),
    cli_platform: str = Query(default="", max_length=128),
    document_category: str = Query(default="", max_length=128),
    feature_domain: str = Query(default="", max_length=128),
    status: str = Query(default="active", max_length=32),
    source_trust_level: str = Query(default="", max_length=32),
    metadata_governance_status: str = Query(default="", max_length=32),
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    """Download a bounded, portable source/metadata ZIP for this tenant.

    The bundle intentionally omits embeddings and server-owned ACL/identity
    fields.  Re-importing it must run the normal chunking and embedding path.
    """
    try:
        bundle = knowledge_export_service.build_export(
            tenant_id=user.get("tenant_id") or "tenant-default",
            source_type=source_type,
            knowledge_scope=knowledge_scope,
            search=search,
            directory_path=directory_path,
            vendor=vendor,
            product_family=product_family,
            product_series=product_series,
            product_model=product_model,
            os_family=os_family,
            os_generation=os_generation,
            software_train=software_train,
            software_release=software_release,
            cli_platform=cli_platform,
            document_category=document_category,
            feature_domain=feature_domain,
            status=status,
            source_trust_level=source_trust_level,
            metadata_governance_status=metadata_governance_status,
        )
    except KnowledgeExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    response = StreamingResponse(
        iter([bundle["content"]]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{bundle["filename"]}"',
            "Content-Length": str(len(bundle["content"])),
            "X-Knowledge-Export-Documents": str(bundle["document_count"]),
            "X-Knowledge-Export-Content-Bytes": str(bundle["content_bytes"]),
            "X-Knowledge-Export-Embeddings": "false",
        },
    )
    return response


@router.get("/documents/facets")
def list_document_facets(
    source_type: Optional[str] = Query(default=None, max_length=64),
    directory_path: Optional[str] = Query(default=None, max_length=500),
    knowledge_scope: Optional[str] = Query(default=None, max_length=32),
    status: str = Query(default="active", max_length=32),
    vendor: Optional[str] = Query(default=None, max_length=128),
    product_family: Optional[str] = Query(default=None, max_length=128),
    product_series: Optional[str] = Query(default=None, max_length=128),
    metadata_governance_status: str = Query(default="", max_length=32),
    user=Depends(require_ai_permission("ai.view")),
):
    """Return bounded product hierarchy facets for the knowledge browser."""
    return knowledge_service.list_document_facets(
        knowledge_source_type=source_type,
        directory_path=directory_path,
        knowledge_scope=knowledge_scope,
        status=status,
        vendor=vendor,
        product_family=product_family,
        product_series=product_series,
        metadata_governance_status=metadata_governance_status,
        tenant_id=user.get("tenant_id") or "tenant-default",
    )


@router.post("/documents")
def add_document(payload: KnowledgeDocumentCreateRequest, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Add document and perform automatic chunking + embedding."""
    tenant_id = user.get("tenant_id") or "tenant-default"
    if payload.metadata_confirmation_token or payload.metadata_confirmed:
        try:
            validate_metadata_confirmation(
                user=user,
                token=payload.metadata_confirmation_token,
                confirmed=payload.metadata_confirmed,
                name=payload.name,
                content=payload.content,
                vendor=payload.vendor,
                platform=payload.platform,
                knowledge_source_type=payload.knowledge_source_type,
                source_trust_level=payload.source_trust_level,
                chunk_size=payload.chunk_size,
                metadata=payload.metadata,
            )
        except MetadataConfirmationError as exc:
            detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
            if exc.details is not None:
                detail["details"] = exc.details
            raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    kb_list = knowledge_service.list_knowledge_bases(tenant_id=tenant_id)
    kb_id = kb_list[0]["id"] if kb_list else knowledge_service.create_knowledge_base("Default KB", tenant_id=tenant_id)["id"]
    return knowledge_service.add_document_and_chunk(
        knowledge_base_id=kb_id,
        name=payload.name,
        content=payload.content,
        vendor=payload.vendor,
        # A legacy UI hint must never write platform=all.  Front Matter (or a
        # nullable platform-neutral document) is authoritative.
        platform=payload.platform,
        knowledge_source_type=payload.knowledge_source_type,
        tenant_id=tenant_id,
        acl=payload.acl,
        source_trust_level=payload.source_trust_level,
        chunk_size=payload.chunk_size,
        metadata=payload.metadata,
    )


@router.post("/documents/import-bundle")
async def import_document_bundle(
    file: UploadFile = File(...),
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    """Validate and import a Nexora export ZIP in one database transaction.

    The destination always re-chunks/re-embeds locally.  Claims that a bundle
    is an official source are downgraded to ``user_document`` until the URL is
    explicitly re-reviewed through the official ingestion workflow.
    """
    max_bytes = 64 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail={"code": "KNOWLEDGE_BUNDLE_TOO_LARGE", "message": "知识库导出包超过 64 MB 限制"})
    try:
        result = import_knowledge_bundle(
            content,
            tenant_id=user.get("tenant_id") or "tenant-default",
            request_id=request_id_var.get("-"),
        )
    except KnowledgeBundleImportError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"code": "KNOWLEDGE_BUNDLE_IMPORT_FAILED", "message": "知识库导出包导入失败，已回滚全部变更"}) from exc
    return {"success": True, "data": result, "message": "知识库导出包已原子导入"}


@router.post("/documents/metadata-preview")
def preview_document_metadata_endpoint(
    payload: KnowledgeMetadataPreviewRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    """Preview canonical Metadata before a document is allowed to import."""

    try:
        preview = preview_document_metadata(
            user=user,
            name=payload.name,
            content=payload.content,
            vendor=payload.vendor,
            platform=payload.platform,
            knowledge_source_type=payload.knowledge_source_type,
            source_trust_level=payload.source_trust_level,
            chunk_size=payload.chunk_size,
            metadata=payload.metadata,
        )
    except MetadataConfirmationError as exc:
        detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.details is not None:
            detail["details"] = exc.details
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return {"success": True, "data": preview, "message": "Metadata preview ready for confirmation"}


@router.post("/clear-sample-knowledge")
def clear_sample_knowledge(user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Clear all sample knowledge documents."""
    return knowledge_service.clear_sample_knowledge(tenant_id=user.get("tenant_id") or "tenant-default")


@router.get("/documents/{doc_id}")
def get_document_detail(doc_id: str, user=Depends(require_ai_permission("ai.view"))):
    """Return a tenant-safe document detail view with ordered chunk content."""
    document = knowledge_service.get_document_detail(
        doc_id,
        tenant_id=user.get("tenant_id") or "tenant-default",
    )
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在或无权查看")
    return document


@router.get("/documents/{doc_id}/actions/impact")
def get_document_action_impact(doc_id: str, user=Depends(require_ai_permission("ai.view"))):
    """Return bounded document/Chunk/index/reference impact before confirmation."""
    try:
        return knowledge_service.get_document_action_impact(
            doc_id=doc_id,
            tenant_id=user.get("tenant_id") or "tenant-default",
        )
    except KnowledgeDocumentActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc


def _execute_knowledge_document_action(
    doc_id: str,
    action: str,
    payload: KnowledgeDocumentActionRequest,
    user: Dict[str, Any],
):
    try:
        return knowledge_service.execute_document_action(
            doc_id=doc_id,
            action=action,
            tenant_id=user.get("tenant_id") or "tenant-default",
            actor_id=user.get("id") or user.get("user_id") or user.get("username") or "system",
            actor_username=user.get("username") or "system",
            confirm=payload.confirm,
            reason=payload.reason,
        )
    except KnowledgeDocumentActionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.post("/documents/{doc_id}/actions/delete")
def delete_document_action(
    doc_id: str,
    payload: KnowledgeDocumentActionRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    """Explicitly confirmed document deletion with a durable action ledger."""
    return _execute_knowledge_document_action(doc_id, "delete", payload, user)


@router.post("/documents/{doc_id}/actions/disable")
def disable_document_action(
    doc_id: str,
    payload: KnowledgeDocumentActionRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    return _execute_knowledge_document_action(doc_id, "disable", payload, user)


@router.post("/documents/{doc_id}/actions/enable")
def enable_document_action(
    doc_id: str,
    payload: KnowledgeDocumentActionRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    return _execute_knowledge_document_action(doc_id, "enable", payload, user)


@router.post("/documents/{doc_id}/actions/reparse")
def reparse_document_action(
    doc_id: str,
    payload: KnowledgeDocumentActionRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    return _execute_knowledge_document_action(doc_id, "reparse", payload, user)


@router.post("/documents/{doc_id}/actions/rechunk")
def rechunk_document_action(
    doc_id: str,
    payload: KnowledgeDocumentActionRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    return _execute_knowledge_document_action(doc_id, "rechunk", payload, user)


@router.post("/documents/{doc_id}/actions/reindex")
def reindex_document_action(
    doc_id: str,
    payload: KnowledgeDocumentActionRequest,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    return _execute_knowledge_document_action(doc_id, "reindex", payload, user)


@router.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
    payload: Optional[KnowledgeDocumentActionRequest] = None,
    user=Depends(require_ai_permission("ai.knowledge.manage")),
):
    """Compatibility route; destructive calls must use the explicit action contract."""
    if payload is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "KNOWLEDGE_ACTION_CONFIRMATION_REQUIRED",
                "message": "use POST /documents/{id}/actions/delete with confirm=true",
            },
        )
    return _execute_knowledge_document_action(doc_id, "delete", payload, user)


@router.post("/documents/batch-delete")
def batch_delete_documents(payload: KnowledgeBatchDeleteRequest, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Batch delete multiple documents by IDs."""
    if not payload.confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "KNOWLEDGE_ACTION_CONFIRMATION_REQUIRED",
                "message": "explicit confirmation is required for batch deletion",
            },
        )
    tenant_id = user.get("tenant_id") or "tenant-default"
    actions = []
    for doc_id in payload.doc_ids:
        try:
            actions.append(
                knowledge_service.execute_document_action(
                    doc_id=doc_id,
                    action="delete",
                    tenant_id=tenant_id,
                    actor_id=user.get("id") or user.get("user_id") or user.get("username") or "system",
                    actor_username=user.get("username") or "system",
                    confirm=True,
                    reason=payload.reason or "confirmed batch delete",
                )
            )
        except KnowledgeDocumentActionError as exc:
            if exc.code == "KNOWLEDGE_DOCUMENT_NOT_FOUND":
                continue
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    return {"deleted_count": len(actions), "requested": len(payload.doc_ids), "actions": actions}
