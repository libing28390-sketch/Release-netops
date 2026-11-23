"""
AI Service for Configuration Diff Analysis and Operational Risk Assessment
"""

from __future__ import annotations

import json
from typing import Any, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.prompts.manager import prompt_manager
from ai.prompts.renderer import prompt_renderer
from ai.schemas.analysis import DiffAnalysisRequest, DiffAnalysisResponse, DiffChangeItem
from ai.security.sanitizer import sanitize_text

_VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class DiffAnalysisService:
    """Service handling AI Config Diff Analysis."""

    async def analyze(
        self,
        req: DiffAnalysisRequest,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> DiffAnalysisResponse:
        sanitized_diff = sanitize_text(req.diff_text)

        prompt_data = prompt_manager.get_prompt_by_code("CONFIG_DIFF_ANALYSIS")
        if prompt_data:
            sys_prompt = prompt_data["system_prompt"]
            user_prompt = prompt_renderer.render(
                prompt_data["user_prompt_template"],
                {
                    "vendor": req.vendor or "Generic",
                    "platform": req.platform or "Generic",
                    "diff_text": sanitized_diff
                }
            )
            p_id = prompt_data["id"]
            p_ver = prompt_data["version"]
        else:
            sys_prompt = (
                "You are a network change control expert. Analyze the provided configuration diff from Nexora Diff Engine. "
                "Return a structured JSON object with keys: 'summary', 'risk_level' (LOW|MEDIUM|HIGH|CRITICAL), 'changes', "
                "'affected_services', 'verification_commands', 'rollback_recommendation'."
            )
            user_prompt = f"Vendor: {req.vendor}\nPlatform: {req.platform}\nDiff:\n{sanitized_diff}"
            p_id = None
            p_ver = None

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="config_diff",
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

        raw_changes = parsed.get("changes") if isinstance(parsed.get("changes"), list) else []
        typed_changes = []
        for c in raw_changes:
            if isinstance(c, dict):
                typed_changes.append(DiffChangeItem(
                    type=str(c.get("type") or "change"),
                    risk=str(c.get("risk") or "LOW"),
                    description=str(c.get("description") or str(c)),
                    possible_impact=_coerce_str_list(c.get("possible_impact")),
                ))

        raw_risk = str(parsed.get("risk_level") or "LOW").strip().upper()
        risk_level = raw_risk if raw_risk in _VALID_RISK_LEVELS else "LOW"

        return DiffAnalysisResponse(
            request_id=res["request_id"],
            summary=str(parsed.get("summary") or (content if content else "Diff analysis completed.")),
            risk_level=risk_level,
            changes=typed_changes,
            affected_services=_coerce_str_list(parsed.get("affected_services")),
            verification_commands=_coerce_str_list(parsed.get("verification_commands")),
            rollback_recommendation=_coerce_str_list(parsed.get("rollback_recommendation")),
        )


diff_analysis_service = DiffAnalysisService()
