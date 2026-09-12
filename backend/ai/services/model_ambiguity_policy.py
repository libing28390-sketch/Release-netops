"""Fail-closed knowledge scope for ambiguous product-model resolution.

CAT-012 deliberately does not infer vendor, family, series, OS or driver from
an alias string.  Callers must join Alias candidates to reviewed catalog
context and pass those explicit fields here before any scoped knowledge is
used.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


_KNOWN_OUTCOMES = frozenset({"unique", "ambiguous", "candidates", "unknown"})
_REQUIRED_CONTEXT_FIELDS = ("vendor_id", "family_code", "series_code", "product_model_id")


class ModelAmbiguityPolicyError(ValueError):
    """Stable contract error for invalid catalog context."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ModelAmbiguityPolicy:
    resolution_outcome: str
    knowledge_scope: str
    safe_knowledge_kinds: tuple[str, ...]
    clarification_required: bool
    clarification_fields: tuple[str, ...]
    platform_specific_knowledge_allowed: bool
    driver_selection_allowed: bool
    candidate_count: int
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["safe_knowledge_kinds"] = list(self.safe_knowledge_kinds)
        result["clarification_fields"] = list(self.clarification_fields)
        return result


def _text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _context_values(candidates: list[dict[str, Any]], field: str) -> set[str]:
    return {_text(item.get(field)) for item in candidates if _text(item.get(field))}


def _context_complete(candidate: dict[str, Any]) -> bool:
    return all(_text(candidate.get(field)) for field in _REQUIRED_CONTEXT_FIELDS)


def _platform_context_is_consistent(candidates: list[dict[str, Any]]) -> bool:
    for field in ("os_family", "software_train", "cli_platform"):
        values = _context_values(candidates, field)
        if len(values) > 1:
            return False
    return all(any(_text(item.get(field)) for item in candidates) for field in ("os_family", "software_train", "cli_platform"))


def _policy(
    *,
    outcome: str,
    scope: str,
    safe_kinds: tuple[str, ...],
    fields: tuple[str, ...],
    platform_allowed: bool,
    count: int,
    rationale: str,
) -> ModelAmbiguityPolicy:
    return ModelAmbiguityPolicy(
        resolution_outcome=outcome,
        knowledge_scope=scope,
        safe_knowledge_kinds=safe_kinds,
        clarification_required=bool(fields),
        clarification_fields=fields,
        platform_specific_knowledge_allowed=platform_allowed,
        # Product ambiguity can never authorize a network driver or write.
        driver_selection_allowed=False,
        candidate_count=count,
        rationale=rationale,
    )


def evaluate_model_ambiguity(
    resolution_outcome: str,
    candidates: Iterable[dict[str, Any]],
) -> ModelAmbiguityPolicy:
    """Return the only knowledge scope allowed for a resolution result.

    Candidate dictionaries must contain explicit reviewed catalog context.
    Missing context is treated like UNKNOWN; the function never parses a
    product-model ID or alias to manufacture a vendor or platform.
    """
    outcome = _text(resolution_outcome)
    if outcome not in _KNOWN_OUTCOMES:
        raise ModelAmbiguityPolicyError("MODEL_RESOLUTION_OUTCOME_UNKNOWN", "resolution_outcome is not supported")
    rows = [dict(item) for item in candidates]
    if outcome == "unknown" or not rows:
        return _policy(
            outcome=outcome,
            scope="generic",
            safe_kinds=("generic_network_knowledge",),
            fields=("vendor", "product_model", "os_family", "software_version"),
            platform_allowed=False,
            count=len(rows),
            rationale="unknown_or_empty_candidates_require_explicit_identity",
        )
    if any(not _context_complete(item) for item in rows):
        return _policy(
            outcome=outcome,
            scope="generic",
            safe_kinds=("generic_network_knowledge",),
            fields=("vendor", "product_family", "product_series", "product_model"),
            platform_allowed=False,
            count=len(rows),
            rationale="catalog_context_incomplete_no_identity_inference",
        )

    vendors = _context_values(rows, "vendor_id")
    families = _context_values(rows, "family_code")
    series = _context_values(rows, "series_code")
    models = _context_values(rows, "product_model_id")
    platform_consistent = _platform_context_is_consistent(rows)
    if outcome == "unique" and len(models) == 1 and len(rows) == 1:
        return _policy(
            outcome=outcome,
            scope="model",
            safe_kinds=("vendor", "product_family", "product_series", "product_model"),
            fields=(),
            platform_allowed=platform_consistent,
            count=len(rows),
            rationale="one_explicit_reviewed_product_model",
        )
    if len(vendors) == 1 and len(families) == 1 and len(series) == 1:
        return _policy(
            outcome=outcome,
            scope="series",
            safe_kinds=("vendor", "product_family", "product_series", "series_capabilities"),
            fields=("product_model",),
            platform_allowed=False,
            count=len(rows),
            rationale="same_reviewed_series_multiple_models_requires_model_clarification",
        )
    if len(vendors) == 1 and len(families) == 1:
        return _policy(
            outcome=outcome,
            scope="family",
            safe_kinds=("vendor", "product_family", "family_capabilities"),
            fields=("product_series", "product_model"),
            platform_allowed=False,
            count=len(rows),
            rationale="same_reviewed_family_multiple_series_requires_series_and_model_clarification",
        )
    if len(vendors) == 1:
        return _policy(
            outcome=outcome,
            scope="vendor",
            safe_kinds=("vendor", "vendor_neutral_capabilities"),
            fields=("product_family", "product_series", "product_model"),
            platform_allowed=False,
            count=len(rows),
            rationale="same_vendor_multiple_families_requires_family_clarification",
        )
    return _policy(
        outcome=outcome,
        scope="generic",
        safe_kinds=("generic_network_knowledge",),
        fields=("vendor", "product_family", "product_series", "product_model"),
        platform_allowed=False,
        count=len(rows),
        rationale="cross_vendor_candidates_require_vendor_and_model_clarification",
    )
