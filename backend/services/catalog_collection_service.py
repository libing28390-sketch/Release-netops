"""CAT-018 boundary between immutable official catalog facts and custom collections.

The collection repository remains gated by DB-001/DB-013.  This
adapter therefore keeps custom collection metadata in a process-local registry,
but enforces the production contract now: official catalog rows are always
read-only, custom rows are tenant-scoped, and a custom collection can only hold
opaque references to catalog models rather than copying or editing their facts.
"""

from __future__ import annotations

import copy
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from core.rbac import authorize_resource


PERSISTENCE_STATUS = "contract_only_ephemeral_custom_collection_registry"
DEFAULT_TENANT = "tenant-default-reviewed"
CUSTOM_KIND = "custom"
OFFICIAL_KIND = "official_catalog"
COLLECTION_STATUSES = {"draft", "active", "disabled", "archived"}
_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ACL_KEYS = {"allowed_roles", "allowed_user_ids", "allowed_site_ids", "deny_roles", "deny_user_ids"}
_MAX_ACL_ITEMS = 500
_MAX_MODEL_REFS = 500

AuditWriter = Callable[[str, dict[str, Any]], str]


class CatalogCollectionError(ValueError):
    """Stable, user-safe error returned by the CAT-018 boundary."""

    def __init__(self, code: str, message: str, *, status_code: int = 400, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


_LOCK = threading.RLock()
_STATES: dict[str, dict[str, dict[str, Any]]] = {}


def _now() -> str:
    # Keep microseconds so two rapid mutations cannot share an optimistic
    # concurrency token.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _next_timestamp(previous: str) -> str:
    """Return a strictly newer optimistic-concurrency token.

    A create followed immediately by an update can observe the same wall-clock
    microsecond on platforms whose clock resolution is coarser than the
    formatter.  CAS tokens must still change in that case.
    """

    current = _now()
    try:
        previous_dt = datetime.fromisoformat(str(previous).replace("Z", "+00:00"))
        current_dt = datetime.fromisoformat(current.replace("Z", "+00:00"))
        if current_dt <= previous_dt:
            current_dt = previous_dt + timedelta(microseconds=1)
            return current_dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (TypeError, ValueError):
        # Existing malformed legacy state is not a reason to reject a new
        # mutation; the next valid timestamp repairs the CAS token.
        pass
    return current


def _tenant(user: dict[str, Any]) -> str:
    tenant = str(user.get("tenant_id") or DEFAULT_TENANT).strip()
    return tenant or DEFAULT_TENANT


def _actor(user: dict[str, Any]) -> str:
    return str(user.get("id") or user.get("user_id") or user.get("username") or "system").strip() or "system"


def _authorize(user: dict[str, Any], action: str, tenant_id: str) -> None:
    if not authorize_resource(user, "knowledge_collection", action, tenant_id=tenant_id):
        raise CatalogCollectionError("COLLECTION_PERMISSION_DENIED", "Insufficient permission for custom collection operation", status_code=403)


def _text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if len(text) > maximum or _CONTROL_RE.search(text) or (required and not text):
        raise CatalogCollectionError("COLLECTION_FIELD_INVALID", f"{field} is invalid")
    return text


def _acl(value: Any) -> dict[str, list[str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CatalogCollectionError("COLLECTION_ACL_INVALID", "acl must be an object")
    unknown = set(value) - _ACL_KEYS
    if unknown:
        raise CatalogCollectionError("COLLECTION_ACL_FIELD_FORBIDDEN", "acl contains an unsupported field")
    result: dict[str, list[str]] = {}
    for key in _ACL_KEYS:
        raw = value.get(key, [])
        if not isinstance(raw, list) or len(raw) > _MAX_ACL_ITEMS:
            raise CatalogCollectionError("COLLECTION_ACL_INVALID", "acl entries are bounded lists")
        items: list[str] = []
        for item in raw:
            text = _text(item, field=f"acl.{key}", maximum=128, required=True)
            items.append(text)
        result[key] = sorted(set(items))
    return result


def _model_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > _MAX_MODEL_REFS:
        raise CatalogCollectionError("COLLECTION_MODEL_REFS_INVALID", "catalog_model_refs must be a bounded list")
    refs = [_text(item, field="catalog_model_refs", maximum=256, required=True) for item in value]
    return sorted(set(refs))


def _boundary() -> dict[str, Any]:
    return {
        "official_catalog": {
            "collection_kind": OFFICIAL_KIND,
            "read_only": True,
            "mutable": False,
            "mutation_routes": [],
            "authority": "reviewed_product_catalog_artifacts_and_controlled_version_gate",
        },
        "custom_collection": {
            "collection_kind": CUSTOM_KIND,
            "read_only": False,
            "mutable": True,
            "tenant_scoped": True,
            "persistence_status": PERSISTENCE_STATUS,
            "official_rows_are_references_only": True,
        },
    }


def _state(tenant_id: str) -> dict[str, dict[str, Any]]:
    return _STATES.setdefault(tenant_id, {})


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(row)


def _audit(user: dict[str, Any], operation: str, row: dict[str, Any], *, before_status: str = "", writer: AuditWriter | None = None) -> str:
    details = {
        "operation": operation,
        "actor": _actor(user),
        "tenant_id": row["tenant_id"],
        "collection_id": row["id"],
        "collection_kind": row["collection_kind"],
        "before_status": before_status,
        "after_status": row["status"],
        "persistence_status": PERSISTENCE_STATUS,
    }
    event_id = writer(operation, details) if writer else f"audit-{uuid.uuid4().hex}"
    row.setdefault("audit_events", []).append({"event_id": event_id, "created_at": _now(), **details})
    row["audit_events"] = row["audit_events"][-100:]
    return event_id


def reset_catalog_collection_state_for_tests() -> None:
    with _LOCK:
        _STATES.clear()


def collection_boundary() -> dict[str, Any]:
    return {"persistence_status": PERSISTENCE_STATUS, **_boundary()}


def list_custom_collections(user: dict[str, Any], *, status: str = "all") -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, "read", tenant_id)
    status_filter = _text(status, field="status", maximum=32).casefold() or "all"
    if status_filter != "all" and status_filter not in COLLECTION_STATUSES:
        raise CatalogCollectionError("COLLECTION_STATUS_INVALID", "status filter is invalid")
    with _LOCK:
        rows = [row for row in _state(tenant_id).values() if status_filter == "all" or row["status"] == status_filter]
        rows.sort(key=lambda row: (row["code"], row["id"]))
        return {
            "persistence_status": PERSISTENCE_STATUS,
            "tenant_id": tenant_id,
            "collection_kind": CUSTOM_KIND,
            "read_only": False,
            "items": [_public(row) for row in rows],
            "total": len(rows),
            "boundary": _boundary(),
        }


def create_custom_collection(user: dict[str, Any], payload: dict[str, Any], *, audit_writer: AuditWriter | None = None) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, "create", tenant_id)
    if not isinstance(payload, dict):
        raise CatalogCollectionError("COLLECTION_PAYLOAD_INVALID", "collection payload must be an object")
    allowed = {"code", "name", "description", "acl", "catalog_model_refs"}
    if set(payload) - allowed:
        if set(payload) & {"collection_kind", "is_official", "official", "source_artifact"}:
            raise CatalogCollectionError("COLLECTION_KIND_SERVER_AUTHORITY", "collection kind is server-controlled")
        raise CatalogCollectionError("COLLECTION_FIELD_FORBIDDEN", "Collection field is not accepted")
    if any(key in payload for key in ("collection_kind", "is_official", "official", "source_artifact")):
        raise CatalogCollectionError("COLLECTION_KIND_SERVER_AUTHORITY", "collection kind is server-controlled")
    code = _text(payload.get("code"), field="code", maximum=64, required=True).casefold()
    if not _CODE_RE.fullmatch(code):
        raise CatalogCollectionError("COLLECTION_CODE_INVALID", "code must be a lowercase bounded slug")
    name = _text(payload.get("name"), field="name", maximum=128, required=True)
    description = _text(payload.get("description"), field="description", maximum=1024)
    acl = _acl(payload.get("acl"))
    model_refs = _model_refs(payload.get("catalog_model_refs"))
    with _LOCK:
        state = _state(tenant_id)
        if any(row["code"] == code for row in state.values()):
            raise CatalogCollectionError("COLLECTION_CODE_CONFLICT", "A custom collection with this code already exists", status_code=409)
        now = _now()
        row = {
            "id": f"custom:{tenant_id}:{uuid.uuid4().hex}",
            "tenant_id": tenant_id,
            "code": code,
            "name": name,
            "description": description,
            "collection_kind": CUSTOM_KIND,
            "status": "draft",
            "acl": acl,
            "catalog_model_refs": model_refs,
            "official": False,
            "read_only": False,
            "mutable_fields": ["name", "description", "acl", "catalog_model_refs", "status"],
            "created_at": now,
            "updated_at": now,
            "created_by": _actor(user),
            "updated_by": _actor(user),
            "audit_events": [],
        }
        _audit(user, "create", row, writer=audit_writer)
        state[row["id"]] = row
        return _public(row)


def update_custom_collection(
    user: dict[str, Any],
    collection_id: str,
    payload: dict[str, Any],
    *,
    expected_updated_at: str = "",
    audit_writer: AuditWriter | None = None,
) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, "update", tenant_id)
    if not isinstance(payload, dict):
        raise CatalogCollectionError("COLLECTION_PAYLOAD_INVALID", "collection payload must be an object")
    forbidden = set(payload) & {"id", "tenant_id", "code", "collection_kind", "is_official", "official", "created_at", "created_by", "source_artifact"}
    if forbidden:
        code = "COLLECTION_OFFICIAL_READ_ONLY" if "collection_kind" in forbidden or "is_official" in forbidden or "official" in forbidden else "COLLECTION_IDENTITY_IMMUTABLE"
        raise CatalogCollectionError(code, "Official catalog identity and tenant fields are immutable")
    allowed = {"name", "description", "acl", "catalog_model_refs", "status"}
    if set(payload) - allowed:
        raise CatalogCollectionError("COLLECTION_FIELD_FORBIDDEN", "Collection field is not mutable")
    with _LOCK:
        row = _state(tenant_id).get(str(collection_id).strip())
        if not row:
            raise CatalogCollectionError("COLLECTION_NOT_FOUND", "Custom collection was not found", status_code=404)
        if row.get("collection_kind") != CUSTOM_KIND or row.get("official"):
            raise CatalogCollectionError("COLLECTION_OFFICIAL_READ_ONLY", "Official catalog collections are read-only", status_code=403)
        if row["status"] == "archived":
            raise CatalogCollectionError("COLLECTION_ARCHIVED", "Archived custom collections cannot be edited", status_code=409)
        if expected_updated_at and expected_updated_at != row["updated_at"]:
            raise CatalogCollectionError("COLLECTION_STALE", "Collection changed since it was read", status_code=409)
        # Stage every mutation on a copy.  If the audit writer fails, the
        # registry remains byte-for-byte unchanged and the caller can retry.
        candidate = copy.deepcopy(row)
        before_status = candidate["status"]
        if "name" in payload:
            candidate["name"] = _text(payload.get("name"), field="name", maximum=128, required=True)
        if "description" in payload:
            candidate["description"] = _text(payload.get("description"), field="description", maximum=1024)
        if "acl" in payload:
            candidate["acl"] = _acl(payload.get("acl"))
        if "catalog_model_refs" in payload:
            candidate["catalog_model_refs"] = _model_refs(payload.get("catalog_model_refs"))
        if "status" in payload:
            status = _text(payload.get("status"), field="status", maximum=32, required=True).casefold()
            if status not in COLLECTION_STATUSES:
                raise CatalogCollectionError("COLLECTION_STATUS_INVALID", "status is invalid")
            candidate["status"] = status
        candidate["updated_at"] = _next_timestamp(row["updated_at"])
        candidate["updated_by"] = _actor(user)
        _audit(user, "update", candidate, before_status=before_status, writer=audit_writer)
        state = _state(tenant_id)
        state[candidate["id"]] = candidate
        return _public(candidate)


