"""
AI Service for CLI Command Explanation and Output Inspection
"""

from __future__ import annotations

import json
from typing import Any, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.prompts.manager import prompt_manager
from ai.prompts.renderer import prompt_renderer
from ai.schemas.analysis import CommandAnalysisRequest, CommandAnalysisResponse
from ai.security.sanitizer import sanitize_text


def _coerce_dict_list(value: Any) -> List[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: List[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
        elif item is not None and str(item).strip():
            result.append({"field": str(item).strip()})
    return result


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class CommandAnalysisService:
    """Service handling AI Command Explanation."""

    async def analyze(
        self,
        req: CommandAnalysisRequest,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> CommandAnalysisResponse:
        sanitized_output = sanitize_text(req.output)
        prompt_data = prompt_manager.get_prompt_by_code("COMMAND_EXPLAIN")
        if prompt_data:
            sys_prompt = prompt_data["system_prompt"]
            user_prompt = prompt_renderer.render(
                prompt_data["user_prompt_template"],
                {
                    "command": req.command,
                    "vendor": req.vendor or "Generic",
                    "platform": req.platform or "Generic",
                    "output": sanitized_output
                }
            )
            p_id = prompt_data["id"]
            p_ver = prompt_data["version"]
        else:
            sys_prompt = (
                "You are an expert network engineer. Analyze the provided CLI command and output. "
                "Return a JSON object with keys: 'command_purpose', 'summary', 'important_fields' (list of objects), "
                "'abnormalities' (list of strings), 'recommendations' (list of strings)."
            )
            user_prompt = f"Command: {req.command}\nVendor: {req.vendor}\nPlatform: {req.platform}\nOutput:\n{sanitized_output}"
            p_id = None
            p_ver = None

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="command_explain",
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
                # Strip markdown json code block if present
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

        return CommandAnalysisResponse(
            request_id=res["request_id"],
            command_purpose=str(parsed.get("command_purpose") or f"Analysis of '{req.command}'"),
            summary=str(parsed.get("summary") or (content if content else "Analysis completed.")),
            important_fields=_coerce_dict_list(parsed.get("important_fields")),
            abnormalities=_coerce_str_list(parsed.get("abnormalities")),
            recommendations=_coerce_str_list(parsed.get("recommendations")),
        )


command_analysis_service = CommandAnalysisService()
