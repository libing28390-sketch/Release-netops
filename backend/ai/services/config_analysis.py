"""
AI Service for Device Configuration Analysis and Security Auditing
"""

from __future__ import annotations

import json
from typing import Any, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.prompts.manager import prompt_manager
from ai.prompts.renderer import prompt_renderer
from ai.schemas.analysis import ConfigAnalysisRequest, ConfigAnalysisResponse
from ai.security.sanitizer import sanitize_text


def _coerce_dict_list(value: Any) -> List[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: List[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
        elif item is not None and str(item).strip():
            result.append({"description": str(item).strip()})
    return result


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class ConfigAnalysisService:
    """Service handling AI Device Configuration Analysis."""

    async def analyze(
        self,
        req: ConfigAnalysisRequest,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> ConfigAnalysisResponse:
        # Guarantee strict pre-sanitization of config text
        sanitized_config = sanitize_text(req.config_text)
        
        prompt_data = prompt_manager.get_prompt_by_code("CONFIG_EXPLAIN")
        if prompt_data:
            sys_prompt = prompt_data["system_prompt"]
            user_prompt = prompt_renderer.render(
                prompt_data["user_prompt_template"],
                {
                    "vendor": req.vendor or "Generic",
                    "platform": req.platform or "Generic",
                    "config_text": sanitized_config
                }
            )
            p_id = prompt_data["id"]
            p_ver = prompt_data["version"]
        else:
            sys_prompt = (
                "You are an expert network architect. Analyze the device configuration text. "
                "Return a structured JSON object with keys: 'summary', 'routing_protocols', "
                "'security_risks', 'network_services', 'management_services', 'risk_items', 'recommendations'."
            )
            user_prompt = f"Vendor: {req.vendor}\nPlatform: {req.platform}\nConfig:\n{sanitized_config}"
            p_id = None
            p_ver = None

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="config_explain",
            messages=messages,
            response_format={"type": "json_object"},
            prompt_id=p_id,
            prompt_version=p_ver,
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )

        content = res.get("content", "")
        parsed = {}
        if content:
            try:
                clean_json = content.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.startswith("```"):
                    clean_json = clean_json[3:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                loaded = json.loads(clean_json.strip())
                parsed = loaded if isinstance(loaded, dict) else {}
            except Exception:
                parsed = {}

        return ConfigAnalysisResponse(
            request_id=res["request_id"],
            summary=str(parsed.get("summary") or (content if content else "Configuration analysis completed.")),
            routing_protocols=_coerce_str_list(parsed.get("routing_protocols")),
            security_risks=_coerce_dict_list(parsed.get("security_risks")),
            network_services=_coerce_str_list(parsed.get("network_services")),
            management_services=_coerce_str_list(parsed.get("management_services")),
            risk_items=_coerce_dict_list(parsed.get("risk_items")),
            recommendations=_coerce_str_list(parsed.get("recommendations")),
        )


config_analysis_service = ConfigAnalysisService()
