"""
Data Sanitizer for redacting sensitive network credentials, SNMP communities, passwords, and tokens before sending context to LLMs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Union

REDACTED_TAG = "<REDACTED>"

_LOG_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|token|password|passwd|secret|community|authorization|cookie|private[_ -]?key)"
    r"\s*[:=]\s*[\"']?[^\s,;\"'}]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_KEY_RE = re.compile(r"(?is)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----")

_REDACTION_PATTERNS = [
    # SNMP Community (Huawei / H3C / Cisco) — horizontal whitespace only so
    # "include snmp-agent community\ndisplay ..." never eats the next line.
    (re.compile(r'(?i)(?<!display )(?<!show )(?<!include )(snmp-agent[ \t]+community[ \t]+(?:(?:read|write|cipher|simple)[ \t]+)*)([^\s`]+)'), r'\1<REDACTED>'),
    (re.compile(r'(?i)(?<!display )(?<!show )(?<!include )(snmp-server[ \t]+community[ \t]+)([^\s`]+)'), r'\1<REDACTED>'),
    
    # CLI Passwords & Secrets
    # (?<![\w-]) keeps "trace-secret Bearer" or "db-password x" from being
    # read as the CLI keyword followed by its value.
    (re.compile(r'(?i)(?<![\w-])(password\s+(?:(?:level\s+\d+\s+)?(?:irreversible[-_ ]?cipher|cipher|simple|hash|7|8|9|0)\s+)?)(\S+)'), r'\1<REDACTED>'),
    (re.compile(r'(?i)(?<![\w-])(secret\s+(?:(?:level\s+\d+\s+)?(?:irreversible[-_ ]?cipher|cipher|simple|hash|0|5|7|8|9)\s+)?)(\S+)'), r'\1<REDACTED>'),
    (re.compile(r'(?i)(key-string\s+(?:(?:cipher|simple)\s+)?)(\S+)'), r'\1<REDACTED>'),
    (re.compile(r'(?i)(pre-shared-key\s+(?:(?:cipher|simple|local|remote)\s+)*)(\S+)'), r'\1<REDACTED>'),
    (re.compile(r'(?i)(tacacs-server\s+(?:key|shared-key)\s+(?:(?:irreversible[-_ ]?cipher|cipher|simple|0|7|8|9)\s+)?)(\S+)'), r'\1<REDACTED>'),
    (re.compile(r'(?i)(radius-server\s+(?:shared-key|key)\s+(?:(?:irreversible[-_ ]?cipher|cipher|simple|0|7|8|9)\s+)?)(\S+)'), r'\1<REDACTED>'),
    (re.compile(r'(?i)(authentication-password\s+(?:(?:cipher|simple)\s+)?)(\S+)'), r'\1<REDACTED>'),
    
    # JSON / Key-Value Credentials
    (re.compile(r'(?i)("(?:password|passwd|secret|api_key|token|snmp_community|community|access_token|private_key)"\s*:\s*")([^"]+)(")'), r'\1<REDACTED>\3'),
    
    # Private Key blocks (PKCS#1, PKCS#8, OpenSSH, EC, DSA, encrypted)
    (_PRIVATE_KEY_RE, '<REDACTED_PRIVATE_KEY>'),
]

SENSITIVE_KEYS = {
    "password", "passwd", "secret", "community", "snmp_community",
    "tacacs_key", "radius_secret", "private_key", "api_key", "token"
}


def sanitize_text(text: str) -> str:
    """Sanitize raw configuration text or command output."""
    if not text:
        return text
    sanitized = text
    try:
        from ai.security.classification import redact_cn_secret_assignments
        sanitized, _ = redact_cn_secret_assignments(sanitized)
    except Exception:
        pass
    for pattern, replacement in _REDACTION_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def sanitize_log_text(value: Any, *, limit: int = 512) -> str:
    """Return a bounded, secret-free value suitable for application logs."""

    sanitized = sanitize_text(str(value or ""))
    sanitized = _PRIVATE_KEY_RE.sub("<REDACTED_PRIVATE_KEY>", sanitized)
    sanitized = _LOG_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<REDACTED>", sanitized)
    sanitized = _BEARER_RE.sub("Bearer <REDACTED>", sanitized)
    return sanitized[: max(1, int(limit or 512))]


def sanitize_data(data: Union[Dict[str, Any], List[Any], str, int, float, bool, None]) -> Any:
    """Recursively sanitize dict, list, or text data structure."""
    if isinstance(data, str):
        return sanitize_text(data)
    elif isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            if k.lower() in SENSITIVE_KEYS:
                new_dict[k] = REDACTED_TAG
            else:
                new_dict[k] = sanitize_data(v)
        return new_dict
    elif isinstance(data, list):
        return [sanitize_data(item) for item in data]
    return data
