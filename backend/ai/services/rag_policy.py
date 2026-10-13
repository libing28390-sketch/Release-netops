"""Tenant, role and source-trust rules for the local AI knowledge base."""

from __future__ import annotations

import json
from typing import Any, Iterable


TRUST_RANK = {
    "official": 4,
    "internal": 3,
    "reviewed": 3,
    "operator": 2,
    "user_document": 2,
    "external": 1,
    "untrusted": 0,
}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def parse_acl(value: Any) -> dict[str, list[str]]:
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except (TypeError, ValueError):
            value = {}
    if not isinstance(value, dict):
        return {}
    return {str(key): _as_list(item) for key, item in value.items()}


def document_is_visible(
    document: dict[str, Any],
    *,
    tenant_id: str = "tenant-default",
    user_id: str | None = None,
    roles: Iterable[str] | None = None,
    site_ids: Iterable[str] | None = None,
) -> bool:
    """Apply tenant and optional document ACL checks before retrieval.

    Empty ACL means the document is visible only to its owning tenant.  The
    default tenant is deliberately not treated as a wildcard for other
    tenants, which prevents a legacy document from becoming cross-tenant.
    """
    tenant = str(tenant_id or "tenant-default")
    owner = str(document.get("tenant_id") or "tenant-default")
    if owner not in {tenant, "*"}:
        return False
    acl = parse_acl(document.get("acl_json") or document.get("acl"))
    if not acl:
        return True
    user_values = {str(user_id or "")}
    role_values = {str(item) for item in (roles or [])}
    site_values = {str(item) for item in (site_ids or [])}
    allowed_users = set(acl.get("users", [])) | set(acl.get("user_ids", []))
    allowed_roles = set(acl.get("roles", []))
    allowed_sites = set(acl.get("sites", [])) | set(acl.get("site_ids", []))
    if allowed_users and user_values & allowed_users:
        return True
    if allowed_roles and role_values & allowed_roles:
        return True
    if allowed_sites and site_values & allowed_sites:
        return True
    # An explicitly empty dimension is not a grant.  ACLs with no supported
    # dimensions fail closed rather than accidentally becoming public.
    return False


def trust_rank(value: Any) -> int:
    return TRUST_RANK.get(str(value or "untrusted").lower(), 0)
