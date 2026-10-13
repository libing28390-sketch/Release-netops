"""CAT-015 versioned Product Catalog import, diff, and rollback boundary.

DB-006 deliberately freezes the relational catalog contract without applying
production DDL.  This module therefore provides a tenant-scoped, process-local
version registry over the reviewed seeds.  The validation, diff, optimistic
concurrency, audit, and rollback semantics are the same boundary a later
repository can persist without changing the API contract.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ai.services.product_alias_service import ProductAliasError, normalize_alias
from services.product_catalog_service import _ALIAS_FILE, _seed_model_rows


PERSISTENCE_STATUS = "contract_only_ephemeral_version_registry"
DEFAULT_TENANT = "tenant-default-reviewed"
MODEL_STATUSES = {"draft", "active", "disabled", "archived", "deleted", "purged"}
ALIAS_KINDS = {"exact", "canonical", "prefix", "trigram"}
ALIAS_STATUSES = MODEL_STATUSES
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SENSITIVE_KEY_PARTS = (
    "password", "passwd", "token", "secret", "private_key", "authorization",
    "cookie", "community", "credential", "api_key", "apikey",
)
MAX_MODELS = 5_000
MAX_ALIASES = 10_000
MAX_DIFF_ITEMS = 200

AuditWriter = Callable[[str, dict[str, Any]], str]


class CatalogVersionError(ValueError):
    """Stable, user-safe error returned by the CAT-015 boundary."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


