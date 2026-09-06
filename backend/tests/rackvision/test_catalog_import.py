from __future__ import annotations

import json

from services import rack_catalog_import_service, rack_service


def _catalog_row(model: str = "RV-IMPORT-1", *, width_mm: int | None = None) -> dict:
    return {
        "catalog_key": f"test__{model.casefold()}",
        "vendor": "test-vendor",
        "family": "Test Family",
        "exact_model": model,
        "device_type": "switch",
        "height_u": 1,
        "width_mm": width_mm,
        "depth_mm": None,
        "height_mm": None,
        "dimension_status": "pending_verification",
        "data_confidence": "tbd",
        "notes": "catalog test row",
        "source_row": 4,
        "source_title": "test",
        "source_url": "https://example.invalid/catalog",
        "source_version": "test",
    }


def test_catalog_import_is_dry_run_by_default_and_applies_additively(isolated_db, tmp_path):
    source = tmp_path / "network_devices.json"
    source.write_text(json.dumps([_catalog_row()]), encoding="utf-8")
    conn = isolated_db["module"].get_db_connection()
    try:
        preview = rack_catalog_import_service.import_device_catalog(conn, source)
        assert preview["dry_run"] is True
        assert preview["summary"]["new"] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM device_types WHERE vendor = ? AND model = ?",
            ("test-vendor", "RV-IMPORT-1"),
        ).fetchone()[0] == 0

        applied = rack_catalog_import_service.import_device_catalog(
            conn,
            source,
            apply=True,
            commit=True,
        )
        assert applied["applied"] is True
        row = conn.execute(
            "SELECT vendor, model, u_height, depth_class, dimension_status, catalog_key "
            "FROM device_types WHERE vendor = ? AND model = ?",
            ("test-vendor", "RV-IMPORT-1"),
        ).fetchone()
        assert row["vendor"] == "test-vendor"
        assert row["u_height"] == 1
        assert row["depth_class"] == "unknown"
        assert row["dimension_status"] == "pending_verification"
        assert row["catalog_key"] == "test__rv-import-1"

        second = rack_catalog_import_service.import_device_catalog(conn, source)
        assert second["summary"]["new"] == 0
        assert second["summary"]["unchanged"] == 1
    finally:
        conn.close()


def test_catalog_import_preserves_operator_dimensions_and_blocks_conflicts(isolated_db, tmp_path):
    conn = isolated_db["module"].get_db_connection()
    try:
        existing = rack_service.create_device_type(
            conn,
            model="RV-IMPORT-2",
            vendor="test-vendor",
            u_height=1,
            width_mm=900,
            dimension_status="confirmed",
            catalog_key="",
        )
        source = tmp_path / "network_devices.json"
        source.write_text(json.dumps([_catalog_row("RV-IMPORT-2", width_mm=600)]), encoding="utf-8")
        report = rack_catalog_import_service.import_device_catalog(
            conn,
            source,
            apply=True,
            commit=True,
        )
        assert report["applied"] is False
        assert report["apply_blocked"] is True
        assert report["summary"]["conflicts"] == 1
        row = conn.execute(
            "SELECT width_mm, dimension_status, catalog_key FROM device_types WHERE id = ?",
            (existing["id"],),
        ).fetchone()
        assert row["width_mm"] == 900
        assert row["dimension_status"] == "confirmed"
        assert row["catalog_key"] == ""
    finally:
        conn.close()

