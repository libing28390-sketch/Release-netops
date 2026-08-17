"""ING-008 document Prompt Injection and knowledge-pollution boundary.

This scanner runs after ING-007 cleaning and before metadata extraction,
chunking or publication.  It is deliberately deterministic and local: source
text is inspected in memory, findings contain only stable rule IDs, bounded
locators and hashes, and suspicious documents receive an explicit quarantine
decision rather than being partially published.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from ai.security.classification import classify_text
from core.enum_compat import StrEnum
from services.document_content_cleaning import CleanedDocument
from services.document_parser_adapters import MAX_PARSE_BYTES, ParsedDocument


SCANNER_NAME = "nexora-document-security-scanner"
SCANNER_VERSION = "1.0.0"


class DocumentSecurityScanError(ValueError):
    """Stable, redacted scanner error."""

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


class SecurityDecision(StrEnum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"


class ScanStatus(StrEnum):
    CLEAN = "clean"
    QUARANTINED = "quarantined"
    EMPTY = "empty"


@dataclass(frozen=True)
class SecurityFinding:
    code: str
    category: str
    severity: str
    block_index: int | None = None
    locator: dict[str, Any] = field(default_factory=dict)
    evidence_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "block_index": self.block_index,
            "locator": dict(self.locator),
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True)
class DocumentSecurityScanResult:
    format: str
    status: ScanStatus
    decision: SecurityDecision
    publication_allowed: bool
    scanner_name: str
    scanner_version: str
    document_hash: str
    findings: tuple[SecurityFinding, ...] = ()
    reason_codes: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def quarantined(self) -> bool:
        return self.decision == SecurityDecision.QUARANTINE

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "status": self.status.value,
            "decision": self.decision.value,
            "publication_allowed": self.publication_allowed,
            "scanner_name": self.scanner_name,
            "scanner_version": self.scanner_version,
            "document_hash": self.document_hash,
            "findings": [item.as_dict() for item in self.findings],
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
        }


class _DocumentLike(Protocol):
    format: str
    text: str
    blocks: tuple[Any, ...]
    metadata: dict[str, Any]


_RULES: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    (
        "KP_HIDDEN_SCRIPT",
        "hidden_instruction",
        "high",
        re.compile(r"(?is)<script\b.*?>.*?</script>|<!--.*?(?:ignore|system|developer|instruction|override).*?-->|style\s*=\s*['\"][^'\"]*(?:display\s*:\s*none|visibility\s*:\s*hidden)"),
    ),
    (
        "PI_OVERRIDE_CONTEXT",
        "prompt_injection",
        "high",
        re.compile(
            r"(?is)\b(?:ignore|disregard|override|bypass|forget|do\s+not\s+follow)\b.{0,180}\b(?:previous|prior|system|developer|assistant|safety|security|instruction|rule)s?\b"
        ),
    ),
    (
        "PI_ROLE_REASSIGNMENT",
        "prompt_injection",
        "high",
        re.compile(r"(?is)\b(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be|role[- ]?play|new\s+(?:system|developer|assistant)\s+(?:message|instruction))\b"),
    ),
    (
        "PI_SECRET_PROMPT_REQUEST",
        "prompt_injection",
        "high",
        re.compile(r"(?is)\b(?:reveal|show|print|leak|expose|repeat|output)\b.{0,120}\b(?:system\s+prompt|developer\s+prompt|hidden\s+prompt|chain[- ]of[- ]thought|credentials?|secret)\b"),
    ),
    (
        "PI_CONTROL_TAG",
        "prompt_injection",
        "high",
        re.compile(r"(?is)<\|(?:system|developer|assistant|user)\|>|\b(?:BEGIN|END)_(?:SYSTEM|DEVELOPER|ASSISTANT)_MESSAGE\b"),
    ),
    (
        "PI_JAILBREAK_MODE",
        "prompt_injection",
        "high",
        re.compile(r"(?is)\b(?:jailbreak|DAN\s+mode|developer\s+mode|unrestricted\s+mode)\b"),
    ),
    (
        "PI_TOOL_EXECUTION_DIRECTIVE",
        "prompt_injection",
        "high",
        re.compile(r"(?is)\b(?:call|invoke|execute|run|use)\b.{0,100}\b(?:tool|function|shell|command|request)\b.{0,100}\b(?:without|before|ignore)\b"),
    ),
    (
        "KP_SOURCE_AUTHORITY_OVERRIDE",
        "knowledge_pollution",
        "high",
        re.compile(r"(?is)\b(?:this\s+(?:document|page|text)|these\s+instructions)\b.{0,160}\b(?:override|replace|supersede|only\s+source|source\s+of\s+truth|ignore\s+(?:vendor|official|catalog))\b"),
    ),
    (
        "KP_NO_VERIFY_OR_CITE",
        "knowledge_pollution",
        "high",
        re.compile(r"(?is)\b(?:do\s+not|don't|never)\b.{0,80}\b(?:verify|validate|check|cite|reference|audit)\b"),
    ),
    (
        "KP_UNVERIFIED_AUTHORITY_CLAIM",
        "knowledge_pollution",
        "medium",
        re.compile(r"(?is)\b(?:fake|forged|fabricated|unverified|unofficial)\b.{0,80}\b(?:official|vendor|release|version|source|command)\b"),
    ),
)
_OBFUSCATION_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_DECLARATION_RE = re.compile(r"(?im)\b(vendor|manufacturer|product(?:\s+family)?|version)\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9._/-]{1,80})")


def _normalized_for_scan(text: str) -> str:
    return unicodedata.normalize("NFKC", _OBFUSCATION_RE.sub("", text))


def _hash_evidence(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _finding(code: str, category: str, severity: str, text: str, match: re.Match[str], *, block_index: int | None, locator: Mapping[str, Any]) -> SecurityFinding:
    return SecurityFinding(
        code=code,
        category=category,
        severity=severity,
        block_index=block_index,
        locator={str(key): value for key, value in locator.items() if key in {"line", "column", "line_start", "line_end", "page", "section"}},
        evidence_hash=_hash_evidence(text[match.start() : match.end()]),
    )


def _scan_text(text: str, *, block_index: int | None, locator: Mapping[str, Any]) -> list[SecurityFinding]:
    normalized = _normalized_for_scan(text)
    findings: list[SecurityFinding] = []
    for code, category, severity, pattern in _RULES:
        match = pattern.search(normalized)
        if match:
            findings.append(_finding(code, category, severity, normalized, match, block_index=block_index, locator=locator))
    for classification in classify_text(normalized):
        if classification.category in {"prompt_injection", "credential", "private_key", "snmp_community", "full_configuration_or_topology"}:
            start = classification.start if classification.start is not None else 0
            end = classification.end if classification.end is not None else min(len(normalized), start + 1)
            match = re.match(r"[\s\S]*", normalized[start:end])
            if match:
                mapped = {
                    "prompt_injection": ("PI_CLASSIFIER_MATCH", "prompt_injection", "high"),
                    "credential": ("KP_CREDENTIAL_EXPOSURE", "knowledge_pollution", "high"),
                    "private_key": ("KP_PRIVATE_KEY", "knowledge_pollution", "high"),
                    "snmp_community": ("KP_CREDENTIAL_EXPOSURE", "knowledge_pollution", "high"),
                    "full_configuration_or_topology": ("KP_SENSITIVE_DUMP", "knowledge_pollution", "high"),
                }[classification.category]
                findings.append(
                    SecurityFinding(
                        code=mapped[0],
                        category=mapped[1],
                        severity=mapped[2],
                        block_index=block_index,
                        locator={str(key): value for key, value in locator.items() if key in {"line", "column", "line_start", "line_end", "page", "section"}},
                        evidence_hash=_hash_evidence(normalized[start:end]),
                    )
                )
    if _OBFUSCATION_RE.search(text):
        match = _OBFUSCATION_RE.search(text)
        if match:
            findings.append(_finding("KP_INVISIBLE_TEXT", "knowledge_pollution", "high", text, match, block_index=block_index, locator=locator))
    return findings


def _metadata_conflict(document: _DocumentLike) -> SecurityFinding | None:
    declarations: dict[str, set[str]] = {}
    for match in _DECLARATION_RE.finditer(_normalized_for_scan(document.text)):
        key = re.sub(r"\s+", "_", match.group(1).lower())
        declarations.setdefault(key, set()).add(match.group(2).lower())
    for key, values in declarations.items():
        if len(values) > 1 and key in {"vendor", "manufacturer", "product_family"}:
            return SecurityFinding(
                code="KP_METADATA_CONFLICT",
                category="knowledge_pollution",
                severity="high",
                block_index=None,
                locator={},
                evidence_hash=_hash_evidence(f"{key}:{','.join(sorted(values))}"),
            )
    return None


def scan_document_security(document: _DocumentLike) -> DocumentSecurityScanResult:
    """Scan and return an explicit publication/isolation decision."""

    if not isinstance(document, (ParsedDocument, CleanedDocument)):
        raise DocumentSecurityScanError("SECURITY_DOCUMENT_REQUIRED", "Security scan input must be a parsed or cleaned document")
    if document.format == "html" and not isinstance(document, CleanedDocument):
        raise DocumentSecurityScanError("SECURITY_CLEANING_REQUIRED", "HTML must pass ING-007 cleaning before security scanning")
    text = str(document.text or "")
    if len(text.encode("utf-8", errors="replace")) > MAX_PARSE_BYTES:
        raise DocumentSecurityScanError("SECURITY_DOCUMENT_TOO_LARGE", "Document exceeds security scan size limit")
    document_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    if not text.strip():
        return DocumentSecurityScanResult(
            format=document.format,
            status=ScanStatus.EMPTY,
            decision=SecurityDecision.QUARANTINE,
            publication_allowed=False,
            scanner_name=SCANNER_NAME,
            scanner_version=SCANNER_VERSION,
            document_hash=document_hash,
            reason_codes=("EMPTY_DOCUMENT",),
            warnings=("document_is_empty_or_cleaned_empty",),
        )

    findings: list[SecurityFinding] = []
    for index, block in enumerate(document.blocks):
        block_text = str(getattr(block, "text", "") or "")
        if block_text:
            findings.extend(_scan_text(block_text, block_index=index, locator=getattr(block, "locator", {}) or {}))
    findings.extend(_scan_text(text, block_index=None, locator={}))
    conflict = _metadata_conflict(document)
    if conflict:
        findings.append(conflict)
    unique: dict[tuple[str, int | None, str], SecurityFinding] = {}
    for item in findings:
        unique[(item.code, item.block_index, item.evidence_hash)] = item
    ordered = tuple(unique.values())
    reason_codes = tuple(sorted({item.code for item in ordered}))
    if ordered:
        return DocumentSecurityScanResult(
            format=document.format,
            status=ScanStatus.QUARANTINED,
            decision=SecurityDecision.QUARANTINE,
            publication_allowed=False,
            scanner_name=SCANNER_NAME,
            scanner_version=SCANNER_VERSION,
            document_hash=document_hash,
            findings=ordered,
            reason_codes=reason_codes,
            warnings=("document_isolated_before_publication",),
        )
    return DocumentSecurityScanResult(
        format=document.format,
        status=ScanStatus.CLEAN,
        decision=SecurityDecision.ALLOW,
        publication_allowed=True,
        scanner_name=SCANNER_NAME,
        scanner_version=SCANNER_VERSION,
        document_hash=document_hash,
    )


def isolate_document(document: _DocumentLike) -> DocumentSecurityScanResult:
    """Named enforcement entry point used by ingestion workers."""

    return scan_document_security(document)


__all__ = [
    "DocumentSecurityScanError",
    "DocumentSecurityScanResult",
    "ScanStatus",
    "SCANNER_NAME",
    "SCANNER_VERSION",
    "SecurityDecision",
    "SecurityFinding",
    "isolate_document",
    "scan_document_security",
]
