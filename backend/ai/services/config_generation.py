"""
AI Service for Vendor-Aware Configuration Command Generation and Dangerous Command Interception
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from ai.gateway.llm_gateway import llm_gateway

DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r'(?i)^\s*shutdown\s*$'),
    re.compile(r'(?i)^\s*reboot\s*$'),
    re.compile(r'(?i)^\s*reload\s*$'),
    re.compile(r'(?i)^\s*erase\s+'),
    re.compile(r'(?i)^\s*format\s+'),
    re.compile(r'(?i)^\s*clear\s+config'),
    re.compile(r'(?i)^\s*reset\s+saved-configuration'),
]


class ConfigGenerationService:
    """Generates vendor-aware CLI commands with safety validation."""

    def inspect_dangerous_commands(self, commands: List[str]) -> List[Dict[str, Any]]:
        warnings = []
        for cmd in commands:
            for pattern in DANGEROUS_COMMAND_PATTERNS:
                if pattern.search(cmd):
                    warnings.append({
                        "command": cmd,
                        "risk": "HIGH",
                        "reason": "Dangerous command detected (shutdown/reboot/erase/reset)."
                    })
        return warnings

    async def generate_config(
        self,
        intent: str,
        vendor: str = "Huawei",
        platform: str = "huawei_vrp",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        sys_prompt = (
            f"You are a network configuration engineer expert in {vendor} ({platform}).\n"
            "Generate accurate CLI configuration commands, verification commands, and rollback commands.\n"
            "Return JSON: {\"commands\": [...], \"verification_commands\": [...], \"rollback_commands\": [...], \"summary\": \"...\"}"
        )
        user_prompt = f"Configuration Intent: {intent}"
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]

        res = await llm_gateway.chat(
            scene="agent",
            messages=messages,
            response_format={"type": "json_object"},
            user_id=user_id
        )

        content = res.get("content", "")
        parsed = {}
        try:
            clean_json = content.strip()
            if clean_json.startswith("```json"): clean_json = clean_json[7:]
            if clean_json.startswith("```"): clean_json = clean_json[3:]
            if clean_json.endswith("```"): clean_json = clean_json[:-3]
            parsed = json.loads(clean_json.strip())
        except Exception:
            parsed = {"summary": content, "commands": []}

        generated_cmds = parsed.get("commands", [])
        warnings = self.inspect_dangerous_commands(generated_cmds)

        return {
            "intent": intent,
            "vendor": vendor,
            "platform": platform,
            "commands": generated_cmds,
            "verification_commands": parsed.get("verification_commands", []),
            "rollback_commands": parsed.get("rollback_commands", []),
            "summary": parsed.get("summary", ""),
            "safety_warnings": warnings,
            "requires_approval": len(warnings) > 0 or len(generated_cmds) > 0,
            "request_id": res.get("request_id")
        }


config_generation_service = ConfigGenerationService()
