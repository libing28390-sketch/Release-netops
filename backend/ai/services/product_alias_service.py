"""Deterministic V2 product-alias normalization and resolution.

CAT-009 deliberately keeps this layer persistence-neutral.  DB-006 freezes
the tenant-scoped product-alias contract but does not authorize a
production migration yet.  The service therefore accepts/returns immutable
records that a later repository can persist without changing matching rules.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable


ALIAS_KINDS = frozenset({"exact", "canonical", "prefix", "trigram"})
ALIAS_STATUSES = frozenset({"draft", "active", "disabled", "archived", "deleted", "purged"})
CONFLICT_STATUSES = frozenset({"none", "duplicate_same_target", "ambiguous_pending_review", "manual_approved", "rejected"})
REVIEW_STATUSES = frozenset({"pending_review", "approved", "rejected"})
ADJUDICATION_DECISIONS = frozenset({"approve", "reject", "reset"})
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_MAX_ALIAS_LENGTH = 256
_SENSITIVE_KEY_PARTS = ("password", "token", "secret", "authorization", "cookie", "api_key", "credential", "private_key")


class ProductAliasError(ValueError):
    """Stable, user-safe alias contract error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_alias(value: Any) -> str:
    """Apply DB-006's deterministic NFKC/casefold/dash normalization."""
    raw = unicodedata.normalize("NFKC", str(value or ""))
    if _CONTROL_RE.search(raw):
        raise ProductAliasError("ALIAS_CONTROL_CHARACTER", "Alias contains a control character")
    # A product alias is an identity token, not a URL or credential carrier.
    # Keep punctuation such as SKU dashes, but reject endpoint-like values.
    normalized = raw.strip().replace("-", " ")
    normalized = " ".join(normalized.split()).casefold()
    if not normalized:
        raise ProductAliasError("ALIAS_EMPTY", "Alias must not be empty")
    if len(normalized) > _MAX_ALIAS_LENGTH:
        raise ProductAliasError("ALIAS_TOO_LONG", "Alias exceeds the 256 character limit")
    if "://" in normalized or normalized.startswith(("www.", "bearer ", "basic ")):
        raise ProductAliasError("ALIAS_ENDPOINT_OR_SECRET", "Alias must be a product identity, not an endpoint or credential")
    return normalized


def alias_trigrams(value: Any) -> frozenset[str]:
    """Return bounded character trigrams used only as a candidate signal."""
    normalized = normalize_alias(value)
    padded = f"  {normalized} "
    return frozenset(padded[index : index + 3] for index in range(max(0, len(padded) - 2)))


def _assert_safe_evidence(value: Any, path: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _SENSITIVE_KEY_PARTS):
                raise ProductAliasError("ALIAS_EVIDENCE_SECRET", f"Secret-bearing field is not allowed in {path}.{key}")
            _assert_safe_evidence(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe_evidence(item, f"{path}[{index}]")
    elif isinstance(value, str) and ("bearer " in value.lower() or "basic " in value.lower()):
        raise ProductAliasError("ALIAS_EVIDENCE_SECRET", "Authorization material is not allowed in alias evidence")


def trigram_similarity(left: Any, right: Any) -> float:
    """Return a deterministic 0..1 similarity score for candidate ranking."""
    left_trigrams = alias_trigrams(left)
    right_trigrams = alias_trigrams(right)
    if not left_trigrams or not right_trigrams:
        return 0.0
    overlap = len(left_trigrams & right_trigrams)
    return round((2.0 * overlap) / (len(left_trigrams) + len(right_trigrams)), 6)


@dataclass(frozen=True)
class AliasRecord:
    id: str
    tenant_id: str
    product_model_id: str
    alias: str
    normalized_alias: str
    alias_kind: str
    status: str = "draft"
    locale: str = ""
    conflict_status: str = "none"
    conflict_group: str = ""
    conflict_reason: str = ""
    conflict_count: int = 0
    evidence: dict[str, Any] | None = None
    review_status: str = "pending_review"
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = dict(self.evidence or {})
        return result


@dataclass(frozen=True)
class AliasConflict:
    tenant_id: str
    normalized_alias: str
    alias_kind: str
    conflict_group: str
    conflict_status: str
    reason: str
    record_ids: tuple[str, ...]
    product_model_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["record_ids"] = list(self.record_ids)
        result["product_model_ids"] = list(self.product_model_ids)
        return result


@dataclass(frozen=True)
class AliasResolution:
    outcome: str
    query: str
    normalized_query: str
    candidates: tuple[dict[str, Any], ...]
    conflict_groups: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "query": self.query,
            "normalized_query": self.normalized_query,
            "candidates": [dict(item) for item in self.candidates],
            "candidate_count": len(self.candidates),
            "conflict_groups": list(self.conflict_groups),
        }


