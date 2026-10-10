"""Tenant-scoped Product/OS/Version resolution for the Knowledge Engine.

This module is deliberately read-only. It resolves metadata against an
active, tenant-scoped catalog snapshot and never turns a draft seed, body
text, software train, or CLI hint into a canonical entity or driver choice.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from core.enum_compat import StrEnum


MAX_CANDIDATES = 20
MAX_FIELD_LENGTH = 256
UNKNOWN_TOKENS = frozenset({"", "unknown", "n/a", "na", "none", "null", "unset", "-"})
SECRET_KEY_RE = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential|snmp[_-]?community)",
    re.IGNORECASE,
)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class EntityResolutionOutcome(StrEnum):
    RESOLVED = "resolved"
    CANDIDATES = "candidates"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    QUARANTINED = "quarantined"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


class EntityResolutionDecision(StrEnum):
    PROCEED = "proceed"
    REVIEW = "review"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class EntityResolutionIssue:
    code: str
    field: str
    severity: str = "review"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "severity": self.severity}


@dataclass(frozen=True)
class EntityCatalogSnapshot:
    """A read-only catalog view supplied by the catalog version boundary."""

    tenant_id: str
    models: tuple[Mapping[str, Any], ...] = ()
    aliases: tuple[Mapping[str, Any], ...] = ()
    version_id: str = ""
    is_seed: bool = False
    source: str = "active_catalog"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EntityCatalogSnapshot":
        if not isinstance(value, Mapping):
            raise ValueError("ENTITY_CATALOG_INVALID")
        tenant_id = _tenant(value.get("tenant_id"))
        models = value.get("models") or ()
        aliases = value.get("aliases") or ()
        if not isinstance(models, (list, tuple)) or not isinstance(aliases, (list, tuple)):
            raise ValueError("ENTITY_CATALOG_INVALID")
        return cls(
            tenant_id=tenant_id,
            models=tuple(item for item in models if isinstance(item, Mapping)),
            aliases=tuple(item for item in aliases if isinstance(item, Mapping)),
            version_id=_safe_text(value.get("version_id"), "version_id"),
            is_seed=bool(value.get("is_seed", False)),
            source=_safe_text(value.get("source") or "active_catalog", "source"),
        )


@dataclass(frozen=True)
class DocumentEntityResolution:
    outcome: EntityResolutionOutcome
    decision: EntityResolutionDecision
    tenant_id: str
    metadata: dict[str, Any]
    retrieval_filters: dict[str, Any]
    product: dict[str, Any] | None = None
    os: dict[str, Any] | None = None
    version: dict[str, Any] | None = None
    candidates: tuple[dict[str, Any], ...] = ()
    issues: tuple[EntityResolutionIssue, ...] = ()
    clarification_fields: tuple[str, ...] = ()
    truncated: bool = False
    catalog_ready: bool = False
    driver_selection_allowed: bool = False
    retrieval_eligible: bool = False
    metadata_hash: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return self.outcome in {
            EntityResolutionOutcome.CANDIDATES,
            EntityResolutionOutcome.AMBIGUOUS,
        }

    @property
    def platform_candidates(self) -> list[str]:
        values = {
            str(item.get("cli_platform"))
            for item in self.candidates
            if item.get("cli_platform")
        }
        return sorted(values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "decision": self.decision.value,
            "tenant_id": self.tenant_id,
            "metadata": copy.deepcopy(self.metadata),
            "retrieval_filters": copy.deepcopy(self.retrieval_filters),
            "product": copy.deepcopy(self.product),
            "os": copy.deepcopy(self.os),
            "version": copy.deepcopy(self.version),
            "candidates": copy.deepcopy(list(self.candidates)),
            "issues": [item.as_dict() for item in self.issues],
            "clarification_fields": list(self.clarification_fields),
            "truncated": self.truncated,
            "catalog_ready": self.catalog_ready,
            "driver_selection_allowed": self.driver_selection_allowed,
            "retrieval_eligible": self.retrieval_eligible,
            "metadata_hash": self.metadata_hash,
            "warnings": list(self.warnings),
        }


def _safe_text(value: Any, field: str, maximum: int = MAX_FIELD_LENGTH) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if len(text) > maximum or CONTROL_RE.search(text):
        raise ValueError(f"ENTITY_{field.upper()}_INVALID")
    return text


def _tenant(value: Any) -> str:
    tenant = _safe_text(value or "tenant-default", "tenant_id", 128)
    if not tenant:
        raise ValueError("ENTITY_TENANT_REQUIRED")
    return tenant


def _token(value: Any) -> str:
    text = _safe_text(value, "identity")
    if text.casefold() in UNKNOWN_TOKENS:
        return ""
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _canonical_vendor(value: Any) -> str:
    text = _safe_text(value, "vendor")
    if text.casefold() in UNKNOWN_TOKENS:
        return ""
    aliases = {
        "huawei": "huawei",
        "华为": "huawei",
        "cisco": "cisco",
        "思科": "cisco",
        "h3c": "h3c",
        "华三": "h3c",
        "新华三": "h3c",
        "hpcomware": "h3c",
        "ruijie": "ruijie",
        "锐捷": "ruijie",
        "all": "all",
    }
    return aliases.get(text.casefold(), text.casefold())


def _contains_secret(value: Any, key: str = "") -> bool:
    if SECRET_KEY_RE.search(key):
        return True
    if isinstance(value, Mapping):
        return any(_contains_secret(item, str(name)) for name, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return bool(
        re.search(
            r"(?i)(?:bearer\s+|api[_-]?key\s*[=:]|password\s*[=:]|-----begin)",
            str(value or ""),
        )
    )


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        raise ValueError("ENTITY_METADATA_INVALID")
    if _contains_secret(metadata):
        raise ValueError("ENTITY_METADATA_SECRET_FORBIDDEN")
    allowed = {
        "vendor",
        "product_type",
        "document_category",
        "product_family",
        "product_series",
        "product_model",
        "os_family",
        "os_generation",
        "software_train",
        "software_release",
        "cli_platform",
        "status",
        "source_type",
        "official_only",
        "document_id",
        "schema_version",
    }
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        name = _safe_text(key, "metadata_key", 64).casefold()
        if name not in allowed:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[name] = _safe_text(value, name) if isinstance(value, str) else value
    return result


def _metadata_hash(metadata: Mapping[str, Any]) -> str:
    payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _status_active(row: Mapping[str, Any]) -> bool:
    return _safe_text(row.get("status"), "status", 32).casefold() == "active"


def _row_tenant(row: Mapping[str, Any]) -> str:
    return _safe_text(row.get("tenant_id"), "tenant_id", 128)


def _display_model(row: Mapping[str, Any]) -> dict[str, Any]:
    scope = row.get("software_scope")
    scope = scope if isinstance(scope, Mapping) else {}
    advisory = row.get("platform_binding_advisory")
    advisory = advisory if isinstance(advisory, Mapping) else {}
    platform = advisory.get("cli_platform") or advisory.get("platform_code") or advisory.get("platform")
    if _contains_secret(platform, "cli_platform") or _contains_secret(scope):
        raise ValueError("ENTITY_CATALOG_SECRET_FORBIDDEN")
    scope_keys = {
        "os_family",
        "os_generation",
        "os",
        "generation",
        "software_train",
        "release_train",
        "train",
        "software_versions",
        "supported_versions",
        "reviewed_versions",
        "versions",
        "primary_version",
        "compatibility_version",
    }
    safe_scope: dict[str, Any] = {}
    for key in scope_keys:
        if key not in scope:
            continue
        value = scope[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe_scope[key] = _safe_text(value, key) if isinstance(value, str) else value
        elif isinstance(value, (list, tuple)):
            safe_scope[key] = [
                _safe_text(item, key) if isinstance(item, str) else _safe_text(item.get("version") or item.get("code") or "", key)
                if isinstance(item, Mapping)
                else _safe_text(item, key)
                for item in value
            ]
        elif isinstance(value, Mapping):
            safe_scope[key] = {
                _safe_text(name, key, 64): _safe_text(item, key)
                for name, item in value.items()
                if str(name) in {"version", "code", "status", "normalized_version"}
                and not isinstance(item, (Mapping, list, tuple))
            }
    return {
        "product_model_id": _safe_text(row.get("product_model_id"), "product_model_id", 256),
        "vendor_id": _safe_text(row.get("vendor_id"), "vendor_id", 64).casefold(),
        "vendor_name": _safe_text(row.get("vendor_name") or row.get("vendor_id"), "vendor_name"),
        "family_code": _safe_text(row.get("family_code"), "family_code", 64).casefold(),
        "family_name": _safe_text(row.get("family_name") or row.get("family_code"), "family_name"),
        "series_code": _safe_text(row.get("series_code"), "series_code", 64).casefold(),
        "series_name": _safe_text(row.get("series_name") or row.get("series_code"), "series_name"),
        "model_code": _safe_text(row.get("model_code"), "model_code"),
        "display_name": _safe_text(row.get("display_name") or row.get("model_code"), "display_name"),
        "status": "active",
        "review_status": _safe_text(row.get("review_status"), "review_status", 64),
        "software_scope": safe_scope,
        "cli_platform": _safe_text(platform, "cli_platform", 128),
    }


def _candidate_sort(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("vendor_id") or ""),
        str(item.get("series_code") or ""),
        str(item.get("product_model_id") or ""),
    )


def _scope_values(scope: Mapping[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = scope.get(key)
        if isinstance(value, (list, tuple)):
            values.extend(str(item) for item in value)
        elif isinstance(value, Mapping):
            for item in value.values():
                if isinstance(item, Mapping):
                    values.append(str(item.get("version") or item.get("code") or ""))
                else:
                    values.append(str(item))
        elif value is not None:
            values.append(str(value))
    return [item.strip() for item in values if item.strip()]


def _field_value(metadata: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if value is not None and _token(value):
            return _safe_text(value, key)
    return ""


def _unique(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _token(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(value)
    return output


def _load_snapshot(tenant_id: str) -> EntityCatalogSnapshot:
    from services.catalog_version_service import get_active_catalog_snapshot

    raw = get_active_catalog_snapshot(tenant_id=tenant_id)
    return EntityCatalogSnapshot.from_mapping(raw)


def _base_result(
    *,
    outcome: EntityResolutionOutcome,
    decision: EntityResolutionDecision,
    tenant_id: str,
    metadata: dict[str, Any],
    issues: Sequence[EntityResolutionIssue] = (),
    clarification_fields: Sequence[str] = (),
    candidates: Sequence[dict[str, Any]] = (),
    catalog_ready: bool = False,
    retrieval_eligible: bool = False,
    product: dict[str, Any] | None = None,
    os: dict[str, Any] | None = None,
    version: dict[str, Any] | None = None,
    warnings: Sequence[str] = (),
) -> DocumentEntityResolution:
    ordered = sorted((dict(item) for item in candidates), key=_candidate_sort)
    truncated = len(ordered) > MAX_CANDIDATES
    bounded = tuple(ordered[:MAX_CANDIDATES])
    return DocumentEntityResolution(
        outcome=outcome,
        decision=decision,
        tenant_id=tenant_id,
        metadata=copy.deepcopy(metadata),
        retrieval_filters=copy.deepcopy(metadata if retrieval_eligible else {}),
        product=copy.deepcopy(product),
        os=copy.deepcopy(os),
        version=copy.deepcopy(version),
        candidates=bounded,
        issues=tuple(issues),
        clarification_fields=tuple(sorted(set(clarification_fields))),
        truncated=truncated,
        catalog_ready=catalog_ready,
        retrieval_eligible=retrieval_eligible,
        metadata_hash=_metadata_hash(metadata),
        warnings=tuple(warnings),
    )


def resolve_document_entities(
    metadata: Mapping[str, Any] | None = None,
    *,
    tenant_id: str = "tenant-default",
    catalog: EntityCatalogSnapshot | Mapping[str, Any] | None = None,
    metadata_result: Any = None,
    catalog_loader: Callable[[str], EntityCatalogSnapshot] | None = None,
) -> DocumentEntityResolution:
    """Resolve Product, OS generation and Software Version without guessing."""

    tenant = _tenant(tenant_id)
    if metadata_result is not None:
        allowed = bool(getattr(metadata_result, "entity_resolution_allowed", False))
        source_metadata = getattr(metadata_result, "metadata", None)
        if source_metadata is not None:
            metadata = source_metadata
        if not allowed:
            try:
                safe = _safe_metadata(metadata or {})
            except ValueError:
                safe = {}
            return _base_result(
                outcome=EntityResolutionOutcome.QUARANTINED,
                decision=EntityResolutionDecision.QUARANTINE,
                tenant_id=tenant,
                metadata=safe,
                issues=(EntityResolutionIssue("ENTITY_UPSTREAM_QUARANTINED", "metadata", "block"),),
                clarification_fields=("metadata",),
            )
    try:
        safe = _safe_metadata(metadata or {})
    except ValueError as exc:
        return _base_result(
            outcome=EntityResolutionOutcome.CONFLICT,
            decision=EntityResolutionDecision.QUARANTINE,
            tenant_id=tenant,
            metadata={},
            issues=(EntityResolutionIssue(str(exc), "metadata", "block"),),
            clarification_fields=("metadata",),
        )

    try:
        snapshot = (
            catalog
            if isinstance(catalog, EntityCatalogSnapshot)
            else EntityCatalogSnapshot.from_mapping(catalog)
            if isinstance(catalog, Mapping)
            else (catalog_loader or _load_snapshot)(tenant)
        )
        if snapshot.tenant_id != tenant:
            return _base_result(
                outcome=EntityResolutionOutcome.CONFLICT,
                decision=EntityResolutionDecision.QUARANTINE,
                tenant_id=tenant,
                metadata=safe,
                issues=(EntityResolutionIssue("ENTITY_TENANT_SCOPE_DENIED", "tenant_id", "block"),),
                clarification_fields=("tenant_id",),
            )
        if snapshot.is_seed:
            return _base_result(
                outcome=EntityResolutionOutcome.UNKNOWN,
                decision=EntityResolutionDecision.REVIEW,
                tenant_id=tenant,
                metadata=safe,
                issues=(EntityResolutionIssue("ENTITY_CATALOG_REVIEW_ONLY", "catalog", "review"),),
                clarification_fields=("catalog",),
                warnings=("reviewed_seed_is_not_active_catalog",),
            )
    except Exception:
        return _base_result(
            outcome=EntityResolutionOutcome.DEPENDENCY_UNAVAILABLE,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            issues=(EntityResolutionIssue("ENTITY_CATALOG_UNAVAILABLE", "catalog", "review"),),
            clarification_fields=("catalog",),
        )

    try:
        models = [
            _display_model(row)
            for row in snapshot.models
            if _row_tenant(row) == tenant and _status_active(row)
        ]
        aliases = [
            row
            for row in snapshot.aliases
            if _safe_text(row.get("tenant_id"), "tenant_id", 128) == tenant
            and _safe_text(row.get("status"), "status", 32).casefold() == "active"
        ]
    except Exception:
        return _base_result(
            outcome=EntityResolutionOutcome.DEPENDENCY_UNAVAILABLE,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            issues=(EntityResolutionIssue("ENTITY_CATALOG_INVALID", "catalog", "review"),),
            clarification_fields=("catalog",),
            catalog_ready=True,
        )

    requested_vendor = _canonical_vendor(safe.get("vendor"))
    requested_model = _field_value(safe, "product_model")
    requested_series = _field_value(safe, "product_series")
    requested_family = _field_value(safe, "product_family")
    identity = requested_model or requested_series or requested_family
    candidates: list[dict[str, Any]] = []
    match_kind = "none"

    if requested_model:
        model_token = _token(requested_model)
        direct = [
            item
            for item in models
            if _token(item["model_code"]) == model_token
            or _token(item["display_name"]) == model_token
        ]
        alias_targets = {
            _safe_text(row.get("product_model_id"), "product_model_id", 256)
            for row in aliases
            if _token(row.get("alias")) == model_token
            and _safe_text(row.get("alias_kind"), "alias_kind", 32).casefold()
            in {"exact", "canonical"}
        }
        candidates = direct + [
            item for item in models
            if item["product_model_id"] in alias_targets and item not in direct
        ]
        match_kind = "exact" if direct else "alias"
        if not candidates:
            prefix_targets = {
                _safe_text(row.get("product_model_id"), "product_model_id", 256)
                for row in aliases
                if _token(row.get("alias")) == model_token
                and _safe_text(row.get("alias_kind"), "alias_kind", 32).casefold()
                in {"prefix", "trigram"}
            }
            candidates = [item for item in models if item["product_model_id"] in prefix_targets]
            match_kind = "candidate"
    elif requested_series:
        series_token = _token(requested_series)
        candidates = [
            item
            for item in models
            if _token(item["series_code"]) == series_token
            or _token(item["series_name"]) == series_token
            or _token(item["family_name"]) == series_token
        ]
        match_kind = "candidate"
    elif requested_family:
        family_token = _token(requested_family)
        candidates = [
            item
            for item in models
            if _token(item["family_code"]) == family_token
            or _token(item["family_name"]) == family_token
        ]
        match_kind = "candidate"

    vendor_candidates = [
        item
        for item in candidates
        if not requested_vendor or requested_vendor == "all" or item["vendor_id"] == requested_vendor
    ]
    if requested_vendor and requested_vendor != "all" and candidates and not vendor_candidates:
        return _base_result(
            outcome=EntityResolutionOutcome.CONFLICT,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            candidates=candidates,
            issues=(EntityResolutionIssue("ENTITY_VENDOR_CONFLICT", "vendor", "block"),),
            clarification_fields=("vendor", "product_model"),
            catalog_ready=True,
        )
    candidates = vendor_candidates
    if not identity:
        return _base_result(
            outcome=EntityResolutionOutcome.UNKNOWN,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            issues=(EntityResolutionIssue("ENTITY_PRODUCT_REQUIRED", "product_model", "review"),),
            clarification_fields=("product_model", "product_series"),
            catalog_ready=True,
        )
    if not candidates:
        return _base_result(
            outcome=EntityResolutionOutcome.UNKNOWN,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            issues=(EntityResolutionIssue("ENTITY_PRODUCT_UNKNOWN", "product_model", "review"),),
            clarification_fields=("product_model",),
            catalog_ready=True,
        )
    if len({item["product_model_id"] for item in candidates}) > 1 or match_kind == "candidate":
        return _base_result(
            outcome=EntityResolutionOutcome.AMBIGUOUS,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            candidates=candidates,
            issues=(EntityResolutionIssue("ENTITY_PRODUCT_AMBIGUOUS", "product_model", "review"),),
            clarification_fields=("product_model",),
            catalog_ready=True,
        )

    product = dict(candidates[0])
    scope = product.get("software_scope") or {}
    requested_os = _field_value(safe, "os_family")
    requested_generation = _field_value(safe, "os_generation")
    requested_train = _field_value(safe, "software_train")
    requested_release = _field_value(safe, "software_release")
    os_family = _scope_values(scope, "os_family", "os")
    os_generation = _scope_values(scope, "os_generation", "generation")
    trains = _scope_values(scope, "software_train", "release_train", "train")
    versions = _unique(
        _scope_values(
            scope,
            "software_versions",
            "supported_versions",
            "reviewed_versions",
            "versions",
            "primary_version",
            "compatibility_version",
        )
    )
    issues: list[EntityResolutionIssue] = []
    os_result = None
    version_result = None
    for field_name, requested, values in (
        ("os_family", requested_os, os_family),
        ("os_generation", requested_generation, os_generation),
        ("software_train", requested_train, trains),
    ):
        if requested and values and not any(_token(requested) == _token(value) for value in values):
            issues.append(EntityResolutionIssue("ENTITY_SCOPE_CONFLICT", field_name, "block"))
    if requested_release and (
        not versions
        or not any(_token(requested_release) == _token(value) for value in versions)
    ):
        issues.append(EntityResolutionIssue("ENTITY_VERSION_UNVERIFIED", "software_release", "review"))

    if os_family or os_generation:
        os_result = {
            "family": os_family[0] if os_family else requested_os or None,
            "generation": os_generation[0] if os_generation else requested_generation or None,
            "status": "resolved" if not issues else "review",
        }
    if requested_release:
        version_result = {
            "original": requested_release,
            "normalized": requested_release,
            "status": "resolved"
            if any(_token(requested_release) == _token(value) for value in versions)
            else "review",
        }
    if issues and any(item.severity == "block" for item in issues):
        return _base_result(
            outcome=EntityResolutionOutcome.CONFLICT,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            product=product,
            os=os_result,
            version=version_result,
            issues=issues,
            clarification_fields=("os_family", "os_generation", "software_train", "software_release"),
            catalog_ready=True,
        )

    complete = bool(
        requested_os
        and requested_train
        and requested_release
        and version_result
        and version_result["status"] == "resolved"
    )
    if not complete:
        clarification = [
            field
            for field, value in (
                ("os_family", requested_os),
                ("software_train", requested_train),
                ("software_release", requested_release),
            )
            if not value
        ]
        if not versions and requested_release:
            issues.append(EntityResolutionIssue("ENTITY_VERSION_SCOPE_MISSING", "software_release", "review"))
        return _base_result(
            outcome=EntityResolutionOutcome.UNKNOWN,
            decision=EntityResolutionDecision.REVIEW,
            tenant_id=tenant,
            metadata=safe,
            product=product,
            os=os_result,
            version=version_result,
            issues=issues,
            clarification_fields=clarification or ("software_release",),
            catalog_ready=True,
        )

    resolved = dict(safe)
    resolved["vendor"] = product["vendor_name"]
    resolved["product_family"] = product["family_name"]
    resolved["product_series"] = product["series_name"]
    resolved["product_model"] = product["model_code"]
    resolved["os_family"] = os_result["family"] if os_result else requested_os
    resolved["software_train"] = requested_train
    resolved["software_release"] = version_result["normalized"]
    if product.get("cli_platform") and not _field_value(safe, "cli_platform"):
        resolved["cli_platform"] = product["cli_platform"]
    return DocumentEntityResolution(
        outcome=EntityResolutionOutcome.RESOLVED,
        decision=EntityResolutionDecision.PROCEED,
        tenant_id=tenant,
        metadata=copy.deepcopy(safe),
        retrieval_filters=resolved,
        product=product,
        os=os_result,
        version=version_result,
        candidates=(product,),
        catalog_ready=True,
        retrieval_eligible=True,
        metadata_hash=_metadata_hash(safe),
    )


resolve_entities = resolve_document_entities
