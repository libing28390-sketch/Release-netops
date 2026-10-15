from __future__ import annotations

import json


def test_single_organization_ignores_tenant_for_access_and_new_records():
    from core.rbac import authorize_resource
    from core.tenant_policy import tenant_id_for_write, tenant_scope_for_user

    user = {"role": "Viewer", "tenant_id": "tenant-a"}

    assert tenant_scope_for_user(user) is None
    assert tenant_id_for_write(requested="tenant-b", user=user) == "tenant-default"
    assert authorize_resource(user, "asset", "view", tenant_id="tenant-b")


def test_single_organization_keeps_site_scope_across_tenant_ids(isolated_db, make_user):
    from core.rbac import authorize_resource

    user = make_user("single-org-site-scope", role="Viewer", tenant_id="tenant-default")
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO user_resource_scopes
               (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'asset', 'site', 'site-a', ?, '2026-10-15T00:00:00Z')""",
            ("single-org-site-scope-row", user["user_id"], json.dumps(["view"])),
        )
        conn.execute(
            "UPDATE users SET scope_mode = 'restricted' WHERE id = ?",
            (user["user_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    subject = {
        "id": user["user_id"],
        "role": "Viewer",
        "tenant_id": "tenant-default",
        "scope_mode": "restricted",
    }
    assert authorize_resource(subject, "asset", "view", tenant_id="legacy-tenant", site_id="site-a")
    assert not authorize_resource(subject, "asset", "view", tenant_id="legacy-tenant", site_id="site-b")


def test_single_organization_tenant_scope_grants_apply_org_wide(isolated_db, make_user):
    from core.rbac import authorize_resource

    user = make_user("single-org-tenant-scope", role="Viewer", tenant_id="tenant-default")
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO user_resource_scopes
               (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'asset', 'tenant', 'legacy-tenant-a', ?, '2026-10-15T00:00:00Z')""",
            ("single-org-tenant-scope-row", user["user_id"], json.dumps(["view"])),
        )
        conn.execute(
            "UPDATE users SET scope_mode = 'restricted' WHERE id = ?",
            (user["user_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    subject = {
        "id": user["user_id"],
        "role": "Viewer",
        "tenant_id": "tenant-default",
        "scope_mode": "restricted",
    }
    assert authorize_resource(subject, "asset", "view", tenant_id="different-legacy-tenant")