def archive_custom_collection(
    user: dict[str, Any],
    collection_id: str,
    *,
    expected_updated_at: str = "",
    audit_writer: AuditWriter | None = None,
) -> dict[str, Any]:
    tenant_id = _tenant(user)
    _authorize(user, "archive", tenant_id)
    with _LOCK:
        row = _state(tenant_id).get(str(collection_id).strip())
        if not row:
            raise CatalogCollectionError("COLLECTION_NOT_FOUND", "Custom collection was not found", status_code=404)
        if row.get("collection_kind") != CUSTOM_KIND or row.get("official"):
            raise CatalogCollectionError("COLLECTION_OFFICIAL_READ_ONLY", "Official catalog collections are read-only", status_code=403)
        if expected_updated_at and expected_updated_at != row["updated_at"]:
            raise CatalogCollectionError("COLLECTION_STALE", "Collection changed since it was read", status_code=409)
        candidate = copy.deepcopy(row)
        before_status = candidate["status"]
        candidate["status"] = "archived"
        candidate["updated_at"] = _next_timestamp(row["updated_at"])
        candidate["updated_by"] = _actor(user)
        _audit(user, "archive", candidate, before_status=before_status, writer=audit_writer)
        state = _state(tenant_id)
        state[candidate["id"]] = candidate
        return _public(candidate)
