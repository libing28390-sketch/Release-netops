"""Lossy minimization for sensitive AI context."""

from __future__ import annotations

import re
from typing import Any


DROP_KEYS = {
    "raw", "raw_output", "raw_config", "running_config", "current_configuration",
    "configuration", "credential", "credentials", "password", "private_key",
    "secret", "api_key", "access_token", "snmp_community", "full_topology",
}


def minimize(value: Any, *, max_text_chars: int = 8000) -> Any:
    if isinstance(value, str):
        compact = re.sub(r"[ \t\r\f\v]+", " ", value).strip()
        return compact[:max_text_chars]
    if isinstance(value, list):
        return [minimize(item, max_text_chars=max_text_chars) for item in value[:200]]
    if isinstance(value, tuple):
        return [minimize(item, max_text_chars=max_text_chars) for item in value[:200]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in DROP_KEYS:
                continue
            result[key_text] = minimize(item, max_text_chars=max_text_chars)
        return result
    return value


def minimize_tool_result(result: Any) -> dict[str, Any]:
    """Build the safe view expected by the AI tool protocol."""
    if isinstance(result, dict):
        safe = minimize(result)
    else:
        safe = {"value": minimize(result)}
    if not isinstance(safe, dict):
        safe = {"value": safe}
    safe.setdefault("protocol_version", "nxa.tool.v1")
    safe.setdefault("evidence", [])
    safe.setdefault("freshness", "unknown")
    return safe