@dataclass(frozen=True)
class AliasCandidateList:
    """A bounded candidate response suitable for an API or review queue."""

    outcome: str
    query: str
    normalized_query: str
    candidates: tuple[dict[str, Any], ...]
    conflict_groups: tuple[str, ...] = ()
    requires_clarification: bool = True
    selection_allowed: bool = False
    manual_review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "query": self.query,
            "normalized_query": self.normalized_query,
            "candidates": [dict(item) for item in self.candidates],
            "candidate_count": len(self.candidates),
            "conflict_groups": list(self.conflict_groups),
            "requires_clarification": self.requires_clarification,
            "selection_allowed": self.selection_allowed,
            "manual_review_required": self.manual_review_required,
        }


@dataclass(frozen=True)
class AliasAdjudication:
    """Immutable audit result for a human conflict decision."""

    conflict_group: str
    decision: str
    reviewer_id: str
    reviewed_at: str
    review_note: str
    selected_record_ids: tuple[str, ...]
    rejected_record_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["selected_record_ids"] = list(self.selected_record_ids)
        result["rejected_record_ids"] = list(self.rejected_record_ids)
        return result


def _review_text(value: Any, *, field: str, required: bool, max_length: int) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ProductAliasError(f"ALIAS_{field.upper()}_REQUIRED", f"{field} is required")
    if len(text) > max_length or _CONTROL_RE.search(text):
        raise ProductAliasError(f"ALIAS_{field.upper()}_INVALID", f"{field} is invalid")
    lowered = text.lower()
    if "bearer " in lowered or "basic " in lowered or any(part in lowered for part in _SENSITIVE_KEY_PARTS):
        raise ProductAliasError("ALIAS_REVIEW_SECRET", "Review metadata must not contain authorization material")
    return text


def build_alias_record(payload: dict[str, Any]) -> AliasRecord:
    """Validate and derive the immutable fields for one alias row."""
    if not isinstance(payload, dict):
        raise ProductAliasError("ALIAS_PAYLOAD_INVALID", "Alias payload must be an object")
    tenant_id = str(payload.get("tenant_id") or "").strip()
    model_id = str(payload.get("product_model_id") or "").strip()
    alias_id = str(payload.get("id") or "").strip()
    if not tenant_id:
        raise ProductAliasError("ALIAS_TENANT_REQUIRED", "Alias tenant_id is required")
    if not model_id:
        raise ProductAliasError("ALIAS_MODEL_REQUIRED", "Alias product_model_id is required")
    if not alias_id:
        raise ProductAliasError("ALIAS_ID_REQUIRED", "Alias id is required")
    alias_kind = str(payload.get("alias_kind") or "").strip().lower()
    if alias_kind not in ALIAS_KINDS:
        raise ProductAliasError("ALIAS_KIND_UNKNOWN", "alias_kind must be exact, canonical, prefix or trigram")
    alias = str(payload.get("alias") or "").strip()
    if len(alias) > _MAX_ALIAS_LENGTH:
        raise ProductAliasError("ALIAS_TOO_LONG", "Alias exceeds the 256 character limit")
    normalized = normalize_alias(alias)
    status = str(payload.get("status") or "draft").strip().lower()
    if status not in ALIAS_STATUSES:
        raise ProductAliasError("ALIAS_STATUS_UNKNOWN", "Alias status is not in the lifecycle allowlist")
    locale = str(payload.get("locale") or "").strip()[:32]
    evidence = payload.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ProductAliasError("ALIAS_EVIDENCE_INVALID", "Alias evidence must be an object")
    _assert_safe_evidence(evidence)
    review_status = str(payload.get("review_status") or "pending_review").strip().lower()
    if review_status not in REVIEW_STATUSES:
        raise ProductAliasError("ALIAS_REVIEW_STATUS_UNKNOWN", "review_status is not in the lifecycle allowlist")
    reviewed_by = _review_text(payload.get("reviewed_by"), field="reviewer", required=review_status != "pending_review", max_length=128)
    reviewed_at = _review_text(payload.get("reviewed_at"), field="reviewed_at", required=review_status != "pending_review", max_length=64)
    review_note = _review_text(payload.get("review_note"), field="review_note", required=False, max_length=1024)
    return AliasRecord(
        id=alias_id,
        tenant_id=tenant_id,
        product_model_id=model_id,
        alias=alias,
        normalized_alias=normalized,
        alias_kind=alias_kind,
        status=status,
        locale=locale,
        evidence=dict(evidence),
        review_status=review_status,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        review_note=review_note,
    )


