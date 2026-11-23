"""
AI Service for Alarm Incident Root Cause and Evidence Analysis
"""

from __future__ import annotations

import json
from typing import Any, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.prompts.manager import prompt_manager
from ai.prompts.renderer import prompt_renderer
from ai.schemas.analysis import AlarmAnalysisRequest, AlarmAnalysisResponse
from ai.security.sanitizer import sanitize_text


def _coerce_confidence(value: Any, default: float = 0.8) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric > 1.0 and numeric <= 100.0:
        numeric = numeric / 100.0
    return max(0.0, min(1.0, numeric))


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


class AlarmAnalysisService:
    """Service handling AI Alarm Analysis."""

    async def analyze(
        self,
        req: AlarmAnalysisRequest,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> AlarmAnalysisResponse:
        sanitized_raw = sanitize_text(req.raw_content or "")

        prompt_data = prompt_manager.get_prompt_by_code("ALARM_ANALYSIS")
        if prompt_data:
            sys_prompt = prompt_data["system_prompt"]
            user_prompt = prompt_renderer.render(
                prompt_data["user_prompt_template"],
                {
                    "alarm_title": req.alarm_title,
                    "severity": req.severity,
                    "fingerprint": req.fingerprint or "N/A",
                    "raw_content": sanitized_raw,
                    "context_data": json.dumps(req.context_data or {}, ensure_ascii=False)
                }
            )
            p_id = prompt_data["id"]
            p_ver = prompt_data["version"]
        else:
            sys_prompt = (
                "You are an expert network SRE and incident investigator. Analyze the alarm event. "
                "Return a structured JSON object with keys: 'incident_summary', 'suspected_root_cause', "
                "'confidence' (0.0-1.0), 'evidence', 'affected_scope', 'recommended_actions'."
            )
            user_prompt = f"Title: {req.alarm_title}\nSeverity: {req.severity}\nContent:\n{sanitized_raw}"
            p_id = None
            p_ver = None

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="alarm_analysis",
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

        return AlarmAnalysisResponse(
            request_id=res["request_id"],
            incident_summary=str(parsed.get("incident_summary") or f"Alarm Analysis for '{req.alarm_title}'"),
            suspected_root_cause=str(parsed.get("suspected_root_cause") or (content if content else "Root cause analysis completed.")),
            confidence=_coerce_confidence(parsed.get("confidence"), default=0.8),
            evidence=_coerce_str_list(parsed.get("evidence")),
            affected_scope=_coerce_str_list(parsed.get("affected_scope")),
            recommended_actions=_coerce_str_list(parsed.get("recommended_actions")),
        )


alarm_analysis_service = AlarmAnalysisService()
