"""
AI Service for Vendor-Aware Configuration Command Generation and Dangerous Command Interception
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from ai.gateway.llm_gateway import llm_gateway
from ai.security.sanitizer import sanitize_text

DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r'(?i)^\s*shutdown\s*$'),
    re.compile(r'(?i)^\s*reboot\b'),
    re.compile(r'(?i)^\s*reload\b'),
    re.compile(r'(?i)^\s*erase\s+'),
    re.compile(r'(?i)^\s*write\s+erase\b'),
    re.compile(r'(?i)^\s*delete\s+/unreserved\b'),
    re.compile(r'(?i)^\s*format\s+'),
    re.compile(r'(?i)^\s*clear\s+config'),
    re.compile(r'(?i)^\s*reset\s+saved-configuration'),
    re.compile(r'(?i)^\s*(?:undo\s+(?:bgp|ospf|vlan|interface)\b|no\s+(?:router\s+(?:bgp|ospf)|vlan)\b)'),
]


def _coerce_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


class ConfigGenerationService:
    """Generates vendor-aware CLI commands with safety validation."""

    def inspect_dangerous_commands(self, commands: List[str]) -> List[Dict[str, Any]]:
        warnings = []
        for cmd in _coerce_str_list(commands):
            for pattern in DANGEROUS_COMMAND_PATTERNS:
                if pattern.search(cmd):
                    warnings.append({
                        "command": cmd,
                        "risk": "HIGH",
                        "reason": "Dangerous command detected (shutdown/reboot/erase/reset/routing-removal)."
                    })
                    break
        return warnings

    async def generate_config(
        self,
        intent: str,
        vendor: str = "Huawei",
        platform: str = "huawei_vrp",
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        safe_intent = sanitize_text(intent)
        sys_prompt = (
            f"You are a network configuration engineer expert in {vendor} ({platform}).\n"
            "Generate accurate CLI configuration commands, verification commands, and rollback commands.\n"
            "Return JSON: {\"commands\": [...], \"verification_commands\": [...], \"rollback_commands\": [...], \"summary\": \"...\"}"
        )
        user_prompt = f"Configuration Intent: {safe_intent}"
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="change_plan",
            messages=messages,
            response_format={"type": "json_object"},
            user_id=user_id,
            tenant_id=tenant_id,
            roles=roles,
        )

        content = res.get("content", "")
        parsed = {}
        try:
            clean_json = content.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.startswith("```"): clean_json = clean_json[3:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            loaded = json.loads(clean_json.strip())
            parsed = loaded if isinstance(loaded, dict) else {"summary": content, "commands": []}
        except Exception:
            parsed = {"summary": content, "commands": []}

        generated_cmds = _coerce_str_list(parsed.get("commands"))
        verification_cmds = _coerce_str_list(parsed.get("verification_commands"))
        rollback_cmds = _coerce_str_list(parsed.get("rollback_commands"))
        warnings = self.inspect_dangerous_commands(generated_cmds + rollback_cmds)

        return {
            "intent": intent,
            "vendor": vendor,
            "platform": platform,
            "commands": generated_cmds,
            "verification_commands": verification_cmds,
            "rollback_commands": rollback_cmds,
            "summary": str(parsed.get("summary") or ""),
            "safety_warnings": warnings,
            "requires_approval": len(warnings) > 0 or len(generated_cmds) > 0,
            "request_id": res.get("request_id")
        }


config_generation_service = ConfigGenerationService()
