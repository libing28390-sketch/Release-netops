from __future__ import annotations

from datetime import datetime, timezone

from database import get_db_connection
from database.migrations.m0302_asset_chassis_members import upgrade
from services.asset_chassis_serial_service import (
    get_asset_chassis_members_map,
    sync_asset_chassis_members,
)


def _add_asset_device(conn, asset_id, device_id, ip, *, serial_number="", source=""):
    now = "2026-10-30T00:00:00+00:00"
    conn.execute(
        """INSERT INTO physical_assets (
               id, asset_type, vendor, serial_number, serial_number_source,
               management_ip, created_at, updated_at
           ) VALUES (?, 'network_device', 'H3C', ?, ?, ?, ?, ?)""",
        (asset_id, serial_number, source, ip, now, now),
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, ip_address, asset_id) VALUES (?, ?, ?, ?)",
        (device_id, device_id, ip, asset_id),
    )


def _snapshot(observed_at, members, *, absent=(), failed=(), status="success"):
    return {
        "status": status,
        "members": members,
        "absent_indices": list(absent),
        "failed_indices": list(failed),
        "observed_at": observed_at,
        "discovered_indices": sorted({m["entity_index"] for m in members if isinstance(m, dict) and isinstance(m.get("entity_index"), int) and not isinstance(m.get("entity_index"), bool)} | set(failed)),
        "discovery_complete": status != "failed",
        "serial_complete": status == "success" and not failed,

    }


def _member(index, serial, *, name="", description="", model=""):
    return {
        "entity_index": index,
        "serial_number": serial,
        "entity_name": name,
        "entity_description": description,
        "model": model,
    }


def test_m0302_is_repeatable_and_adds_postgresql_schema(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(conn, "m0302-asset", "m0302-device", "192.0.2.30", serial_number="MANUAL-30")
        conn.execute("SAVEPOINT m0302_repeatable")

        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)

        column = conn.execute(
            """SELECT data_type, is_nullable, column_default
                 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'physical_assets'
                  AND column_name = 'serial_number_source'"""
        ).fetchone()
        assert column[0] == "text"
        assert column[1] == "NO"
        assert column[2] is not None and "''" in column[2]
        watermark = conn.execute(
            """SELECT data_type, is_nullable
                 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'physical_assets'
                  AND column_name = 'chassis_observed_at'"""
        ).fetchone()
        assert tuple(watermark) == ("timestamp with time zone", "YES")
        assert conn.execute(
            "SELECT serial_number, serial_number_source FROM physical_assets WHERE id = ?",
            ("m0302-asset",),
        ).fetchone()[0] == "MANUAL-30"
        assert conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = 'asset_chassis_members'"
        ).fetchone()[0] == 1

        conn.execute(
            """INSERT INTO asset_chassis_members (asset_id, entity_index, serial_number, collected_at)
               VALUES (?, 1, ?, ?)""",
            ("m0302-asset", "MIGRATION-CHASSIS-1", datetime.now(timezone.utc)),
        )
        try:
            conn.execute(
                """INSERT INTO asset_chassis_members (asset_id, entity_index, serial_number, collected_at)
                   VALUES (?, 0, ?, ?)""",
                ("m0302-asset", "INVALID-ENTITY", datetime.now(timezone.utc)),
            )
        except Exception as exc:
            assert getattr(exc, "pgcode", None) == "23514"
            conn.execute("ROLLBACK TO SAVEPOINT m0302_repeatable")
            conn.execute("RELEASE SAVEPOINT m0302_repeatable")
        else:
            raise AssertionError("nonpositive entity indexes must be rejected")

        conn.execute("DELETE FROM physical_assets WHERE id = ?", ("m0302-asset",))
        assert conn.execute(
            "SELECT COUNT(*) FROM asset_chassis_members WHERE asset_id = ?", ("m0302-asset",)
        ).fetchone()[0] == 0
        conn.commit()
    finally:
        conn.close()


