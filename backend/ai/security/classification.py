"""Classification primitives for the Nexora AI security boundary.

The classifier deliberately errs on the side of a higher sensitivity level.
It is used before any provider request is constructed, so a caller cannot
turn a finding into a harmless-looking mask and still send the original value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Iterable

from core.enum_compat import StrEnum


class DataLevel(IntEnum):
    L0_PUBLIC = 0
    L1_GENERAL = 1
    L2_IDENTIFIER = 2
    L3_SENSITIVE = 3
    L4_PROHIBITED = 4


class SecurityAction(StrEnum):
    ALLOW = "ALLOW"
    MINIMIZE = "MINIMIZE"
    TOKENIZE = "TOKENIZE"
    BLOCK = "BLOCK"


class DataClassification(StrEnum):
    """Stable policy vocabulary exposed by the Security Gateway contract."""

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"


@dataclass(frozen=True)
class Finding:
    level: DataLevel
    category: str
    start: int | None = None
    end: int | None = None
    detail: str = ""


# These patterns are intentionally value-oriented.  A key name by itself is
# not a secret, while a key name followed by a value is prohibited.
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(?:password|passwd|secret|community|token|api[_ -]?key|access[_ -]?token|"
    r"private[_ -]?key|pre-shared-key|key-string|shared-key)\b\s*(?:[:=]|cipher|simple|hash|7|8|9)?\s*['\"]?([^\s,'\";]+)",
)
RADIUS_TACACS_SECRET_RE = re.compile(
    r"(?im)\b(?:radius|tacacs(?:\+|[-_ ]plus)?)[-_ ]?(?:key|secret|shared[-_ ]?secret|server[-_ ]?key)\b\s*(?:[:=]|secret|key)?\s*['\"]?([^\s,'\";]+)"
)
JWT_RE = re.compile(r"(?i)\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b")
COOKIE_RE = re.compile(r"(?i)\b(?:cookie|set-cookie)\s*[:=]\s*[^\r\n;]+")
SERIAL_RE = re.compile(r"(?i)\b(?:serial(?:[-_ ]?number)?|sn)\s*[:=#-]?\s*[A-Z0-9][A-Z0-9._-]{5,31}\b")
SITE_NAME_RE = re.compile(r"(?i)\b(?:site|机房|园区|站点)\s*[:=：]\s*[\u4e00-\u9fffA-Za-z0-9][^\r\n,;]{1,80}")
BUSINESS_NAME_RE = re.compile(r"(?i)\b(?:customer|business|project|department|业务|客户|项目|部门)\s*[:=：]\s*[^\r\n,;]{1,80}")
SNMP_SECRET_RE = re.compile(r"(?im)\bsnmp(?:-agent|-server)?\s+community\s+(?:read|write|cipher|simple)?\s*([^\s]+)")
IPV4_RE = re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])")
IPV6_RE = re.compile(r"(?i)(?<![\w:])(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}(?![\w:])")
MAC_RE = re.compile(r"(?i)(?<![\w])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![\w])")
EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,18}\d)(?!\w)")
HOSTNAME_RE = re.compile(
    r"(?<![\w.-])(?=[A-Za-z0-9.-]{3,253}(?![\w.-]))"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}|"
    r"[A-Za-z]{2,}[A-Za-z0-9]*(?:-[A-Za-z0-9]+)+(?:\d+)?(?![\w.-])"
)

PROMPT_INJECTION_RE = re.compile(
    r"(?i)\b(?:ignore|disregard|override|bypass)\b.{0,80}\b(?:previous|prior|system|developer|policy|instruction)s?\b"
)
FULL_CONFIG_RE = re.compile(
    r"(?i)(?:show|display)\s+(?:running-config|current-configuration|configuration)|"
    r"\b(?:running-config|current-configuration|full topology|完整拓扑|全量配置)\b"
)
FULL_CMDB_RE = re.compile(r"(?i)\b(?:full|entire|all)\s+(?:cmdb|asset inventory|device inventory)\b|全量(?:CMDB|资产|设备清单)")
FULL_LOG_RE = re.compile(r"(?i)\b(?:full|entire|all)\s+(?:logs?|log stream|session logs?)\b|全量日志|完整日志")
FULL_SESSION_RE = re.compile(r"(?i)\b(?:full|entire|all)\s+(?:sessions?|terminal sessions?)\b|全量会话|完整会话")
CONFIG_CHANGE_RE = re.compile(r"(?i)\b(?:configure terminal|system-view|commit|write memory|save)\b")
HIDDEN_INSTRUCTION_RE = re.compile(r"(?is)(?:<!--.*?(?:ignore|system|instruction|override).*?-->|<script\b.*?>.*?</script>|style\s*=\s*['\"][^'\"]*(?:display\s*:\s*none|visibility\s*:\s*hidden))")


def classification_for_level(level: DataLevel) -> DataClassification:
    if level <= DataLevel.L0_PUBLIC:
        return DataClassification.PUBLIC
    if level == DataLevel.L1_GENERAL:
        return DataClassification.INTERNAL
    if level == DataLevel.L2_IDENTIFIER:
        return DataClassification.CONFIDENTIAL
    return DataClassification.SECRET


def normalize_classification(value: Any) -> DataClassification | None:
    try:
        return DataClassification(str(value or "").strip().upper())
    except ValueError:
        return None


def separate_data_and_instructions(messages: Any) -> tuple[Any, list[str]]:
    """Mark prompt text as untrusted data and return detected instructions.

    The gateway never promotes text found in documents/tool results to a
    system/developer instruction.  Callers can show the safe categories while
    retaining the original data only inside their tenant-scoped workflow.
    """
    findings: list[str] = []
    for text in iter_text_values(messages):
        if PROMPT_INJECTION_RE.search(text):
            findings.append("prompt_injection")
        if HIDDEN_INSTRUCTION_RE.search(text):
            findings.append("hidden_instruction")
    return messages, sorted(set(findings))


def iter_text_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            # Keys are metadata and are not sent as user content by the
            # gateway, but inspect them for policy fields such as raw_output.
            if isinstance(key, str):
                yield key
            yield from iter_text_values(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from iter_text_values(item)


def classify_text(text: str) -> list[Finding]:
    findings: list[Finding] = []
    if not text:
        return findings

    for pattern, category in (
        (PRIVATE_KEY_RE, "private_key"),
        (SECRET_ASSIGNMENT_RE, "credential"),
        (SNMP_SECRET_RE, "snmp_community"),
        (RADIUS_TACACS_SECRET_RE, "radius_or_tacacs_key"),
        (JWT_RE, "jwt"),
        (COOKIE_RE, "cookie"),
    ):
        for match in pattern.finditer(text):
            findings.append(Finding(DataLevel.L4_PROHIBITED, category, match.start(), match.end()))

    for match in FULL_CONFIG_RE.finditer(text):
        findings.append(Finding(DataLevel.L4_PROHIBITED, "full_configuration_or_topology", match.start(), match.end()))
    for pattern, category in ((FULL_CMDB_RE, "full_cmdb"), (FULL_LOG_RE, "full_logs"), (FULL_SESSION_RE, "full_sessions")):
        for match in pattern.finditer(text):
            findings.append(Finding(DataLevel.L4_PROHIBITED, category, match.start(), match.end()))

    for match in PROMPT_INJECTION_RE.finditer(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "prompt_injection", match.start(), match.end()))
    for match in HIDDEN_INSTRUCTION_RE.finditer(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "hidden_instruction", match.start(), match.end()))

    if CONFIG_CHANGE_RE.search(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "change_command", detail="write-capable command"))

    for pattern, category in (
        (IPV4_RE, "ip_address"),
        (IPV6_RE, "ip_address"),
        (MAC_RE, "mac_address"),
        (EMAIL_RE, "email"),
        (PHONE_RE, "phone"),
        (HOSTNAME_RE, "hostname"),
        (SERIAL_RE, "serial_number"),
        (SITE_NAME_RE, "site_name"),
        (BUSINESS_NAME_RE, "business_name"),
    ):
        for match in pattern.finditer(text):
            findings.append(Finding(DataLevel.L2_IDENTIFIER, category, match.start(), match.end()))

    return findings


def classify(value: Any) -> tuple[DataLevel, list[Finding]]:
    findings = [finding for text in iter_text_values(value) for finding in classify_text(text)]
    if not findings:
        return DataLevel.L1_GENERAL, []
    return max((item.level for item in findings), default=DataLevel.L1_GENERAL), findings


def action_for(level: DataLevel, *, has_prompt_injection: bool = False) -> SecurityAction:
    if level >= DataLevel.L4_PROHIBITED:
        return SecurityAction.BLOCK
    if level == DataLevel.L3_SENSITIVE:
        return SecurityAction.MINIMIZE
    if level == DataLevel.L2_IDENTIFIER or has_prompt_injection:
        return SecurityAction.TOKENIZE
    return SecurityAction.ALLOW
