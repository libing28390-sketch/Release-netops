"""
AI Service for Natural Language Asset and Device Information Queries
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from database.core import get_db_connection
from ai.gateway.llm_gateway import llm_gateway
from ai.security.sanitizer import sanitize_data


class NaturalQueryService:
    """Safely executes structured asset queries based on natural language intent."""

    def search_devices(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                query = "SELECT id, hostname, ip_address, platform, vendor, role, status FROM devices WHERE 1=1"
                params = []
                
                if filters.get("vendor"):
                    query += " AND LOWER(vendor) LIKE ?"
                    params.append(f"%{filters['vendor'].lower()}%")
                if filters.get("role"):
                    query += " AND LOWER(role) LIKE ?"
                    params.append(f"%{filters['role'].lower()}%")
                if filters.get("status"):
                    query += " AND LOWER(status) = ?"
                    params.append(filters["status"].lower())
                if filters.get("keyword"):
                    query += " AND (LOWER(hostname) LIKE ? OR ip_address LIKE ?)"
                    kw = f"%{filters['keyword'].lower()}%"
                    params.extend([kw, kw])
                
                query += " LIMIT 50"
                cursor.execute(query, tuple(params))
                rows = cursor.fetchall()
                for r in rows:
                    results.append({
                        "id": r[0], "hostname": r[1], "ip_address": r[2],
                        "platform": r[3], "vendor": r[4], "role": r[5], "status": r[6]
                    })
        except Exception:
            pass
        return results

    async def execute_query(self, query: str, filters: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
        # Perform safe parameterized database query
        device_facts = self.search_devices(filters)
        sanitized_facts = sanitize_data(device_facts)

        sys_prompt = (
            "You are a network asset management assistant for Nexora. "
            "Given the actual facts queried from the Nexora database, summarize the answer to the user in a clear, concise manner."
        )
        user_prompt = f"User Question: {query}\nDatabase Facts:\n{json.dumps(sanitized_facts, ensure_ascii=False)}"
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="natural_query",
            messages=messages,
            user_id=user_id
        )

        return {
            "query": query,
            "matched_count": len(device_facts),
            "data": sanitized_facts,
            "summary": res.get("content", ""),
            "request_id": res.get("request_id")
        }


natural_query_service = NaturalQueryService()
