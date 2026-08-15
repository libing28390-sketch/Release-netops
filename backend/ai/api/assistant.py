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
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.knowledge_service import knowledge_service
from ai.services.knowledge_reindex_service import knowledge_reindex_service
from ai.services.conversation_service import append_message, get_context

router = APIRouter(prefix="/assistant", tags=["AI Copilot & Knowledge"])


class ChatRequest(BaseModel):
    message: str = Field(..., description="User question or prompt")
    history: Optional[List[Dict[str, str]]] = None
    conversation_id: Optional[str] = None


class IPLocationRequest(BaseModel):
    ip: str = Field(..., description="Target IP Address to trace")


class MACLocationRequest(BaseModel):
    mac: str = Field(..., description="Target MAC Address to trace")


from fastapi.responses import StreamingResponse

@router.post("/chat")
async def chat_assistant(req: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """AI Assistant Copilot Chat Endpoint."""
    user_id = user.get("username", "user")
    tenant_id = user.get("tenant_id") or "tenant-default"
    history = req.history
    if req.conversation_id:
        try:
            context = get_context(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id)
            history = [{"role": item["role"], "content": item["content"]} for item in context["messages"]]
            append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=req.message)
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
    )
    if req.conversation_id:
        try:
            append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="assistant", content=result.get("answer", ""), citations=result.get("citations") or [])
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
    if req.conversation_id:
        try:
            context = get_context(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id)
            history = [{"role": item["role"], "content": item["content"]} for item in context["messages"]]
            append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="user", content=req.message)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="conversation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="message cannot be stored safely") from exc

    async def events():
        collected: list[str] = []
        async for event in ai_assistant_service.chat_stream(
            req.message,
            history=history,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=[str(user.get("role"))] if user.get("role") else [],
            site_ids=user.get("site_ids") or [],
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
            yield event
        if req.conversation_id and collected:
            try:
                append_message(conversation_id=req.conversation_id, tenant_id=tenant_id, user_id=user_id, role="assistant", content="".join(collected))
            except (LookupError, ValueError):
                pass

    return StreamingResponse(events(), media_type="text/event-stream")


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
