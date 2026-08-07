"""
RAG Retriever for Vector Similarity and Keyword Relevance Search
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from database.core import get_db_connection
from ai.providers.embedding import embedding_provider


class RAGRetriever:
    """Retrieves Top-K relevant knowledge chunks based on query similarity and vendor/platform filters."""

    def _calc_keyword_relevance(self, query: str, content: str, doc_name: str) -> float:
        """Calculate keyword overlap relevance between query and chunk content."""
        q_words = set(re.findall(r'[\w\u4e00-\u9fa5]+', query.lower()))
        if not q_words:
            return 0.0
        
        target_text = f"{doc_name} {content}".lower()
        matched = sum(1 for w in q_words if len(w) > 1 and w in target_text)
        
        # Check specific network term hits
        network_terms = ["ospf", "bgp", "vlan", "trunk", "mtu", "crc", "ping", "cli", "huawei", "cisco", "h3c", "sop"]
        term_bonus = 0.0
        for term in network_terms:
            if term in query.lower() and term in target_text:
                term_bonus += 0.25

        score = (matched / max(1, len(q_words))) * 0.7 + term_bonus
        return min(1.0, score)

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        vendor: Optional[str] = None,
        platform: Optional[str] = None,
        min_relevance: float = 0.30,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT c.id, c.content, c.metadata_json, c.section, d.name, d.vendor, d.platform
                    FROM ai_document_chunk c
                    JOIN ai_document d ON c.document_id = d.id
                    WHERE d.status = 'active'
                    ORDER BY c.created_at DESC
                    LIMIT 100
                    """
                )
                rows = cursor.fetchall()
                seen_docs = set()
                
                scored_chunks = []
                for r in rows:
                    c_id, content, meta_json, section, doc_name, d_vendor, d_platform = r
                    
                    if vendor and d_vendor not in ["all", vendor]:
                        continue
                    if platform and d_platform not in ["all", platform]:
                        continue
                    
                    score = self._calc_keyword_relevance(query, content, doc_name)
                    if score < min_relevance:
                        continue

                    doc_key = f"{doc_name}_{section}"
                    if doc_key in seen_docs:
                        continue
                    seen_docs.add(doc_key)

                    scored_chunks.append({
                        "chunk_id": c_id,
                        "content": content,
                        "document_name": doc_name,
                        "section": section,
                        "vendor": d_vendor,
                        "platform": d_platform,
                        "relevance_score": round(score, 2),
                    })

                # Sort by relevance score descending
                scored_chunks.sort(key=lambda x: x["relevance_score"], reverse=True)
                results = scored_chunks[:top_k]

        except Exception as e:
            print(f"RAG retrieval error: {e}")

        return results


rag_retriever = RAGRetriever()
