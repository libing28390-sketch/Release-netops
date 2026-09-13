from __future__ import annotations

from database import get_db_connection
from database.migrations import m0228_admin_tenant_assignment as migration


def test_m0228_backfills_only_unassigned_default_admin_and_is_idempotent(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET tenant_id = '', role_id = '' WHERE username = 'admin'"
        )
        conn.execute(
            """INSERT INTO users (id, username, password, role, status, created_at, tenant_id)
               VALUES ('m0228-unassigned-user', 'm0228-unassigned-user', 'hash',
                       'Operator', 'active', '2026-09-13', '')"""
        )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        admin = conn.execute(
            "SELECT tenant_id, role_id FROM users WHERE username = 'admin'"
        ).fetchone()
        other_user = conn.execute(
            "SELECT tenant_id, role_id FROM users WHERE username = 'm0228-unassigned-user'"
        ).fetchone()
        assert dict(admin) == {
            "tenant_id": "tenant-default",
            "role_id": "role-admin",
        }
        assert dict(other_user) == {"tenant_id": "", "role_id": ""}
    finally:
        conn.close()


def test_m0228_preserves_an_explicit_default_admin_scope(isolated_db):
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE users SET tenant_id = ?, role_id = ? WHERE username = 'admin'",
            ("tenant-custom", "role-custom"),
        )
        conn.commit()

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        admin = conn.execute(
            "SELECT tenant_id, role_id FROM users WHERE username = 'admin'"
        ).fetchone()
        assert dict(admin) == {"tenant_id": "tenant-custom", "role_id": "role-custom"}
    finally:
        conn.close()
