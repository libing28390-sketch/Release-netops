"""Lossy minimization for sensitive AI context."""

from __future__ import annotations

import re
from typing import Any

from ai.security.classification import classify_text


DROP_KEYS = {
    "raw", "raw_output", "raw_config", "running_config", "current_configuration",
    "configuration", "credential", "credentials", "password", "private_key",
    "secret", "api_key", "access_token", "snmp_community", "full_topology",
}

_SENSITIVE_KEY_MARKERS = frozenset({
    "raw", "rawoutput", "rawconfig", "runningconfig", "currentconfiguration",
    "configuration", "credential", "credentials", "password", "passwd",
    "privatekey", "secret", "apikey", "accesstoken", "snmpcommunity",
    "community", "cookie", "authorization", "requestbody", "toolargs",
})
_SENSITIVE_VALUE_CATEGORIES = frozenset({
    "credential", "snmp_community", "radius_or_tacacs_key", "private_key",
    "jwt", "cookie",
})


def _normalise_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key or "").casefold())


def _is_sensitive_key(key: Any) -> bool:
    normalised = _normalise_key(key)
    return any(marker in normalised for marker in _SENSITIVE_KEY_MARKERS)


def _is_sensitive_text(value: str) -> bool:
    return any(item.category in _SENSITIVE_VALUE_CATEGORIES for item in classify_text(value))


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
            if key_text.lower() in DROP_KEYS or _is_sensitive_key(key_text):
                continue
            result[key_text] = minimize(item, max_text_chars=max_text_chars)
        return result
    return value


def minimize_tool_result(result: Any) -> dict[str, Any]:
    """Build the safe view expected by the AI tool protocol.

    Tool handlers are a trust boundary: a future handler may return a secret
    under a non-standard key or embed one in a nested list/string.  Drop
    sensitive keys and replace sensitive scalar values before the result is
    placed in the agent transcript or persisted step trace.
    """

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return "<REDACTED_SENSITIVE>" if _is_sensitive_text(value) else minimize(value)
        if isinstance(value, list):
            return [scrub(item) for item in value[:200]]
        if isinstance(value, tuple):
            return [scrub(item) for item in value[:200]]
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for key, item in value.items():
                if _is_sensitive_key(key):
                    continue
                output[str(key)] = scrub(item)
            return output
        return value

    if isinstance(result, dict):
        safe = scrub(result)
    else:
        safe = {"value": scrub(result)}
    if not isinstance(safe, dict):
        safe = {"value": safe}
    safe.setdefault("protocol_version", "nxa.tool.v1")
    safe.setdefault("evidence", [])
    safe.setdefault("freshness", "unknown")
    return safe

