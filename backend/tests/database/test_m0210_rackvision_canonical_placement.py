from __future__ import annotations

import database
from database.migrations import m0210_rackvision_canonical_placement as migration


def _columns(conn, table_name: str) -> set[str]:
    rows = conn.execute(
        """SELECT column_name
             FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = ?""",
        (table_name,),
    ).fetchall()
    return {str(row[0]) for row in rows}


def test_rackvision_schema_is_additive_and_idempotent(isolated_db):
    conn = database.get_db_connection()
    try:
        assert {
            "mount_policy",
            "layout_revision",
        }.issubset(_columns(conn, "racks"))
        assert {
            "depth_class",
            "dimension_status",
            "default_mount_kind",
            "model_family",
            "catalog_key",
        }.issubset(_columns(conn, "device_types"))
        assert {
            "mount_kind",
            "height_u",
            "placement_status",
            "placement_source",
            "dimension_status",
            "location_note",
            "model_key",
        }.issubset(_columns(conn, "rack_devices"))
        assert {
            "rack_id",
            "rack_position",
            "rack_mount_kind",
            "rack_location_status",
        }.issubset(_columns(conn, "physical_assets"))
        assert _columns(conn, "rack_data_quality_issues") >= {
            "entity_type",
            "entity_id",
            "issue_code",
            "severity",
            "details_json",
            "status",
        }

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        index_names = {
            str(row[0])
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
            ).fetchall()
        }
        assert "uq_rack_devices_nonempty_asset" in index_names
    finally:
        conn.close()

