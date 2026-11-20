from __future__ import annotations

from database import get_db_connection
from database.migrations.m0285_pam_remote_desktop import upgrade


def test_m0285_creates_postgresql_profiles_and_session_leases_idempotently(isolated_db):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        columns = conn.execute(
            """SELECT column_name FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'asset_remote_desktop_profiles'"""
        ).fetchall()
        column_names = {row["column_name"] for row in columns}
        assert {
            "asset_id",
            "protocol",
            "port",
            "normal_credential_id",
            "admin_credential_id",
            "rdp_security_mode",
        } <= column_names

        # Reapplying the deployed migration must tolerate existing tables,
        # columns, and indexes without altering tenant data.
        upgrade(cursor, use_pg=True)
        conn.commit()
        remote_columns = conn.execute(
            """SELECT column_name FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = 'pam_sessions'
                   AND column_name LIKE 'remote_desktop_%'"""
        ).fetchall()
        assert "remote_desktop_ticket_hash" in {row["column_name"] for row in remote_columns}
    finally:
        conn.close()