_LOCK = threading.RLock()
_STATES: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tenant(user: dict[str, Any]) -> str:
    return str(user.get("tenant_id") or DEFAULT_TENANT).strip() or DEFAULT_TENANT


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system").strip() or "system"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _assert_safe(value: Any, path: str = "bundle") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                raise CatalogVersionError("SECRET_FIELD_FORBIDDEN", f"Secret-bearing field is not allowed in {path}.{key}")
            _assert_safe(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe(item, f"{path}[{index}]")
    elif isinstance(value, str):
        if CONTROL_RE.search(value):
            raise CatalogVersionError("CONTROL_CHARACTER_FORBIDDEN", f"Control character is not allowed in {path}")
        lowered = value.lower()
        if "bearer " in lowered or "basic " in lowered:
            raise CatalogVersionError("SECRET_VALUE_FORBIDDEN", "Authorization material is not allowed in a catalog bundle")


def _text(value: Any, *, field: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or CONTROL_RE.search(text):
        raise CatalogVersionError("BUNDLE_FIELD_INVALID", f"{field} is required and bounded")
    return text


def _seed_aliases(model_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        raw = yaml.safe_load(_ALIAS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogVersionError("CATALOG_SEED_UNAVAILABLE", "Alias seed is unavailable", status_code=503) from exc
    model_ids = {str(row.get("product_model_id")) for row in model_rows}
    output: list[dict[str, Any]] = []
    for item in raw.get("alias_samples") or []:
        if not isinstance(item, dict) or str(item.get("product_model_id") or "") not in model_ids:
            continue
        try:
            normalized = normalize_alias(item.get("alias"))
        except ProductAliasError as exc:
            raise CatalogVersionError("CATALOG_SEED_INVALID", "Alias seed contains an invalid alias", details={"code": exc.code}, status_code=503) from exc
        output.append({
            "id": str(item.get("sample_id") or ""),
            "tenant_id": str(item.get("tenant_id") or DEFAULT_TENANT),
            "product_model_id": str(item.get("product_model_id")),
            "alias": str(item.get("alias") or "").strip(),
            "normalized_alias": normalized,
            "alias_kind": str(item.get("alias_kind") or ""),
            "status": str(item.get("status") or "draft").strip().lower(),
        })
    return sorted(output, key=lambda row: (row["normalized_alias"], row["alias_kind"], row["product_model_id"]))


def _normalize_model(raw: Any, tenant_id: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CatalogVersionError("BUNDLE_MODEL_INVALID", f"models[{index}] must be an object")
    _assert_safe(raw, f"models[{index}]")
    requested_tenant = str(raw.get("tenant_id") or tenant_id).strip()
    if requested_tenant != tenant_id:
        raise CatalogVersionError("TENANT_SCOPE_DENIED", "Catalog version cannot cross tenant boundaries", status_code=403)
    status = str(raw.get("status") or "draft").strip().lower()
    if status not in MODEL_STATUSES:
        raise CatalogVersionError("MODEL_STATUS_INVALID", "Catalog model status is invalid")
    scope = raw.get("software_scope") or {}
    if not isinstance(scope, dict):
        raise CatalogVersionError("SOFTWARE_SCOPE_INVALID", "software_scope must be an object")
    advisory = raw.get("platform_binding_advisory") or {}
    if not isinstance(advisory, dict):
        raise CatalogVersionError("PLATFORM_ADVISORY_INVALID", "platform_binding_advisory must be an object")
    if bool(advisory.get("driver_authority")) or bool(advisory.get("execution_write_authority")):
        raise CatalogVersionError("DRIVER_AUTHORITY_FORBIDDEN", "A catalog version cannot grant driver or write authority")
    normalized_scope = copy.deepcopy(scope)
    normalized_advisory = copy.deepcopy(advisory)
    return {
        "product_model_id": _text(raw.get("product_model_id"), field=f"models[{index}].product_model_id", maximum=256),
        "tenant_id": tenant_id,
        "vendor_id": _text(raw.get("vendor_id"), field=f"models[{index}].vendor_id", maximum=64).casefold(),
        "vendor_name": _text(raw.get("vendor_name") or raw.get("vendor_id"), field=f"models[{index}].vendor_name", maximum=256),
        "family_code": _text(raw.get("family_code"), field=f"models[{index}].family_code", maximum=64).casefold(),
        "family_name": _text(raw.get("family_name") or raw.get("family_code"), field=f"models[{index}].family_name", maximum=256),
        "series_code": _text(raw.get("series_code"), field=f"models[{index}].series_code", maximum=64).casefold(),
        "series_name": _text(raw.get("series_name") or raw.get("series_code"), field=f"models[{index}].series_name", maximum=256),
        "model_code": _text(raw.get("model_code"), field=f"models[{index}].model_code", maximum=128),
        "display_name": _text(raw.get("display_name") or raw.get("model_code"), field=f"models[{index}].display_name", maximum=256),
        "status": status,
        "review_status": str(raw.get("review_status") or "pending_review").strip().lower(),
        "source_refs": [str(item) for item in (raw.get("source_refs") or [])][:32],
        "software_scope": normalized_scope,
        "platform_binding_advisory": normalized_advisory,
        "source_artifact": str(raw.get("source_artifact") or "CAT-015-import").strip()[:256],
    }


def _normalize_alias(raw: Any, tenant_id: str, index: int, model_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CatalogVersionError("BUNDLE_ALIAS_INVALID", f"aliases[{index}] must be an object")
    _assert_safe(raw, f"aliases[{index}]")
    requested_tenant = str(raw.get("tenant_id") or tenant_id).strip()
    if requested_tenant != tenant_id:
        raise CatalogVersionError("TENANT_SCOPE_DENIED", "Catalog version cannot cross tenant boundaries", status_code=403)
    model_id = _text(raw.get("product_model_id"), field=f"aliases[{index}].product_model_id", maximum=256)
    if model_id not in model_ids:
        raise CatalogVersionError("ALIAS_MODEL_NOT_FOUND", "Alias target is not present in the imported model set")
    alias_kind = str(raw.get("alias_kind") or "").strip().lower()
    if alias_kind not in ALIAS_KINDS:
        raise CatalogVersionError("ALIAS_KIND_INVALID", "Alias kind is not in the DB-006 allowlist")
    alias = _text(raw.get("alias"), field=f"aliases[{index}].alias", maximum=256)
    try:
        normalized = normalize_alias(alias)
    except ProductAliasError as exc:
        raise CatalogVersionError("ALIAS_INVALID", "Alias normalization failed", details={"code": exc.code}) from exc
    status = str(raw.get("status") or "draft").strip().lower()
    if status not in ALIAS_STATUSES:
        raise CatalogVersionError("ALIAS_STATUS_INVALID", "Alias status is invalid")
    return {
        "id": str(raw.get("id") or f"alias-{uuid.uuid4().hex[:12]}"),
        "tenant_id": tenant_id,
        "product_model_id": model_id,
        "alias": alias,
        "normalized_alias": normalized,
        "alias_kind": alias_kind,
        "status": status,
    }


def _snapshot(version: str, tenant_id: str, models: list[dict[str, Any]], aliases: list[dict[str, Any]], *, is_seed: bool, created_by: str) -> dict[str, Any]:
    body = {
        "version": version,
        "tenant_id": tenant_id,
        "models": sorted(models, key=lambda row: row["product_model_id"]),
        "aliases": sorted(aliases, key=lambda row: (row["normalized_alias"], row["alias_kind"], row["product_model_id"])),
    }
    content_hash = hashlib.sha256(_json(body).encode("utf-8")).hexdigest()
    return {
        **body,
        "content_hash": content_hash,
        "version_id": f"{version}:{content_hash[:12]}",
        "is_seed": is_seed,
        "created_by": created_by,
        "created_at": _now(),
    }


def _prepare_bundle(user: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise CatalogVersionError("BUNDLE_INVALID", "Catalog version bundle must be an object")
    _assert_safe(bundle)
    tenant_id = _tenant(user)
    version = _text(bundle.get("version"), field="version", maximum=64)
    if not VERSION_RE.fullmatch(version):
        raise CatalogVersionError("VERSION_INVALID", "version must use bounded letters, numbers, dot, underscore, or dash")
    raw_models = bundle.get("models")
    if not isinstance(raw_models, list) or not raw_models or len(raw_models) > MAX_MODELS:
        raise CatalogVersionError("MODEL_COUNT_INVALID", f"models must contain 1..{MAX_MODELS} rows")
    models = [_normalize_model(item, tenant_id, index) for index, item in enumerate(raw_models)]
    model_ids = [row["product_model_id"] for row in models]
    if len(set(model_ids)) != len(model_ids):
        raise CatalogVersionError("MODEL_DUPLICATE", "product_model_id must be unique within a version")
    if "aliases" not in bundle:
        raise CatalogVersionError("ALIAS_SET_REQUIRED", "A version bundle must explicitly include its Alias set")
    raw_aliases = bundle.get("aliases") or []
    if not isinstance(raw_aliases, list) or len(raw_aliases) > MAX_ALIASES:
        raise CatalogVersionError("ALIAS_COUNT_INVALID", f"aliases must contain 0..{MAX_ALIASES} rows")
    aliases = [_normalize_alias(item, tenant_id, index, set(model_ids)) for index, item in enumerate(raw_aliases)]
    alias_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in aliases:
        alias_groups.setdefault((row["normalized_alias"], row["alias_kind"]), []).append(row)
    for grouped in alias_groups.values():
        if len(grouped) > 1 and any(row["status"] == "active" for row in grouped):
            raise CatalogVersionError("ALIAS_DUPLICATE_ACTIVE", "An ambiguous Alias must remain pending review before activation")
    return _snapshot(version, tenant_id, models, aliases, is_seed=False, created_by=_actor(user))


def _state_for(tenant_id: str) -> dict[str, Any]:
    state = _STATES.get(tenant_id)
    if state is not None:
        return state
    seed_models = [row for row in _seed_model_rows() if str(row.get("tenant_id")) == tenant_id]
    seed_aliases = _seed_aliases(seed_models)
    seed = _snapshot("seed", tenant_id, seed_models, seed_aliases, is_seed=True, created_by="system")
    state = {"active_version_id": seed["version_id"], "history": {seed["version_id"]: seed}, "audit": []}
    _STATES[tenant_id] = state
    return state


def _metadata(snapshot: dict[str, Any], active_version_id: str) -> dict[str, Any]:
    return {
        "version_id": snapshot["version_id"],
        "version": snapshot["version"],
        "content_hash": snapshot["content_hash"],
        "tenant_id": snapshot["tenant_id"],
        "active": snapshot["version_id"] == active_version_id,
        "is_seed": snapshot["is_seed"],
        "model_count": len(snapshot["models"]),
        "alias_count": len(snapshot["aliases"]),
        "created_by": snapshot["created_by"],
        "created_at": snapshot["created_at"],
    }


def _diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    counts = {"model": {"added": 0, "removed": 0, "changed": 0}, "alias": {"added": 0, "removed": 0, "changed": 0}}
    for entity, key_fn in (
        ("model", lambda row: row["product_model_id"]),
        ("alias", lambda row: f"{row['normalized_alias']}|{row['alias_kind']}"),
    ):
        old = {key_fn(row): row for row in before["models" if entity == "model" else "aliases"]}
        new = {key_fn(row): row for row in after["models" if entity == "model" else "aliases"]}
        for key in sorted(set(old) | set(new)):
            if key not in old:
                action = "added"
            elif key not in new:
                action = "removed"
            elif old[key] != new[key]:
                action = "changed"
            else:
                continue
            counts[entity][action] += 1
            if len(changes) < MAX_DIFF_ITEMS:
                changes.append({"entity": entity, "action": action, "key": key, "before": old.get(key), "after": new.get(key)})
    return {
        "counts": counts,
        "total_changes": sum(sum(item.values()) for item in counts.values()),
        "truncated": sum(sum(item.values()) for item in counts.values()) > MAX_DIFF_ITEMS,
        "items": changes,
    }


def _audit(state: dict[str, Any], operation: str, user: dict[str, Any], details: dict[str, Any], writer: AuditWriter | None) -> str:
    safe_details = {
        "operation": operation,
        "actor": _actor(user),
        "tenant_id": details.get("tenant_id"),
        "before_version_id": details.get("before_version_id"),
        "after_version_id": details.get("after_version_id"),
        "content_hash": details.get("content_hash"),
        "total_changes": details.get("total_changes", 0),
        "persistence_status": PERSISTENCE_STATUS,
    }
    event_id = writer(operation, safe_details) if writer else f"audit-{uuid.uuid4().hex}"
    state["audit"].append({"event_id": event_id, "created_at": _now(), **safe_details})
    del state["audit"][:-100]
    return event_id


def get_active_catalog_rows(*, tenant_id: str | None = None) -> list[dict[str, Any]] | None:
    """Return imported rows for a tenant, or ``None`` to use reviewed seeds."""
    tenant = tenant_id or DEFAULT_TENANT
    with _LOCK:
        state = _state_for(tenant)
        active = state["history"][state["active_version_id"]]
        if active["is_seed"]:
            return None
        return copy.deepcopy(active["models"])


def get_active_catalog_snapshot(*, tenant_id: str | None = None) -> dict[str, Any]:
    """Return the tenant-scoped read-only model and Alias snapshot.

    The reviewed seed is surfaced explicitly as ``is_seed`` so consumers
    cannot mistake contract-only draft rows for active production entities.
    """
    tenant = tenant_id or DEFAULT_TENANT
    with _LOCK:
        state = _state_for(tenant)
        active = copy.deepcopy(state["history"][state["active_version_id"]])
    return {
        "tenant_id": tenant,
        "version_id": active["version_id"],
        "is_seed": bool(active["is_seed"]),
        "models": active["models"],
        "aliases": active["aliases"],
        "source": PERSISTENCE_STATUS,
    }


def list_catalog_versions(user: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _tenant(user)
    with _LOCK:
        state = _state_for(tenant_id)
        versions = [_metadata(item, state["active_version_id"]) for item in state["history"].values()]
        versions.sort(key=lambda item: (not item["active"], item["created_at"], item["version_id"]))
        return {
            "persistence_status": PERSISTENCE_STATUS,
            "tenant_id": tenant_id,
            "active_version_id": state["active_version_id"],
            "versions": versions,
            "audit_events": copy.deepcopy(state["audit"]),
            "rollback_supported": True,
        }


def preview_catalog_version(user: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    tenant_id = _tenant(user)
    try:
        candidate = _prepare_bundle(user, bundle)
    except CatalogVersionError as exc:
        if exc.code == "TENANT_SCOPE_DENIED":
            raise
        return {
            "persistence_status": PERSISTENCE_STATUS,
            "tenant_id": tenant_id,
            "dry_run": True,
            "valid": False,
            "can_import": False,
            "validation": {"errors": [{"code": exc.code, "message": exc.message, "details": exc.details}]},
            "diff": {"counts": {}, "total_changes": 0, "truncated": False, "items": []},
        }
    with _LOCK:
        state = _state_for(tenant_id)
        active = state["history"][state["active_version_id"]]
        diff = _diff(active, candidate)
        return {
            "persistence_status": PERSISTENCE_STATUS,
            "tenant_id": tenant_id,
            "dry_run": True,
            "valid": True,
            "can_import": diff["total_changes"] > 0,
            "baseline": _metadata(active, state["active_version_id"]),
            "candidate": _metadata(candidate, ""),
            "validation": {"errors": []},
            "diff": diff,
            "rollback_target_version_id": state["active_version_id"],
        }


def import_catalog_version(
    user: dict[str, Any],
    bundle: dict[str, Any],
    *,
    expected_active_version_id: str = "",
    confirm: bool = False,
    audit_writer: AuditWriter | None = None,
) -> dict[str, Any]:
    if not confirm:
        raise CatalogVersionError("IMPORT_CONFIRMATION_REQUIRED", "Import requires explicit confirm=true")
    candidate = _prepare_bundle(user, bundle)
    tenant_id = _tenant(user)
    with _LOCK:
        state = _state_for(tenant_id)
        active = state["history"][state["active_version_id"]]
        if expected_active_version_id and expected_active_version_id != state["active_version_id"]:
            raise CatalogVersionError("STALE_ACTIVE_VERSION", "Active catalog changed; refresh the diff before importing", status_code=409)
        if candidate["version_id"] in state["history"]:
            existing = state["history"][candidate["version_id"]]
            if existing["content_hash"] == candidate["content_hash"]:
                raise CatalogVersionError("CATALOG_VERSION_NOOP", "This catalog version is already imported", status_code=409)
            raise CatalogVersionError("CATALOG_VERSION_CONFLICT", "Version label is already used for different content", status_code=409)
        diff = _diff(active, candidate)
        if diff["total_changes"] == 0:
            raise CatalogVersionError("CATALOG_VERSION_NOOP", "Import would not change the active catalog", status_code=409)
        audit_id = _audit(state, "import", user, {
            "tenant_id": tenant_id,
            "before_version_id": state["active_version_id"],
            "after_version_id": candidate["version_id"],
            "content_hash": candidate["content_hash"],
            "total_changes": diff["total_changes"],
        }, audit_writer)
        state["history"][candidate["version_id"]] = candidate
        state["active_version_id"] = candidate["version_id"]
        return {
            "persistence_status": PERSISTENCE_STATUS,
            "tenant_id": tenant_id,
            "imported": True,
            "active_version_id": candidate["version_id"],
            "rollback_target_version_id": active["version_id"],
            "diff": diff,
            "audit_event_id": audit_id,
        }


def rollback_catalog_version(
    user: dict[str, Any],
    target_version_id: str,
    *,
    expected_active_version_id: str = "",
    confirm: bool = False,
    audit_writer: AuditWriter | None = None,
) -> dict[str, Any]:
    if not confirm:
        raise CatalogVersionError("ROLLBACK_CONFIRMATION_REQUIRED", "Rollback requires explicit confirm=true")
    target_id = _text(target_version_id, field="target_version_id", maximum=128)
    tenant_id = _tenant(user)
    with _LOCK:
        state = _state_for(tenant_id)
        active_id = state["active_version_id"]
        if expected_active_version_id and expected_active_version_id != active_id:
            raise CatalogVersionError("STALE_ACTIVE_VERSION", "Active catalog changed; refresh before rollback", status_code=409)
        if target_id not in state["history"]:
            raise CatalogVersionError("CATALOG_VERSION_NOT_FOUND", "Rollback target was not found", status_code=404)
        if target_id == active_id:
            raise CatalogVersionError("ROLLBACK_NOOP", "Catalog is already active at the requested version", status_code=409)
        target = state["history"][target_id]
        active = state["history"][active_id]
        diff = _diff(active, target)
        audit_id = _audit(state, "rollback", user, {
            "tenant_id": tenant_id,
            "before_version_id": active_id,
            "after_version_id": target_id,
            "content_hash": target["content_hash"],
            "total_changes": diff["total_changes"],
        }, audit_writer)
        state["active_version_id"] = target_id
        return {
            "persistence_status": PERSISTENCE_STATUS,
            "tenant_id": tenant_id,
            "rolled_back": True,
            "active_version_id": target_id,
            "previous_active_version_id": active_id,
            "diff": diff,
            "audit_event_id": audit_id,
        }


def reset_catalog_version_state_for_tests() -> None:
    with _LOCK:
        _STATES.clear()