def _conflict_group(tenant_id: str, normalized: str, alias_kind: str) -> str:
    raw = f"{tenant_id}\x1f{normalized}\x1f{alias_kind}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def detect_alias_conflicts(records: Iterable[AliasRecord]) -> tuple[list[AliasRecord], list[AliasConflict]]:
    """Annotate conflicts without selecting a first match.

    Exact/canonical collisions across models are identity conflicts. Prefix
    and trigram collisions are candidate ambiguities, never unique identity.
    Duplicate rows targeting the same model are reported separately so an
    importer can deduplicate without hiding a cross-model collision.
    """
    source = list(records)
    groups: dict[tuple[str, str, str], list[AliasRecord]] = {}
    for record in source:
        key = (record.tenant_id, record.normalized_alias, record.alias_kind)
        groups.setdefault(key, []).append(record)
    updated: dict[str, AliasRecord] = {record.id: record for record in source}
    conflicts: list[AliasConflict] = []
    for (tenant_id, normalized, kind), group in sorted(groups.items()):
        model_ids = tuple(sorted({item.product_model_id for item in group}))
        record_ids = tuple(sorted(item.id for item in group))
        if len(group) == 1:
            continue
        status = "ambiguous_pending_review" if len(model_ids) > 1 else "duplicate_same_target"
        reason = "same_normalized_alias_multiple_models" if len(model_ids) > 1 else "duplicate_same_target"
        conflict_group = _conflict_group(tenant_id, normalized, kind)
        conflicts.append(AliasConflict(tenant_id, normalized, kind, conflict_group, status, reason, record_ids, model_ids))
        for item in group:
            updated[item.id] = replace(
                item,
                conflict_status=status,
                conflict_group=conflict_group,
                conflict_reason=reason,
                conflict_count=len(group),
            )
    return [updated[item.id] for item in source], conflicts


def resolve_alias(
    query: Any,
    records: Iterable[AliasRecord],
    *,
    tenant_id: str,
    limit: int = 20,
    trigram_threshold: float = 0.34,
) -> AliasResolution:
    """Resolve active aliases with exact/canonical precedence and safe ambiguity."""
    raw_query = str(query or "")
    normalized_query = normalize_alias(raw_query)
    bounded_limit = max(1, min(50, int(limit)))
    scoped = [
        item
        for item in records
        if item.tenant_id == str(tenant_id)
        and item.status == "active"
        and item.conflict_status not in {"rejected", "duplicate_same_target"}
    ]
    exact = [item for item in scoped if item.alias_kind == "exact" and item.normalized_alias == normalized_query]
    canonical = [item for item in scoped if item.alias_kind == "canonical" and item.normalized_alias == normalized_query]
    identity = exact or canonical
    if identity:
        ranked = sorted(identity, key=lambda item: (item.conflict_status == "ambiguous_pending_review", item.id))
        conflicts = tuple(sorted({item.conflict_group for item in ranked if item.conflict_group}))
        outcome = "unique" if len({item.product_model_id for item in ranked}) == 1 and not conflicts else "ambiguous"
        return AliasResolution(outcome, raw_query, normalized_query, tuple(item.to_dict() for item in ranked[:bounded_limit]), conflicts)

    prefix = [
        item
        for item in scoped
        if item.alias_kind == "prefix"
        and (normalized_query.startswith(item.normalized_alias) or item.normalized_alias.startswith(normalized_query))
    ]
    if prefix:
        ranked = sorted(prefix, key=lambda item: (len(item.normalized_alias) * -1, item.normalized_alias, item.id))
        conflicts = tuple(sorted({item.conflict_group for item in ranked if item.conflict_group}))
        return AliasResolution("candidates", raw_query, normalized_query, tuple(item.to_dict() for item in ranked[:bounded_limit]), conflicts)

    scored: list[tuple[float, AliasRecord]] = []
    for item in scoped:
        if item.alias_kind != "trigram":
            continue
        score = trigram_similarity(normalized_query, item.normalized_alias)
        if score >= float(trigram_threshold):
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].normalized_alias, pair[1].id))
    if scored:
        candidates = []
        for score, item in scored[:bounded_limit]:
            value = item.to_dict()
            value["similarity"] = score
            candidates.append(value)
        conflicts = tuple(sorted({item.conflict_group for _, item in scored if item.conflict_group}))
        return AliasResolution("candidates", raw_query, normalized_query, tuple(candidates), conflicts)
    return AliasResolution("unknown", raw_query, normalized_query, (), ())


