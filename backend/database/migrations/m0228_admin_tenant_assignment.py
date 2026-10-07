"""Repair tenant assignment for the bootstrap default administrator."""

from __future__ import annotations


VERSION = 228
NAME = "admin_tenant_assignment"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("admin_tenant_assignment requires PostgreSQL")

    # Do not broaden this repair to arbitrary tenantless accounts: assigning
    # those users to the default tenant is an authorization decision. The
    # bootstrap administrator is system-owned and must have a tenant.
    cursor.execute(
        """
        UPDATE users
           SET tenant_id = COALESCE(NULLIF(BTRIM(tenant_id), ''), 'tenant-default'),
               role_id = COALESCE(NULLIF(BTRIM(role_id), ''), 'role-admin')
         WHERE username = 'admin'
           AND (
               tenant_id IS NULL OR BTRIM(tenant_id) = ''
               OR role_id IS NULL OR BTRIM(role_id) = ''
           )
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the ownership repair in place when rolling application code back.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
