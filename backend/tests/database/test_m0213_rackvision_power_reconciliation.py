from __future__ import annotations

import uuid

import database
from database.migrations import m0213_rackvision_power_reconciliation as migration
from services import rack_service


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_power_reconciliation_promotes_legacy_value_and_records_conflict(isolated_db):
    conn = database.get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("power-migration-rack"),
            site_id="site-default",
            rack_code=_id("power-migration-code"),
            power_capacity_watts=5000,
        )
        conn.execute(
            "UPDATE racks SET power_capacity_w = ?, power_capacity_watts = ? WHERE id = ?",
            (7000, 5000, rack["id"]),
        )

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        values = conn.execute(
            "SELECT power_capacity_w, power_capacity_watts FROM racks WHERE id = ?",
            (rack["id"],),
        ).fetchone()
        assert (values["power_capacity_w"], values["power_capacity_watts"]) == (5000, 5000)
        issue = conn.execute(
            """SELECT issue_code, details_json, status
                 FROM rack_data_quality_issues
                WHERE entity_type = 'rack' AND entity_id = ?
                  AND issue_code = 'POWER_FIELD_CONFLICT'""",
            (rack["id"],),
        ).fetchone()
        assert issue is not None
        assert issue["status"] == "open"
        assert "7000" in str(issue["details_json"])

        # A second run is safe and does not create a duplicate quality row.
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        assert conn.execute(
            """SELECT COUNT(*) FROM rack_data_quality_issues
                WHERE entity_type = 'rack' AND entity_id = ?
                  AND issue_code = 'POWER_FIELD_CONFLICT'""",
            (rack["id"],),
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_power_reconciliation_uses_legacy_value_when_canonical_is_zero(isolated_db):
    conn = database.get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("power-fallback-rack"),
            site_id="site-default",
            rack_code=_id("power-fallback-code"),
            power_capacity_watts=5000,
        )
        conn.execute(
            "UPDATE racks SET power_capacity_w = ?, power_capacity_watts = 0 WHERE id = ?",
            (4200, rack["id"]),
        )
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        values = conn.execute(
            "SELECT power_capacity_w, power_capacity_watts FROM racks WHERE id = ?",
            (rack["id"],),
        ).fetchone()
        assert (values["power_capacity_w"], values["power_capacity_watts"]) == (4200, 4200)
        assert conn.execute(
            """SELECT COUNT(*) FROM rack_data_quality_issues
                WHERE entity_type = 'rack' AND entity_id = ?
                  AND issue_code = 'POWER_FIELD_CONFLICT'""",
            (rack["id"],),
        ).fetchone()[0] == 0
    finally:
        conn.close()
