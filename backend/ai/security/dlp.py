"""Outbound and inbound DLP checks for the AI trust boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ai.security.classification import (
    EMAIL_RE,
    IPV4_RE,
    IPV6_RE,
    MAC_RE,
    PHONE_RE,
    PRIVATE_KEY_RE,
    SECRET_ASSIGNMENT_RE,
    RADIUS_TACACS_SECRET_RE,
    JWT_RE,
    COOKIE_RE,
)


@dataclass(frozen=True)
class DLPFinding:
    category: str
    detail: str = ""


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return repr(value)


def scan(value: Any, *, identifiers_blocked: bool = True) -> list[DLPFinding]:
    text = _text(value)
    findings: list[DLPFinding] = []
    if PRIVATE_KEY_RE.search(text):
        findings.append(DLPFinding("private_key"))
    if SECRET_ASSIGNMENT_RE.search(text):
        findings.append(DLPFinding("credential"))
    if RADIUS_TACACS_SECRET_RE.search(text):
        findings.append(DLPFinding("radius_or_tacacs_key"))
    if JWT_RE.search(text):
        findings.append(DLPFinding("jwt"))
    if COOKIE_RE.search(text):
        findings.append(DLPFinding("cookie"))
    if identifiers_blocked:
        for pattern, category in (
            (IPV4_RE, "ip_address"), (IPV6_RE, "ip_address"),
            (MAC_RE, "mac_address"), (EMAIL_RE, "email"), (PHONE_RE, "phone"),
        ):
            if pattern.search(text):
                findings.append(DLPFinding(category))
    return findings


def assert_clean(value: Any, *, identifiers_blocked: bool = True) -> None:
    findings = scan(value, identifiers_blocked=identifiers_blocked)
    if findings:
        categories = ",".join(sorted({item.category for item in findings}))
        raise ValueError(f"outbound DLP violation: {categories}")
