"""
AI Intent Parser for Natural Language Query Recognition
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from ai.gateway.llm_gateway import llm_gateway


class IntentParser:
    """Parses natural language queries into structured intent & filter parameters."""

    async def parse_intent(self, query: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        sys_prompt = (
            "You are an intent parser for Nexora Network Operations. "
            "Analyze the user's natural language question and extract structured JSON intent.\n"
            "Allowed intent types: 'device_search', 'ip_location', 'mac_location', 'alarm_search', "
            "'config_search', 'troubleshooting', 'general_qa'.\n"
            "Return JSON format: {\"intent\": \"<type>\", \"filters\": { \"ip\": \"\", \"mac\": \"\", "
            "\"site\": \"\", \"vendor\": \"\", \"role\": \"\", \"status\": \"\", \"keyword\": \"\" }}"
        )
        user_prompt = f"User Query: {query}"
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            res = await llm_gateway.chat(
                scene="natural_query",
                messages=messages,
                response_format={"type": "json_object"},
                user_id=user_id
            )
            content = res.get("content", "")
            clean_json = content.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.startswith("```"): clean_json = clean_json[3:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            parsed = json.loads(clean_json.strip())
            return {
                "intent": parsed.get("intent", "general_qa"),
                "filters": parsed.get("filters", {})
            }
        except Exception:
            return {"intent": "general_qa", "filters": {"keyword": query}}


intent_parser = IntentParser()
