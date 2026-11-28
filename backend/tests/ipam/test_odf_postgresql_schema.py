"""Verify the retained production PostgreSQL ODF schema path."""
from database import get_db_connection
from services import odf_service


def test_odf_schema_postgresql_idempotent(isolated_db, monkeypatch):
    monkeypatch.setattr(odf_service, "_ODF_SCHEMA_READY", False)
    with get_db_connection() as conn:
        odf_service.ensure_odf_tables(conn, force=True)
        odf_service.ensure_odf_tables(conn, force=True)
        for table in ("odf_frames", "odf_trays", "odf_ports"):
            assert conn.execute("SELECT to_regclass(?)", (table,)).fetchone()[0] == table
        conn.execute(
            "INSERT INTO sites(id, site_code, site_name) VALUES ('odf-pg-test-site', 'ODF-PG', 'ODF PG Test')"
        )
        conn.execute(
            """INSERT INTO odf_frames(id, site_id, frame_code, name)
               VALUES ('odf-pg-test-frame', 'odf-pg-test-site', 'ODF-PG-01', 'Test frame')"""
        )
        conn.commit()
        odf_service.ensure_odf_tables(conn, force=True)
        assert conn.execute(
            "SELECT total_cores FROM odf_frames WHERE id='odf-pg-test-frame'"
        ).fetchone()[0] == 576
        conn.execute("DELETE FROM sites WHERE id='odf-pg-test-site'")
        conn.commit()
        assert conn.execute(
            "SELECT COUNT(*) FROM odf_frames WHERE id='odf-pg-test-frame'"
        ).fetchone()[0] == 0
