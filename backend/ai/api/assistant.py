"""
FastAPI Router for AI Assistant Copilot, Natural Query, IP/MAC Location, and Knowledge Base
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from ai.security.permissions import require_ai_permission
from ai.services.assistant import ai_assistant_service
from ai.services.intent_parser import intent_parser
from ai.security.sanitizer import sanitize_text
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.knowledge_service import knowledge_service
from ai.services.knowledge_reindex_service import knowledge_reindex_service
from ai.services.conversation_service import append_message, get_context, set_conversation_model
from ai.security.security_service import create_diagnostic_case, handoff_case, record_feedback

router = APIRouter(prefix="/assistant", tags=["AI Copilot & Knowledge"])


class ChatRequest(BaseModel):
    message: str = Field(..., description="User question or prompt")
    history: Optional[List[Dict[str, str]]] = None
    conversation_id: Optional[str] = None
    model_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class CopilotFeedbackRequest(BaseModel):
    conversation_id: str = Field(..., min_length=1, max_length=120)
    message_id: str = Field(..., min_length=1, max_length=120)
    rating: str = Field(..., pattern="^(positive|negative)$")
    reasons: List[str] = Field(default_factory=list, max_length=8)
    comment: str = Field(default="", max_length=500)


class DiagnosticCaseRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    symptom: str = Field(default="", max_length=2000)
    conversation_id: Optional[str] = Field(default=None, max_length=120)
    context: Dict[str, Any] = Field(default_factory=dict)
    plan: List[Dict[str, Any]] = Field(default_factory=list, max_length=20)


class DiagnosticHandoffRequest(BaseModel):
    summary: str = Field(default="", max_length=2000)
    assignee: str = Field(default="", max_length=120)
    ticket_draft: str = Field(default="", max_length=3000)


class IPLocationRequest(BaseModel):
    ip: str = Field(..., description="Target IP Address to trace")


class MACLocationRequest(BaseModel):
    mac: str = Field(..., description="Target MAC Address to trace")


class RetrievalTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)
    filters: Dict[str, Any] = Field(default_factory=dict)


from fastapi.responses import StreamingResponse

@router.post("/chat")
async def chat_assistant(req: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """AI Assistant Copilot Chat Endpoint."""
    user_id = user.get("username", "user")
    tenant_id = user.get("tenant_id") or "tenant-default"
    history = req.history
    requested_model_id = req.model_id
    model_selection_source = "message_explicit_model" if req.model_id else None
    if req.conversation_id:
        try:
            context = get_context(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id)
            history = [{"role": item["role"], "content": item["content"]} for item in context["messages"]]
            if not requested_model_id and context.get("conversation", {}).get("selected_model_id"):
                requested_model_id = context["conversation"]["selected_model_id"]
                model_selection_source = "session_model"
            if req.model_id:
                try:
                    set_conversation_model(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, model_id=req.model_id, locked=True)
                except (RuntimeError, LookupError):
                    pass
            append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=req.message, requested_model_id=requested_model_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="message cannot be stored safely") from exc

    result = await ai_assistant_service.chat(
        req.message,
        history=history,
        user_id=user_id,
        tenant_id=tenant_id,
        roles=[str(user.get("role"))] if user.get("role") else [],
        site_ids=user.get("site_ids") or [],
        model_id=requested_model_id,
        model_selection_source=model_selection_source,
        context=req.context,
    )
    if req.conversation_id:
        try:
            append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="assistant", content=result.get("answer", ""), citations=result.get("citations") or [], requested_model_id=result.get("requested_model_id") or requested_model_id, actual_model_id=result.get("model_id"), provider_id=result.get("provider_id"), route_reason=result.get("route_reason"), fallback_used=bool(result.get("fallback_used")))
        except (LookupError, ValueError):
            # Do not discard a valid model answer when the safe-history write
            # rejects provider output or the client disconnects during cleanup.
            pass
    return result


@router.post("/chat-stream")
async def chat_assistant_stream(req: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """AI Assistant Copilot Real-time Streaming SSE Endpoint."""
    user_id = user.get("username", "user")
    tenant_id = user.get("tenant_id") or "tenant-default"
    history = req.history
    requested_model_id = req.model_id
    model_selection_source = "message_explicit_model" if req.model_id else None
    if req.conversation_id:
        try:
            context = get_context(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id)
            history = [{"role": item["role"], "content": item["content"]} for item in context["messages"]]
            if not requested_model_id and context.get("conversation", {}).get("selected_model_id"):
                requested_model_id = context["conversation"]["selected_model_id"]
                model_selection_source = "session_model"
            if req.model_id:
                try:
                    set_conversation_model(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, model_id=req.model_id, locked=True)
                except (RuntimeError, LookupError):
                    pass
            append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=req.message, requested_model_id=requested_model_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="message cannot be stored safely") from exc

    async def events():
        collected: list[str] = []
        route_meta: dict[str, Any] = {}
        async for event in ai_assistant_service.chat_stream(
            req.message,
            history=history,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[str(user.get("role"))] if user.get("role") else [],
            site_ids=user.get("site_ids") or [],
            model_id=requested_model_id,
            model_selection_source=model_selection_source,
            context=req.context,
        ):
            if req.conversation_id:
                for line in event.splitlines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[5:].strip())
                    except (TypeError, ValueError):
                        continue
                    if isinstance(payload, dict) and payload.get("content"):
                        collected.append(str(payload["content"]))
                    if isinstance(payload, dict) and payload.get("model_id"):
                        route_meta.update(payload)
            yield event
        if req.conversation_id and collected:
            try:
                append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="assistant", content="".join(collected), requested_model_id=route_meta.get("requested_model_id") or requested_model_id, actual_model_id=route_meta.get("model_id"), provider_id=route_meta.get("provider_id"), route_reason=route_meta.get("route_reason"), fallback_used=bool(route_meta.get("fallback_used")))
            except (LookupError, ValueError):
                pass

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/feedback")
def submit_copilot_feedback(payload: CopilotFeedbackRequest, user=Depends(require_ai_permission("ai.copilot.feedback"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    return record_feedback(
        tenant_id=tenant_id,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        user_id=str(user.get("username") or "anonymous"),
        rating=payload.rating,
        reasons=payload.reasons,
        comment=payload.comment,
    )


@router.post("/cases")
def create_copilot_case(payload: DiagnosticCaseRequest, user=Depends(require_ai_permission("ai.assistant"))):
    tenant_id = str(user.get("tenant_id") or "tenant-default")
    return create_diagnostic_case(
        tenant_id=tenant_id,
        user_id=str(user.get("username") or "anonymous"),
        title=payload.title,
        symptom=payload.symptom,
        conversation_id=payload.conversation_id,
        scope=payload.context,
        plan=payload.plan,
    )


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
        for key, value in dict(payload.filters or {}).items()
        if key in {
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
    }


@router.post("/ip-location")
async def locate_ip(req: IPLocationRequest, user=Depends(require_ai_permission("ai.use"))):
    """Intelligent IP Location & Troubleshooting Endpoint."""
    user_id = user.get("username", "user")
    return await ip_troubleshooting_service.troubleshoot_ip(req.ip, user_id=user_id)


@router.post("/mac-location")
async def locate_mac(req: MACLocationRequest, user=Depends(require_ai_permission("ai.use"))):
    """Intelligent MAC Location Endpoint."""
    user_id = user.get("username", "user")
    return await mac_troubleshooting_service.troubleshoot_mac(req.mac, user_id=user_id)


# --- Knowledge Base & Document Chunking Endpoints ---
@router.get("/knowledge-bases")
def list_knowledge_bases(user=Depends(require_ai_permission("ai.view"))):
    """List Knowledge Bases."""
    return knowledge_service.list_knowledge_bases(tenant_id=user.get("tenant_id") or "tenant-default")


@router.post("/knowledge-bases")
def create_knowledge_base(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Create a new Knowledge Base."""
    return knowledge_service.create_knowledge_base(
        name=payload.get("name", "Default KB"),
        description=payload.get("description"),
        created_by=user.get("username", "admin"),
        tenant_id=user.get("tenant_id") or "tenant-default",
        acl=payload.get("acl") if isinstance(payload.get("acl"), dict) else {},
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
def start_knowledge_reindex(payload: Dict[str, Any] | None = None, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Start a metadata/chunk/embedding reindex without deleting source docs."""
    payload = payload or {}
    scope = {
        key: payload.get(key)
        for key in ("vendor", "directory_path", "document_id")
        if payload.get(key)
    }
    return knowledge_reindex_service.create_job(
        tenant_id=user.get("tenant_id") or "tenant-default",
        scope=scope,
        dry_run=bool(payload.get("dry_run", False)),
        run_async=bool(payload.get("run_async", True)),
        batch_size=payload.get("batch_size", 250),
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
def create_knowledge_directory(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Create a root directory or a child below an existing directory."""
    tenant_id = user.get("tenant_id") or "tenant-default"
    try:
        knowledge_base = knowledge_service.get_or_create_default_knowledge_base(
            tenant_id=tenant_id,
            created_by=user.get("username", "admin"),
        )
        return knowledge_service.create_knowledge_directory(
            knowledge_base_id=knowledge_base["id"],
            name=payload.get("name", ""),
            parent_id=payload.get("parent_id") or None,
            tenant_id=tenant_id,
            created_by=user.get("username", "admin"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/knowledge-directories/{directory_id}")
def rename_knowledge_directory(directory_id: str, payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Rename a directory and update descendant paths."""
    try:
        return knowledge_service.rename_knowledge_directory(
            directory_id=directory_id,
            name=payload.get("name", ""),
            tenant_id=user.get("tenant_id") or "tenant-default",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/knowledge-directories/{directory_id}")
def delete_knowledge_directory(directory_id: str, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Delete a directory subtree without deleting uploaded documents."""
    try:
        return knowledge_service.delete_knowledge_directory(
            directory_id=directory_id,
            tenant_id=user.get("tenant_id") or "tenant-default",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/documents")
def list_documents(
    source_type: Optional[str] = Query(default=None, max_length=64),
    search: str = Query(default="", max_length=200),
    directory_path: Optional[str] = Query(default=None, max_length=500),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user=Depends(require_ai_permission("ai.view")),
):
    """List documents with server-side filtering and pagination."""
    return knowledge_service.list_documents(
        knowledge_source_type=source_type,
        directory_path=directory_path,
        search=search,
        page=page,
        page_size=page_size,
        tenant_id=user.get("tenant_id") or "tenant-default",
    )


@router.post("/documents")
def add_document(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Add document and perform automatic chunking + embedding."""
    tenant_id = user.get("tenant_id") or "tenant-default"
    kb_list = knowledge_service.list_knowledge_bases(tenant_id=tenant_id)
    kb_id = kb_list[0]["id"] if kb_list else knowledge_service.create_knowledge_base("Default KB", tenant_id=tenant_id)["id"]
    return knowledge_service.add_document_and_chunk(
        knowledge_base_id=kb_id,
        name=payload.get("name", "Untitled Document"),
        content=payload.get("content", ""),
        vendor=payload.get("vendor", "all"),
        # A legacy UI hint must never write platform=all.  Front Matter (or a
        # nullable platform-neutral document) is authoritative.
        platform=payload.get("platform"),
        knowledge_source_type=payload.get("knowledge_source_type", "user_document"),
        tenant_id=tenant_id,
        acl=payload.get("acl") if isinstance(payload.get("acl"), dict) else {},
        source_trust_level=payload.get("source_trust_level", "internal"),
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )


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


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Delete a single document and its chunks."""
    result = knowledge_service.delete_document(doc_id, tenant_id=user.get("tenant_id") or "tenant-default")
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail=result.get("error", "文档不存在"))
    return result


@router.post("/documents/batch-delete")
def batch_delete_documents(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Batch delete multiple documents by IDs."""
    doc_ids = payload.get("doc_ids", [])
    if not doc_ids or not isinstance(doc_ids, list):
        raise HTTPException(status_code=400, detail="doc_ids 必须为非空列表")
    return knowledge_service.batch_delete_documents(
        doc_ids,
        tenant_id=user.get("tenant_id") or "tenant-default",
    )
