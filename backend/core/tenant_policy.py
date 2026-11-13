"""Runtime tenant policy for the single-organization Nexora deployment.

Tenant identifiers remain on stored records for compatibility and audit
history. They no longer partition an authenticated user's access in the
single-organization product mode.
"""

from __future__ import annotations

from typing import Any


DEFAULT_TENANT_ID = "tenant-default"
TENANT_ISOLATION_ENABLED = False


def tenant_scope_is_enabled() -> bool:
    """Whether tenant IDs currently act as an authorization boundary."""

    return TENANT_ISOLATION_ENABLED


def tenant_scope_for_user(user: Any = None) -> str | None:
    """Return a user's tenant query scope, or ``None`` in single-org mode."""

    if not TENANT_ISOLATION_ENABLED:
        return None
    if not isinstance(user, dict):
        return None
    tenant_id = str(user.get("tenant_id") or "").strip()
    return tenant_id or None


def tenant_id_for_write(*, requested: Any = None, user: Any = None) -> str:
    """Resolve the organization label for a new record.

    In single-organization mode, new records always use the seeded default
    organization, regardless of a request-body or user tenant value.
    """

    if not TENANT_ISOLATION_ENABLED:
        return DEFAULT_TENANT_ID
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    if isinstance(user, dict):
        tenant_id = str(user.get("tenant_id") or "").strip()
        if tenant_id:
            return tenant_id
    return DEFAULT_TENANT_ID
