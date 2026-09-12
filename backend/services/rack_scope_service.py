"""Tenant/site scope helpers for RackVision reads and mutations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.rbac import enforce_resource_scope, resource_action_allowed
from fastapi import HTTPException


@dataclass(frozen=True)
class RackScope:
    """A SQL-friendly projection of the caller's rack visibility."""

    tenant_id: str | None = None
    site_ids: tuple[str, ...] | None = None

    @property
    def cache_key(self) -> str:
        tenant = self.tenant_id or "*"
        sites = "*" if self.site_ids is None else ",".join(self.site_ids)
        return f"tenant={tenant};sites={sites}"


def _row_value(row: Any, key: str, default: Any = "") -> Any:
    if row is None:
        return default
    if hasattr(row, "keys"):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return default
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def _normalized_actions(raw: Any) -> set[str]:
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()
    if not isinstance(values, list):
        return set()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _action_matches(actions: set[str], action: str) -> bool:
    normalized = str(action or "view").strip().lower()
    if "*" in actions or normalized in actions:
        return True
    # Existing scope rows use both vocabulary variants for read-only access.
    if normalized == "view":
        return "read" in actions
    if normalized == "read":
        return "view" in actions
    return False


def allowed_resource_scope(
    conn,
    user: dict,
    resource_type: str,
    action: str = "view",
) -> RackScope:
    """Return the caller's effective tenant/site filter for one resource.

    A user without explicit RackVision scope rows keeps the legacy role
    behavior but is still restricted to the session tenant when one exists.
    Once rack scope rows exist, they narrow access to global, tenant, or site
    grants.  Administrators retain the existing global behavior.
    """

    if not resource_action_allowed(user, resource_type, action):
        return RackScope(tenant_id=str(user.get("tenant_id") or "").strip() or None, site_ids=())

    if user.get("role") == "Administrator":
        return RackScope()

    tenant_id = str(user.get("tenant_id") or "").strip() or None
    user_id = str(user.get("id") or user.get("user_id") or "").strip()
    if not user_id:
        return RackScope(tenant_id=tenant_id)

    rows = conn.execute(
        """SELECT scope_type, scope_id, actions_json
             FROM user_resource_scopes
            WHERE user_id = ? AND resource_type IN (?, '*')""",
        (user_id, resource_type),
    ).fetchall()
    if not rows:
        return RackScope(tenant_id=tenant_id)

    global_allowed = False
    tenant_allowed = False
    site_ids: set[str] = set()
    for row in rows:
        actions = _normalized_actions(_row_value(row, "actions_json", "[]"))
        if not _action_matches(actions, action):
            continue
        scope_type = str(_row_value(row, "scope_type", "") or "").strip().lower()
        scope_id = str(_row_value(row, "scope_id", "") or "").strip()
        if scope_type == "global":
            global_allowed = True
        elif scope_type == "tenant" and tenant_id and scope_id == tenant_id:
            tenant_allowed = True
        elif scope_type == "site" and scope_id:
            site_ids.add(scope_id)

    if global_allowed or tenant_allowed:
        return RackScope(tenant_id=tenant_id)
    if site_ids:
        return RackScope(tenant_id=tenant_id, site_ids=tuple(sorted(site_ids)))
    return RackScope(tenant_id=tenant_id, site_ids=())


def allowed_rack_scope(conn, user: dict, action: str = "view") -> RackScope:
    """Return the caller's effective RackVision rack filter."""

    return allowed_resource_scope(conn, user, "rack", action)


def enforce_loaded_resource(
    user: dict,
    resource: dict,
    resource_type: str,
    action: str = "view",
) -> dict:
    """Enforce scope on a row already loaded by the service."""

    tenant_id = str(resource.get("site_tenant_id") or resource.get("tenant_id") or "").strip() or None
    site_id = str(resource.get("site_id") or "").strip() or None
    enforce_resource_scope(
        user,
        resource_type,
        action,
        tenant_id=tenant_id,
        site_id=site_id,
    )
    return resource


def enforce_loaded_rack(user: dict, rack: dict, action: str = "view") -> dict:
    """Enforce scope on a rack row already loaded by the service."""

    return enforce_loaded_resource(user, rack, "rack", action)


def enforce_site(
    conn,
    user: dict,
    site_id: str,
    action: str = "create",
    resource_type: str = "rack",
) -> None:
    """Enforce a resource action against a target site before writing."""

    row = conn.execute(
        "SELECT id, tenant_id FROM sites WHERE id = ? OR site_code = ? OR site_name = ? LIMIT 1",
        (site_id, site_id, site_id),
    ).fetchone()
    if not row:
        return
    enforce_resource_scope(
        user,
        resource_type,
        action,
        tenant_id=str(_row_value(row, "tenant_id", "") or "").strip() or None,
        site_id=str(_row_value(row, "id", "") or "").strip() or None,
    )


def resolve_site_id(conn, site_id: str = "", legacy_label: str = "") -> str:
    """Resolve a request's site label for pre-write scope checks."""

    requested = str(site_id or legacy_label or "").strip()
    if not requested:
        return ""
    row = conn.execute(
        "SELECT id FROM sites WHERE id = ? OR site_code = ? OR site_name = ? LIMIT 1",
        (requested, requested, requested),
    ).fetchone()
    return str(_row_value(row, "id", "") or "").strip() if row else ""


def raise_not_found(rack_id: str) -> None:
    raise HTTPException(
        status_code=404,
        detail={"code": "RACK_NOT_FOUND", "message": f"Rack not found: {rack_id}"},
    )