def list_alias_candidates(
    query: Any,
    records: Iterable[AliasRecord],
    *,
    tenant_id: str,
    limit: int = 20,
    trigram_threshold: float = 0.34,
) -> AliasCandidateList:
    """Return a bounded, review-aware candidate list without selecting a model."""
    resolution = resolve_alias(
        query,
        records,
        tenant_id=tenant_id,
        limit=limit,
        trigram_threshold=trigram_threshold,
    )
    candidates: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    for candidate in resolution.candidates:
        model_id = str(candidate.get("product_model_id") or "")
        # One row per model keeps a duplicate alias from becoming a hidden
        # first-match selection while retaining the underlying record ID.
        if model_id in seen_models:
            continue
        seen_models.add(model_id)
        item = dict(candidate)
        item["candidate_rank"] = len(candidates) + 1
        item["match_kind"] = item.get("alias_kind", "")
        item["selection_allowed"] = resolution.outcome == "unique"
        candidates.append(item)
    pending = any(item.get("conflict_status") == "ambiguous_pending_review" for item in candidates)
    return AliasCandidateList(
        outcome=resolution.outcome,
        query=resolution.query,
        normalized_query=resolution.normalized_query,
        candidates=tuple(candidates),
        conflict_groups=resolution.conflict_groups,
        requires_clarification=resolution.outcome != "unique",
        selection_allowed=resolution.outcome == "unique",
        manual_review_required=pending,
    )


def adjudicate_alias_conflict(
    records: Iterable[AliasRecord],
    conflict_group: str,
    *,
    decision: str,
    reviewer_id: str,
    review_note: str,
    selected_record_id: str = "",
    reviewed_at: str,
) -> tuple[list[AliasRecord], AliasAdjudication]:
    """Apply an explicit human decision to one multi-model conflict group.

    Approval selects exactly one alias row and rejects the competing rows. It
    never changes the alias lifecycle to active and never authorizes a driver.
    Prefix/trigram aliases remain candidate-only even after approval.
    """
    group_id = str(conflict_group or "").strip()
    if not group_id:
        raise ProductAliasError("ALIAS_CONFLICT_GROUP_REQUIRED", "conflict_group is required")
    action = str(decision or "").strip().lower()
    if action not in ADJUDICATION_DECISIONS:
        raise ProductAliasError("ALIAS_ADJUDICATION_UNKNOWN", "decision must be approve, reject or reset")
    reviewer = _review_text(reviewer_id, field="reviewer", required=True, max_length=128)
    note = _review_text(review_note, field="review_note", required=True, max_length=1024)
    timestamp = _review_text(reviewed_at, field="reviewed_at", required=True, max_length=64)
    source = list(records)
    group = [item for item in source if item.conflict_group == group_id]
    if not group:
        annotated, _ = detect_alias_conflicts(source)
        group = [item for item in annotated if item.conflict_group == group_id]
        source = annotated
    if not group:
        raise ProductAliasError("ALIAS_CONFLICT_NOT_FOUND", "Conflict group was not found")
    model_ids = {item.product_model_id for item in group}
    if len(model_ids) < 2:
        raise ProductAliasError("ALIAS_CONFLICT_NOT_MULTI_MODEL", "Only multi-model conflicts can be adjudicated")
    selected_id = str(selected_record_id or "").strip()
    group_ids = {item.id for item in group}
    if action == "approve" and selected_id not in group_ids:
        raise ProductAliasError("ALIAS_SELECTED_RECORD_INVALID", "Approved record must belong to the conflict group")
    selected_ids: tuple[str, ...] = (selected_id,) if action == "approve" else ()
    rejected_ids: tuple[str, ...]
    if action == "approve":
        rejected_ids = tuple(sorted(group_ids - {selected_id}))
    elif action == "reject":
        rejected_ids = tuple(sorted(group_ids))
    else:
        rejected_ids = ()
    updated: list[AliasRecord] = []
    for item in source:
        if item.id not in group_ids:
            updated.append(item)
            continue
        if action == "approve" and item.id == selected_id:
            updated.append(replace(
                item,
                conflict_status="manual_approved",
                conflict_group="",
                conflict_reason="manual_approved_by_reviewer",
                conflict_count=0,
                review_status="approved",
                reviewed_by=reviewer,
                reviewed_at=timestamp,
                review_note=note,
            ))
        elif action == "reset":
            updated.append(replace(
                item,
                conflict_status="ambiguous_pending_review",
                conflict_group=_conflict_group(item.tenant_id, item.normalized_alias, item.alias_kind),
                conflict_reason="same_normalized_alias_multiple_models",
                conflict_count=len(group),
                review_status="pending_review",
                reviewed_by="",
                reviewed_at="",
                review_note=note,
            ))
        else:
            updated.append(replace(
                item,
                conflict_status="rejected",
                conflict_group=group_id,
                conflict_reason="manual_rejected_by_conflict_adjudication",
                conflict_count=len(group),
                review_status="rejected",
                reviewed_by=reviewer,
                reviewed_at=timestamp,
                review_note=note,
            ))
    adjudication = AliasAdjudication(
        conflict_group=group_id,
        decision=action,
        reviewer_id=reviewer,
        reviewed_at=timestamp,
        review_note=note,
        selected_record_ids=selected_ids,
        rejected_record_ids=rejected_ids,
    )
    return updated, adjudication
