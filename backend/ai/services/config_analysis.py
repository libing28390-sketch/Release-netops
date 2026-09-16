"""
AI Service for Device Configuration Analysis and Security Auditing
"""

from __future__ import annotations

import json
from typing import Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.prompts.manager import prompt_manager
from ai.prompts.renderer import prompt_renderer
from ai.schemas.analysis import ConfigAnalysisRequest, ConfigAnalysisResponse
from ai.security.sanitizer import sanitize_text


class ConfigAnalysisService:
    """Service handling AI Device Configuration Analysis."""

    async def analyze(
        self,
        req: ConfigAnalysisRequest,
        user_id: Optional[str] = None
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
            user_id=user_id
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
                parsed = json.loads(clean_json.strip())
            except Exception:
                parsed = {}

        return ConfigAnalysisResponse(
            request_id=res["request_id"],
            summary=parsed.get("summary") or (content if content else "Configuration analysis completed."),
            routing_protocols=parsed.get("routing_protocols") if isinstance(parsed.get("routing_protocols"), list) else [],
            security_risks=parsed.get("security_risks") if isinstance(parsed.get("security_risks"), list) else [],
            network_services=parsed.get("network_services") if isinstance(parsed.get("network_services"), list) else [],
            management_services=parsed.get("management_services") if isinstance(parsed.get("management_services"), list) else [],
            risk_items=parsed.get("risk_items") if isinstance(parsed.get("risk_items"), list) else [],
            recommendations=parsed.get("recommendations") if isinstance(parsed.get("recommendations"), list) else []
        )


config_analysis_service = ConfigAnalysisService()
