"""
FastAPI Router for AI Assistant Copilot, Natural Query, IP/MAC Location, and Knowledge Base
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from ai.security.permissions import require_ai_permission
from ai.services.assistant import ai_assistant_service
from ai.services.natural_query import natural_query_service
from ai.services.ip_troubleshooting import ip_troubleshooting_service
from ai.services.mac_troubleshooting import mac_troubleshooting_service
from ai.services.knowledge_service import knowledge_service

router = APIRouter(prefix="/assistant", tags=["AI Copilot & Knowledge"])


class ChatRequest(BaseModel):
    message: str = Field(..., description="User question or prompt")
    history: Optional[List[Dict[str, str]]] = None


class IPLocationRequest(BaseModel):
    ip: str = Field(..., description="Target IP Address to trace")


class MACLocationRequest(BaseModel):
    mac: str = Field(..., description="Target MAC Address to trace")


from fastapi.responses import StreamingResponse

@router.post("/chat")
async def chat_assistant(req: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """AI Assistant Copilot Chat Endpoint."""
    user_id = user.get("username", "user")
    return await ai_assistant_service.chat(req.message, history=req.history, user_id=user_id)


@router.post("/chat-stream")
async def chat_assistant_stream(req: ChatRequest, user=Depends(require_ai_permission("ai.assistant"))):
    """AI Assistant Copilot Real-time Streaming SSE Endpoint."""
    user_id = user.get("username", "user")
    return StreamingResponse(
        ai_assistant_service.chat_stream(req.message, history=req.history, user_id=user_id),
        media_type="text/event-stream"
    )


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
    return knowledge_service.list_knowledge_bases()


@router.post("/knowledge-bases")
def create_knowledge_base(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Create a new Knowledge Base."""
    return knowledge_service.create_knowledge_base(
        name=payload.get("name", "Default KB"),
        description=payload.get("description"),
        created_by=user.get("username", "admin")
    )


@router.get("/knowledge-stats")
def get_knowledge_stats(user=Depends(require_ai_permission("ai.view"))):
    """Get metrics on Total Documents, Chunks, Vendors, Ready Indexes."""
    return knowledge_service.get_knowledge_stats()


@router.get("/documents")
def list_documents(source_type: Optional[str] = None, user=Depends(require_ai_permission("ai.view"))):
    """List documents optionally filtered by knowledge_source_type."""
    return knowledge_service.list_documents(knowledge_source_type=source_type)


@router.post("/documents")
def add_document(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Add document and perform automatic chunking + embedding."""
    kb_list = knowledge_service.list_knowledge_bases()
    kb_id = kb_list[0]["id"] if kb_list else knowledge_service.create_knowledge_base("Default KB")["id"]
    return knowledge_service.add_document_and_chunk(
        knowledge_base_id=kb_id,
        name=payload.get("name", "Untitled Document"),
        content=payload.get("content", ""),
        vendor=payload.get("vendor", "all"),
        platform=payload.get("platform", "all"),
        knowledge_source_type=payload.get("knowledge_source_type", "user_document")
    )


@router.post("/clear-sample-knowledge")
def clear_sample_knowledge(user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Clear all sample knowledge documents."""
    return knowledge_service.clear_sample_knowledge()


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Delete a single document and its chunks."""
    result = knowledge_service.delete_document(doc_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail=result.get("error", "文档不存在"))
    return result


@router.post("/documents/batch-delete")
def batch_delete_documents(payload: Dict[str, Any], user=Depends(require_ai_permission("ai.knowledge.manage"))):
    """Batch delete multiple documents by IDs."""
    doc_ids = payload.get("doc_ids", [])
    if not doc_ids or not isinstance(doc_ids, list):
        raise HTTPException(status_code=400, detail="doc_ids 必须为非空列表")
    return knowledge_service.batch_delete_documents(doc_ids)
