"""Grounding and citation contracts for local knowledge answers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit


_ALLOWED_SCHEMES = {"http", "https"}
_SECRET_RE = re.compile(r"(?i)(?:sk-|api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")


@dataclass(frozen=True)
class Citation:
    citation_id: str
    vendor: str | None
    product: str | None
    os_family: str | None
    software_version: str | None
    document: str
    document_id: str | None
    document_version: str | None
    url: str | None
    section: str | None
    chunk_id: str | None
    source_type: str
    status: str
    trust: str
    validation: str
    updated_at: str | None = None
    claim_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "vendor": self.vendor,
            "product": self.product,
            "os_family": self.os_family,
            "software_version": self.software_version,
            "document": self.document,
            "document_id": self.document_id,
            "document_version": self.document_version,
            "url": self.url,
            "section": self.section,
            "chunk_id": self.chunk_id,
            "source_type": self.source_type,
            "status": self.status,
            "trust": self.trust,
            "validation": self.validation,
            "updated_at": self.updated_at,
            "claim_ids": list(self.claim_ids),
            "warnings": list(self.warnings),
        }


def _safe_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or _SECRET_RE.search(text):
        return None
    parsed = urlsplit(text)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
        return None
    # Query strings can carry credentials or tracking material; citation URLs
    # are canonicalized to scheme/host/path only.
    return f"{parsed.scheme.lower()}://{parsed.hostname}{parsed.path or '/'}"


def citation_from_chunk(item: Mapping[str, Any]) -> Citation:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    document = str(item.get("document_name") or item.get("document_id") or "Nexora Knowledge")[:256]
    document_id = str(item.get("document_id") or "") or None
    chunk_id = str(item.get("chunk_id") or "") or None
    raw_identity = "|".join((document_id or "", chunk_id or "", str(item.get("section") or "")))
    citation_id = "cit_" + hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()[:16]
    source_type = str(item.get("knowledge_source_type") or metadata.get("source_type") or "local")[:64]
    status = str(item.get("document_status") or metadata.get("status") or "active")[:32]
    source_url = _safe_url(item.get("source") or metadata.get("canonical_url") or metadata.get("source_url"))
    warnings: list[str] = []
    if not document_id:
        warnings.append("document_id_missing")
    if not item.get("section"):
        warnings.append("section_missing")
    if metadata.get("knowledge_stale") or metadata.get("stale"):
        warnings.append("knowledge_stale")
    if status.lower() not in {"published", "active"} and source_type.startswith("official"):
        warnings.append("official_source_not_published")
    validation = "pending"
    if status.lower() in {"disabled", "quarantined", "deleted", "archived"}:
        validation = "invalid_lifecycle"
    elif source_type.startswith("official") and not source_url:
        validation = "invalid_url"
    elif source_type.startswith("official") and status.lower() not in {"published", "active"}:
        validation = "invalid_lifecycle"
    else:
        validation = "local_active" if not source_type.startswith("official") else "validated_official"
    return Citation(
        citation_id=citation_id,
        vendor=str(item.get("vendor") or metadata.get("vendor") or "") or None,
        product=str(item.get("product_model") or metadata.get("product_model") or item.get("product_series") or metadata.get("product_series") or "") or None,
        os_family=str(item.get("os_family") or metadata.get("os_family") or "") or None,
        software_version=str(item.get("software_release") or metadata.get("software_release") or item.get("document_version") or metadata.get("software_train") or "") or None,
        document=document,
        document_id=document_id,
        document_version=str(item.get("document_version") or metadata.get("document_version") or "") or None,
        url=source_url,
        section=str(item.get("section") or "") or None,
        chunk_id=chunk_id,
        source_type=source_type,
        status=status,
        trust=str(item.get("source_trust_level") or metadata.get("source_trust_level") or "untrusted"),
        validation=validation,
        updated_at=str(item.get("updated_at") or metadata.get("updated_at") or metadata.get("last_verified_at") or "") or None,
        warnings=tuple(warnings),
    )


def validate_citations(
    citations: Sequence[Citation],
    *,
    requested_vendor: Any = None,
    requested_version: Any = None,
    allowed_hosts: Iterable[str] = (),
) -> tuple[list[Citation], list[dict[str, Any]]]:
    """Return only citations safe for an answer and structured warnings."""

    hosts = {str(item).lower().strip().rstrip(".") for item in allowed_hosts if str(item).strip()}
    accepted: list[Citation] = []
    warnings: list[dict[str, Any]] = []
    for citation in citations:
        local_warnings = list(citation.warnings)
        if requested_vendor and citation.vendor and str(requested_vendor).lower() != citation.vendor.lower():
            local_warnings.append("vendor_conflict")
        if requested_version and citation.software_version and str(requested_version).lower() not in citation.software_version.lower():
            local_warnings.append("version_conflict")
        if citation.source_type.startswith("official") and citation.url:
            host = str(urlsplit(citation.url).hostname or "").lower().rstrip(".")
            if hosts and host not in hosts:
                local_warnings.append("host_not_allowlisted")
        if citation.validation.startswith("invalid") or any(item in local_warnings for item in ("vendor_conflict", "version_conflict", "host_not_allowlisted")):
            if citation.validation.startswith("invalid"):
                local_warnings.append(citation.validation)
            warnings.append({"citation_id": citation.citation_id, "warnings": sorted(set(local_warnings))})
            continue
        accepted.append(citation)
    return accepted, warnings


def build_grounded_citations(chunks: Sequence[Mapping[str, Any]], *, request: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = []
    for index, item in enumerate(chunks[:20], start=1):
        citation = citation_from_chunk(item)
        raw.append(Citation(**{**citation.__dict__, "claim_ids": (f"conclusion-{index}",)}))
    accepted, warnings = validate_citations(
        raw,
        requested_vendor=getattr(request, "vendor", None),
        requested_version=getattr(request, "software_release", None) or getattr(request, "software_train", None),
    )
    return [item.to_dict() for item in accepted], warnings


def answer_contract(*, intent: str, citations: Sequence[Mapping[str, Any]], grounded: bool, no_match: bool = False) -> dict[str, Any]:
    """Stable answer labels used by UI and audit consumers."""

    conclusion_citations = {
        f"conclusion-{index}": [str(item.get("citation_id"))]
        for index, item in enumerate(citations, start=1)
        if item.get("citation_id")
    }
    return {
        "contract_version": "answer-grounding-v1",
        "intent": intent,
        "grounded": bool(grounded),
        "no_match": bool(no_match),
        "sections": ["judgement", "facts", "gaps", "assumptions", "next_steps", "risk", "remediation", "verification"]
        if intent in {"troubleshooting", "ip_location", "mac_location"}
        else ["facts", "commands", "notes"],
        "citation_count": len(citations),
        "citation_ids": [str(item.get("citation_id")) for item in citations if item.get("citation_id")],
        "conclusion_citations": conclusion_citations,
        "answer_marks": [
            {"type": "fact", "label": "事实", "grounded_by": list(conclusion_citations)},
            {"type": "inference", "label": "推断", "requires_citation": True},
            {"type": "recommendation", "label": "建议", "requires_operator_confirmation": True},
            {"type": "command", "label": "命令", "requires_applicable_version": True},
        ],
        "fact_mode": "local_evidence_only" if grounded else "refusal_or_user_supplied_context",
    }


def refusal_for_missing_evidence(*, intent: str = "knowledge") -> str:
    if intent in {"troubleshooting", "ip_location", "mac_location"}:
        return "缺少足够的本地证据，暂不做确定性判断。请补充设备型号、软件版本、相关命令输出或时间范围后再继续。"
    return "当前知识库没有足够的匹配证据，暂不生成未经本地资料验证的结论或配置命令。请补充厂商、型号、OS/版本或上传对应官方文档。"
