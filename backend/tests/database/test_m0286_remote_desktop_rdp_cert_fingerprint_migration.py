from __future__ import annotations

from database import get_db_connection
from database.migrations import build_migration_plan
from database.migrations.m0286_pam_remote_desktop_rdp_cert_fingerprint import upgrade


def test_m0286_adds_optional_rdp_certificate_fingerprint_idempotently(isolated_db):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        upgrade(cursor, use_pg=True)
        conn.commit()

        columns = conn.execute(
            """SELECT column_name, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'asset_remote_desktop_profiles'
                  AND column_name = 'rdp_cert_fingerprint'"""
        ).fetchall()
        assert len(columns) == 1
        assert columns[0]["is_nullable"] == "NO"
        assert "''" in str(columns[0]["column_default"])

        # A second startup must be safe for profiles already in production.
        upgrade(cursor, use_pg=True)
        conn.commit()
        assert 286 in build_migration_plan(conn, use_pg=True).discovered_versions
    finally:
        conn.close()
