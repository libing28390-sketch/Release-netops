"""Tenant/site scope helpers for RackVision reads and mutations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.rbac import enforce_resource_scope, resource_action_allowed
from core.tenant_policy import TENANT_ISOLATION_ENABLED, tenant_scope_for_user
from fastapi import HTTPException


@dataclass(frozen=True)
class RackScope:
    """A SQL-friendly projection of the caller's rack visibility."""

    tenant_id: str | None = None
    site_ids: tuple[str, ...] | None = None
    device_group_ids: tuple[str, ...] | None = None

    @property
    def cache_key(self) -> str:
        return json.dumps(
            {
                "tenant": self.tenant_id,
                "sites": self.site_ids,
                "device_groups": self.device_group_ids,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


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
        return RackScope(
            tenant_id=tenant_scope_for_user(user),
            site_ids=(),
            device_group_ids=(),
        )

    if user.get("role") == "Administrator":
        return RackScope()

    tenant_id = tenant_scope_for_user(user)
    user_id = str(user.get("id") or user.get("user_id") or "").strip()
    if not user_id:
        if str(user.get("scope_mode") or "legacy") == "restricted":
            return RackScope(tenant_id=tenant_id, site_ids=(), device_group_ids=())
        return RackScope(tenant_id=tenant_id)

    rows = conn.execute(
        """SELECT scope_type, scope_id, actions_json
             FROM user_resource_scopes
            WHERE user_id = ? AND resource_type IN (?, '*')""",
        (user_id, resource_type),
    ).fetchall()
    if not rows:
        if str(user.get("scope_mode") or "legacy") == "restricted":
            return RackScope(tenant_id=tenant_id, site_ids=(), device_group_ids=())
        return RackScope(tenant_id=tenant_id)

    global_allowed = False
    tenant_allowed = False
    site_ids: set[str] = set()
    device_group_ids: set[str] = set()
    for row in rows:
        actions = _normalized_actions(_row_value(row, "actions_json", "[]"))
        if not _action_matches(actions, action):
            continue
        scope_type = str(_row_value(row, "scope_type", "") or "").strip().lower()
        scope_id = str(_row_value(row, "scope_id", "") or "").strip()
        if scope_type == "global":
            global_allowed = True
        elif scope_type == "tenant":
            if not TENANT_ISOLATION_ENABLED and scope_id:
                tenant_allowed = True
            elif tenant_id and scope_id == tenant_id:
                tenant_allowed = True
        elif scope_type == "site" and scope_id:
            site_ids.add(scope_id)
        elif scope_type == "device_group" and scope_id:
            device_group_ids.add(scope_id)

    if global_allowed or tenant_allowed:
        return RackScope(tenant_id=tenant_id)
    if site_ids or device_group_ids:
        return RackScope(
            tenant_id=tenant_id,
            site_ids=tuple(sorted(site_ids)),
            device_group_ids=tuple(sorted(device_group_ids)),
        )
    return RackScope(tenant_id=tenant_id, site_ids=(), device_group_ids=())


def device_scope_predicate(
    scope: RackScope,
    *,
    device_alias: str = "d",
) -> tuple[str, tuple[Any, ...]]:
    """Return a fail-closed SQL predicate for site and device-group scope.

    Site grants match the normalized device site. Group grants use the
    authoritative ``devices.device_group_id`` relationship. When both kinds
    are present, either grant makes a device visible.
    """

    if scope.site_ids is None and scope.device_group_ids is None:
        return "", ()

    predicates: list[str] = []
    params: list[Any] = []
    if scope.site_ids:
        site_placeholders = ",".join("?" for _ in scope.site_ids)
        predicates.append(
            "(NULLIF({alias}.site_id, '') IN ({sites}) "
            "OR NULLIF({alias}.site, '') IN ({sites}))".format(
                alias=device_alias,
                sites=site_placeholders,
            )
        )
        params.extend(scope.site_ids)
        params.extend(scope.site_ids)
    if scope.device_group_ids:
        group_placeholders = ",".join("?" for _ in scope.device_group_ids)
        predicates.append(
            f"{device_alias}.device_group_id IN ({group_placeholders})"
        )
        params.extend(scope.device_group_ids)
    if not predicates:
        return "1 = 0", ()
    return f"({' OR '.join(predicates)})", tuple(params)


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
    device_group_id = str(resource.get("device_group_id") or "").strip() or None
    try:
        enforce_resource_scope(
            user,
            resource_type,
            action,
            tenant_id=tenant_id,
            site_id=site_id,
            device_group_id=device_group_id,
        )
    except HTTPException as initial_error:
        if resource_type != "asset" or device_group_id:
            raise

        device_id = str(resource.get("device_id") or "").strip()
        asset_id = str(resource.get("asset_id") or resource.get("id") or "").strip()
        identity_clauses: list[str] = []
        identity_params: list[str] = []
        if device_id:
            identity_clauses.append("id = ?")
            identity_params.append(device_id)
        if asset_id:
            identity_clauses.append("asset_id = ?")
            identity_params.append(asset_id)
            # Some installations use the CMDB asset ID as the device ID.
            identity_clauses.append("id = ?")
            identity_params.append(asset_id)
        if not identity_clauses:
            raise initial_error
        try:
            from database import get_db_connection

            conn = get_db_connection()
            try:
                rows = conn.execute(
                    "SELECT DISTINCT device_group_id FROM devices WHERE ("
                    + " OR ".join(identity_clauses)
                    + ") AND device_group_id IS NOT NULL AND device_group_id <> ''",
                    tuple(identity_params),
                ).fetchall()
            finally:
                conn.close()
        except Exception:
            raise initial_error
        for row in rows:
            group_id = str(_row_value(row, "device_group_id", "") or "").strip()
            if not group_id:
                continue
            try:
                enforce_resource_scope(
                    user,
                    resource_type,
                    action,
                    tenant_id=tenant_id,
                    site_id=site_id,
                    device_group_id=group_id,
                )
                break
            except HTTPException as group_error:
                if group_error.status_code != 403:
                    raise
        else:
            raise initial_error
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
