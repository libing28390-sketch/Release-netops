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
CONFIG_CHANGE_RE = re.compile(r"(?i)\b(?:configure terminal|system-view|commit|write memory|save)\b")


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
    ):
        for match in pattern.finditer(text):
            findings.append(Finding(DataLevel.L4_PROHIBITED, category, match.start(), match.end()))

    for match in FULL_CONFIG_RE.finditer(text):
        findings.append(Finding(DataLevel.L4_PROHIBITED, "full_configuration_or_topology", match.start(), match.end()))

    for match in PROMPT_INJECTION_RE.finditer(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "prompt_injection", match.start(), match.end()))

    if CONFIG_CHANGE_RE.search(text):
        findings.append(Finding(DataLevel.L3_SENSITIVE, "change_command", detail="write-capable command"))

    for pattern, category in (
        (IPV4_RE, "ip_address"),
        (IPV6_RE, "ip_address"),
        (MAC_RE, "mac_address"),
        (EMAIL_RE, "email"),
        (PHONE_RE, "phone"),
        (HOSTNAME_RE, "hostname"),
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
