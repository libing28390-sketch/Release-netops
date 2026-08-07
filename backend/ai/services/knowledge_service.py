"""
AI Knowledge Base and Document Chunking Service
Supports Normalized Markdown Middle Format & Heading/CLI-Aware Smart Chunking
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from database.core import get_db_connection
from ai.providers.embedding import embedding_provider


class KnowledgeService:
    """Service for Knowledge Base CRUD, metadata tagging, normalized Markdown middle format, and smart chunking."""

    def create_knowledge_base(self, name: str, description: Optional[str] = None, created_by: Optional[str] = "admin") -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        kb_id = f"kb_{uuid.uuid4().hex[:12]}"
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO ai_knowledge_base (id, name, description, enabled, created_by, created_at) VALUES (?, ?, ?, 1, ?, ?)",
                (kb_id, name, description, created_by, now_iso)
            )
            conn.commit()
        return {"id": kb_id, "name": name, "description": description, "created_at": now_iso}

    def list_knowledge_bases(self) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, description, enabled, created_by, created_at FROM ai_knowledge_base WHERE enabled = 1")
            rows = cursor.fetchall()
            return [{"id": r[0], "name": r[1], "description": r[2], "enabled": bool(r[3]), "created_by": r[4], "created_at": r[5]} for r in rows]

    def get_knowledge_stats(self) -> Dict[str, Any]:
        """Return metrics: total_documents, total_chunks, total_vendors, ready_indexes."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM ai_document WHERE status = 'active'")
            total_docs = (cursor.fetchone() or [0])[0]

            cursor.execute("SELECT COUNT(*) FROM ai_document_chunk")
            total_chunks = (cursor.fetchone() or [0])[0]

            cursor.execute("SELECT COUNT(DISTINCT vendor) FROM ai_document WHERE vendor IS NOT NULL AND vendor != 'all'")
            total_vendors = (cursor.fetchone() or [0])[0]

            return {
                "total_documents": total_docs,
                "total_chunks": total_chunks,
                "total_vendors": total_vendors,
                "ready_indexes": total_docs,
            }

    def list_documents(self, knowledge_source_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT id, knowledge_base_id, name, source, vendor, platform, status, knowledge_source_type, created_at FROM ai_document WHERE status = 'active'"
            params = []
            if knowledge_source_type:
                query += " AND knowledge_source_type = ?"
                params.append(knowledge_source_type)
            query += " ORDER BY created_at DESC"
            cursor.execute(query, params)
            rows = cursor.fetchall()

            results = []
            for r in rows:
                doc_id = r[0]
                cursor.execute("SELECT COUNT(*) FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
                chunk_cnt = (cursor.fetchone() or [0])[0]
                results.append({
                    "id": doc_id,
                    "knowledge_base_id": r[1],
                    "name": r[2],
                    "source": r[3],
                    "vendor": r[4],
                    "platform": r[5],
                    "status": r[6],
                    "knowledge_source_type": r[7] or "user_document",
                    "created_at": r[8],
                    "chunk_count": chunk_cnt
                })
            return results

    def clear_sample_knowledge(self) -> Dict[str, Any]:
        """Delete all documents and chunks tagged as sample."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM ai_document WHERE knowledge_source_type = 'sample'")
            doc_ids = [r[0] for r in cursor.fetchall()]
            
            for doc_id in doc_ids:
                cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
                cursor.execute("DELETE FROM ai_document WHERE id = ?", (doc_id,))
            
            conn.commit()
            return {"deleted_count": len(doc_ids)}

    def delete_document(self, doc_id: str) -> Dict[str, Any]:
        """Delete a single document and its chunks by ID."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM ai_document WHERE id = ?", (doc_id,))
            row = cursor.fetchone()
            if not row:
                return {"deleted": False, "error": "文档不存在"}
            
            cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
            cursor.execute("DELETE FROM ai_document WHERE id = ?", (doc_id,))
            conn.commit()
            return {"deleted": True, "id": doc_id}

    def batch_delete_documents(self, doc_ids: List[str]) -> Dict[str, Any]:
        """Delete multiple documents and their chunks by IDs."""
        if not doc_ids:
            return {"deleted_count": 0}
        with get_db_connection() as conn:
            cursor = conn.cursor()
            deleted = 0
            for doc_id in doc_ids:
                cursor.execute("SELECT id FROM ai_document WHERE id = ?", (doc_id,))
                if cursor.fetchone():
                    cursor.execute("DELETE FROM ai_document_chunk WHERE document_id = ?", (doc_id,))
                    cursor.execute("DELETE FROM ai_document WHERE id = ?", (doc_id,))
                    deleted += 1
            conn.commit()
            return {"deleted_count": deleted, "requested": len(doc_ids)}

    def smart_chunk_markdown(self, markdown_text: str, max_chunk_size: int = 800) -> List[Dict[str, Any]]:
        """
        Heading & Command-Block Aware Smart Chunker.
        Splits text by Markdown headers (#, ##, ###) while preserving code/CLI blocks in single chunks.
        """
        lines = markdown_text.splitlines()
        chunks: List[Dict[str, Any]] = []
        
        current_section = "General Overview"
        current_block: List[str] = []
        
        heading_pattern = re.compile(r"^(#{1,4})\s+(.+)")

        for line in lines:
            h_match = heading_pattern.match(line)
            if h_match:
                # Flush existing accumulated block as a chunk
                block_text = "\n".join(current_block).strip()
                if block_text:
                    chunks.append({
                        "section": current_section,
                        "content": block_text
                    })
                    current_block = []
                current_section = h_match.group(2).strip()

            current_block.append(line)
            
            # If current block exceeds max_chunk_size, split cleanly at double newline
            if len("\n".join(current_block)) >= max_chunk_size and not line.startswith("```"):
                block_text = "\n".join(current_block).strip()
                chunks.append({
                    "section": current_section,
                    "content": block_text
                })
                current_block = []

        # Flush remaining lines
        block_text = "\n".join(current_block).strip()
        if block_text:
            chunks.append({
                "section": current_section,
                "content": block_text
            })

        return chunks

    def add_document_and_chunk(
        self,
        knowledge_base_id: str,
        name: str,
        content: str,
        vendor: str = "all",
        platform: str = "all",
        knowledge_source_type: str = "user_document",
        chunk_size: int = 800,
    ) -> Dict[str, Any]:
        now_iso = datetime.now(timezone.utc).isoformat()
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        
        # 1. Normalize input into Normalized Markdown (already Markdown or plain text)
        normalized_markdown = content.strip()

        # 2. Heading & Command-Aware Smart Chunking
        smart_chunks = self.smart_chunk_markdown(normalized_markdown, max_chunk_size=chunk_size)

        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ai_document (id, knowledge_base_id, name, source, vendor, platform, status, knowledge_source_type, created_at, updated_at)
                VALUES (?, ?, ?, 'upload', ?, ?, 'active', ?, ?, ?)
                """,
                (doc_id, knowledge_base_id, name, vendor, platform, knowledge_source_type, now_iso, now_iso)
            )

            for idx, chk in enumerate(smart_chunks):
                chunk_id = f"chk_{uuid.uuid4().hex[:12]}"
                chunk_text = chk["content"]
                section_name = chk["section"]
                
                vec = embedding_provider.embed_text(chunk_text)
                meta_json = json.dumps({
                    "chunk_idx": idx,
                    "vendor": vendor,
                    "platform": platform,
                    "knowledge_source_type": knowledge_source_type,
                    "section": section_name
                }, ensure_ascii=False)

                cursor.execute(
                    """
                    INSERT INTO ai_document_chunk (id, document_id, content, embedding, metadata_json, page, section, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (chunk_id, doc_id, chunk_text, json.dumps(vec), meta_json, idx + 1, section_name, now_iso)
                )
            conn.commit()

        return {"document_id": doc_id, "name": name, "chunk_count": len(smart_chunks), "knowledge_source_type": knowledge_source_type}


knowledge_service = KnowledgeService()