def test_single_member_sync_sets_only_auto_scalar_and_projects_utc_map(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(conn, "m302-single", "m302-single-device", "192.0.2.31")
        observed = "2026-10-30T01:02:03.456789Z"

        result = sync_asset_chassis_members(
            conn,
            "m302-single",
            _snapshot(observed, [_member(1, "H3C-SERIAL-1", name="member-one", model="S6850")], absent=(2, 3)),
            device_id="m302-single-device",
            management_ip="192.0.2.31",
        )

        assert result["status"] == "synced"
        assert result["members_count"] == 1
        assert result["synced_serial_number"] == "H3C-SERIAL-1"
        assert result["serial_number_source"] == "snmp_entity_discovery"
        asset = conn.execute(
            "SELECT serial_number, serial_number_source FROM physical_assets WHERE id = ?",
            ("m302-single",),
        ).fetchone()
        assert tuple(asset) == ("H3C-SERIAL-1", "snmp_entity_discovery")
        projected = get_asset_chassis_members_map(conn, ["m302-single", "missing"])
        assert set(projected) == {"m302-single", "missing"}
        member = projected["m302-single"][0]
        assert member["entity_index"] == 1
        assert member["serial_number"] == "H3C-SERIAL-1"
        assert member["collected_at"] == "2026-10-30T01:02:03.456789Z"
        assert projected["missing"] == []
        conn.commit()
    finally:
        conn.close()


def test_manual_serial_is_protected_and_collision_does_not_abort_member_sync(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(
            conn,
            "m302-manual",
            "m302-manual-device",
            "192.0.2.32",
            serial_number="MANUAL-SERIAL",
            source="",
        )
        _add_asset_device(
            conn,
            "m302-owner",
            "m302-owner-device",
            "192.0.2.33",
            serial_number="SERIAL-IN-USE",
            source="",
        )

        manual_result = sync_asset_chassis_members(
            conn,
            "m302-manual",
            _snapshot("2026-10-30T02:00:00Z", [_member(1, "OBSERVED-SERIAL")], absent=(2, 3)),
            device_id="m302-manual-device",
            management_ip="192.0.2.32",
        )
        assert manual_result["status"] == "synced"
        assert manual_result["synced_serial_number"] == "MANUAL-SERIAL"
        assert conn.execute(
            "SELECT serial_number_source FROM physical_assets WHERE id = ?", ("m302-manual",)
        ).fetchone()[0] == ""

        _add_asset_device(conn, "m302-collision", "m302-collision-device", "192.0.2.38")
        conflict_result = sync_asset_chassis_members(
            conn,
            "m302-collision",
            _snapshot("2026-10-30T02:01:00Z", [_member(1, "serial-in-use")], absent=(2, 3)),
            device_id="m302-collision-device",
            management_ip="192.0.2.38",
        )
        assert conflict_result["status"] == "synced"
        assert conflict_result["members_count"] == 1
        assert conflict_result["synced_serial_number"] == "serial-in-use"
        assert conn.execute(
            "SELECT serial_number FROM asset_chassis_members WHERE asset_id = ? AND entity_index = 1",
            ("m302-collision",),
        ).fetchone()[0] == "serial-in-use"
        conn.commit()
    finally:
        conn.close()


def test_multi_member_requires_complete_serial_reads_before_clearing_auto_scalar(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(
            conn,
            "m302-stack",
            "m302-stack-device",
            "192.0.2.34",
            serial_number="OLD-AUTO-SERIAL",
            source="snmp_entity_fixed_get",
        )
        partial = sync_asset_chassis_members(
            conn,
            "m302-stack",
            _snapshot(
                "2026-10-30T03:00:00Z",
                [_member(1, "STACK-1"), _member(2, "STACK-2")],
                failed=(3,),
                status="partial",
            ),
            device_id="m302-stack-device",
            management_ip="192.0.2.34",
        )
        assert partial["status"] == "partial"
        assert partial["synced_serial_number"] == "OLD-AUTO-SERIAL"
        assert conn.execute(
            "SELECT serial_number FROM physical_assets WHERE id = ?", ("m302-stack",)
        ).fetchone()[0] == "OLD-AUTO-SERIAL"

        complete = sync_asset_chassis_members(
            conn,
            "m302-stack",
            _snapshot(
                "2026-10-30T03:01:00Z",
                [_member(1, "STACK-1"), _member(2, "STACK-2")],
                absent=(3,),
            ),
            device_id="m302-stack-device",
            management_ip="192.0.2.34",
        )
        assert complete["status"] == "synced"
        assert complete["synced_serial_number"] == ""
        assert complete["serial_number_source"] == ""
        assert tuple(conn.execute(
            "SELECT serial_number, serial_number_source FROM physical_assets WHERE id = ?",
            ("m302-stack",),
        ).fetchone()) == ("", "")
        conn.commit()
    finally:
        conn.close()


def test_complete_all_absent_clears_auto_scalar_and_keeps_empty_snapshot_watermark(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(
            conn,
            "m302-empty",
            "m302-empty-device",
            "192.0.2.40",
            serial_number="OLD-AUTO",
            source="snmp_entity_fixed_get",
        )
        conn.execute(
            """INSERT INTO asset_chassis_members (
                   asset_id, entity_index, serial_number, collected_at
               ) VALUES (?, 1, ?, ?)""",
            ("m302-empty", "OLD-MEMBER", datetime(2026, 10, 30, 6, 0, tzinfo=timezone.utc)),
        )

        empty = sync_asset_chassis_members(
            conn,
            "m302-empty",
            _snapshot("2026-10-30T07:00:00Z", [], absent=(1, 2, 3)),
            device_id="m302-empty-device",
            management_ip="192.0.2.40",
        )
        assert empty["status"] == "synced"
        assert empty["members_count"] == 0
        assert empty["synced_serial_number"] == ""
        asset = conn.execute(
            "SELECT serial_number, serial_number_source, chassis_observed_at FROM physical_assets WHERE id = ?",
            ("m302-empty",),
        ).fetchone()
        assert tuple(asset[:2]) == ("", "")
        assert asset[2].astimezone(timezone.utc).isoformat() == "2026-10-30T07:00:00+00:00"

        stale = sync_asset_chassis_members(
            conn,
            "m302-empty",
            _snapshot("2026-10-30T06:30:00Z", [_member(1, "OLD-MEMBER")], absent=(2, 3)),
            device_id="m302-empty-device",
            management_ip="192.0.2.40",
        )
        assert stale["status"] == "superseded"
        assert conn.execute(
            "SELECT COUNT(*) FROM asset_chassis_members WHERE asset_id = ?", ("m302-empty",)
        ).fetchone()[0] == 0
        conn.commit()
    finally:
        conn.close()


def test_partial_metadata_reuses_only_same_serial_member_values(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(conn, "m302-metadata", "m302-metadata-device", "192.0.2.41")
        first = sync_asset_chassis_members(
            conn,
            "m302-metadata",
            _snapshot(
                "2026-10-30T08:00:00Z",
                [_member(1, "MEMBER-SAME", name="old name", description="old description", model="old model")],
                absent=(2, 3),
            ),
            device_id="m302-metadata-device",
            management_ip="192.0.2.41",
        )
        assert first["status"] == "synced"

        same_serial_partial = sync_asset_chassis_members(
            conn,
            "m302-metadata",
            _snapshot(
                "2026-10-30T08:01:00Z",
                [_member(1, "member-same")],
                absent=(2,),
                failed=(3,),
                status="partial",
            ),
            device_id="m302-metadata-device",
            management_ip="192.0.2.41",
        )
        assert same_serial_partial["status"] == "partial"
        saved = conn.execute(
            """SELECT serial_number, entity_name, entity_description, model
                 FROM asset_chassis_members WHERE asset_id = ? AND entity_index = 1""",
            ("m302-metadata",),
        ).fetchone()
        assert tuple(saved) == ("member-same", "old name", "old description", "old model")

        new_serial_partial = sync_asset_chassis_members(
            conn,
            "m302-metadata",
            _snapshot(
                "2026-10-30T08:02:00Z",
                [_member(1, "MEMBER-NEW")],
                absent=(2,),
                failed=(3,),
                status="partial",
            ),
            device_id="m302-metadata-device",
            management_ip="192.0.2.41",
        )
        assert new_serial_partial["status"] == "partial"
        saved_new = conn.execute(
            """SELECT serial_number, entity_name, entity_description, model
                 FROM asset_chassis_members WHERE asset_id = ? AND entity_index = 1""",
            ("m302-metadata",),
        ).fetchone()
        assert tuple(saved_new) == ("MEMBER-NEW", "", "", "")
        conn.commit()
    finally:
        conn.close()


def test_failed_indexes_preserve_old_members_and_newer_snapshot_supersedes(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(conn, "m302-fresh", "m302-fresh-device", "192.0.2.35")
        initial = sync_asset_chassis_members(
            conn,
            "m302-fresh",
            _snapshot("2026-10-30T04:00:00Z", [_member(1, "OLD-1"), _member(2, "OLD-2")], absent=(3,)),
            device_id="m302-fresh-device",
            management_ip="192.0.2.35",
        )
        assert initial["members_count"] == 2

        partial = sync_asset_chassis_members(
            conn,
            "m302-fresh",
            _snapshot(
                "2026-10-30T04:01:00Z",
                [_member(1, "NEW-1")],
                absent=(2,),
                failed=(3,),
                status="partial",
            ),
            device_id="m302-fresh-device",
            management_ip="192.0.2.35",
        )
        assert partial["status"] == "partial"
        assert partial["members_count"] == 2
        rows = conn.execute(
            "SELECT entity_index, serial_number FROM asset_chassis_members WHERE asset_id = ? ORDER BY entity_index",
            ("m302-fresh",),
        ).fetchall()
        assert [tuple(row) for row in rows] == [(1, "NEW-1"), (2, "OLD-2")]

        stale = sync_asset_chassis_members(
            conn,
            "m302-fresh",
            _snapshot("2026-10-30T04:00:30Z", [_member(1, "STALE-1")], absent=(2, 3)),
            device_id="m302-fresh-device",
            management_ip="192.0.2.35",
        )
        assert stale["status"] == "superseded"
        assert conn.execute(
            "SELECT serial_number FROM asset_chassis_members WHERE asset_id = ? AND entity_index = 1",
            ("m302-fresh",),
        ).fetchone()[0] == "NEW-1"
        conn.commit()
    finally:
        conn.close()


def test_stale_device_ip_or_missing_identity_is_superseded_without_writes(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(conn, "m302-ip", "m302-ip-device", "192.0.2.36")
        snapshot = _snapshot("2026-10-30T05:00:00Z", [_member(1, "NO-WRITE")], absent=(2, 3))

        changed_ip = sync_asset_chassis_members(
            conn,
            "m302-ip",
            snapshot,
            device_id="m302-ip-device",
            management_ip="192.0.2.99",
        )
        missing_asset = sync_asset_chassis_members(
            conn,
            "missing-asset",
            snapshot,
            device_id="m302-ip-device",
            management_ip="192.0.2.36",
        )
        missing_device = sync_asset_chassis_members(
            conn,
            "m302-ip",
            snapshot,
            device_id="missing-device",
            management_ip="192.0.2.36",
        )

        assert changed_ip["status"] == "superseded"
        assert missing_asset["status"] == "superseded"
        assert missing_device["status"] == "superseded"
        assert conn.execute(
            "SELECT COUNT(*) FROM asset_chassis_members WHERE asset_id = ?", ("m302-ip",)
        ).fetchone()[0] == 0
        conn.commit()
    finally:
        conn.close()


def test_identity_switches_h3c_gate_and_collection_flag_prevent_writes(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(conn, "m302-guard", "m302-guard-device", "192.0.2.39")
        snapshot = _snapshot("2026-10-30T05:30:00Z", [_member(1, "GUARDED")], absent=(2, 3))

        conn.execute("UPDATE devices SET vendor = 'Huawei' WHERE id = ?", ("m302-guard-device",))
        vendor_conflict = sync_asset_chassis_members(
            conn,
            "m302-guard",
            snapshot,
            device_id="m302-guard-device",
            management_ip="192.0.2.39",
        )
        assert vendor_conflict["status"] == "superseded"

        conn.execute(
            "UPDATE physical_assets SET vendor = '' WHERE id = ?",
            ("m302-guard",),
        )
        conn.execute(
            "UPDATE devices SET vendor = 'H3C', snmp_collection_enabled = FALSE WHERE id = ?",
            ("m302-guard-device",),
        )
        disabled = sync_asset_chassis_members(
            conn,
            "m302-guard",
            snapshot,
            device_id="m302-guard-device",
            management_ip="192.0.2.39",
        )
        assert disabled["status"] == "superseded"

        conn.execute(
            "UPDATE devices SET snmp_collection_enabled = TRUE WHERE id = ?",
            ("m302-guard-device",),
        )
        device_only_h3c = sync_asset_chassis_members(
            conn,
            "m302-guard",
            snapshot,
            device_id="m302-guard-device",
            management_ip="192.0.2.39",
        )
        assert device_only_h3c["status"] == "synced"
        conn.commit()
    finally:
        conn.close()


def test_nul_and_invalid_member_text_never_reach_postgresql(isolated_db):
    conn = get_db_connection()
    try:
        _add_asset_device(conn, "m302-invalid", "m302-invalid-device", "192.0.2.37")
        result = sync_asset_chassis_members(
            conn,
            "m302-invalid",
            _snapshot(
                "2026-10-30T06:00:00Z",
                [_member(1, "BAD\x00SERIAL"), _member(2, "VALID-2", name="bad\ud800name")],
                absent=(3,),
                status="partial",
            ),
            device_id="m302-invalid-device",
            management_ip="192.0.2.37",
        )

        assert result["status"] == "partial"
        rows = conn.execute(
            "SELECT entity_index, serial_number, entity_name FROM asset_chassis_members WHERE asset_id = ? ORDER BY entity_index",
            ("m302-invalid",),
        ).fetchall()
        assert [tuple(row) for row in rows] == [(2, "VALID-2", "")]
        conn.commit()
    finally:
        conn.close()
