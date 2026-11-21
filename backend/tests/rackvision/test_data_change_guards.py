"""Regression tests for destructive rack/template edits."""

from __future__ import annotations

import uuid

import pytest

from services import rack_placement_service, rack_service


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def test_rack_resize_cannot_hide_existing_u_placement(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("resize-rack"),
            site_id="site-default",
            total_u=10,
            rack_code=_id("resize-code"),
        )
        device_type = rack_service.create_device_type(
            conn,
            model=_id("resize-switch"),
            vendor="RackVision",
            u_height=2,
        )
        rack_service.create_rack_device(
            conn,
            name="near-top-device",
            rack_id=rack["id"],
            device_type_id=device_type["id"],
            start_u=8,
        )

        with pytest.raises(rack_placement_service.RackPlacementError) as caught:
            rack_service.update_rack(conn, rack["id"], total_u=7)

        assert caught.value.code == "RACK_RESIZE_CONFLICT"
        assert caught.value.status_code == 409
        assert conn.execute("SELECT total_u FROM racks WHERE id = ?", (rack["id"],)).fetchone()[0] == 10
    finally:
        conn.close()


def test_device_type_height_change_cannot_break_inherited_placement(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("template-rack"),
            site_id="site-default",
            total_u=10,
            rack_code=_id("template-code"),
        )
        device_type = rack_service.create_device_type(
            conn,
            model=_id("template-switch"),
            vendor="RackVision",
            u_height=2,
        )
        placement = rack_service.create_rack_device(
            conn,
            name="inherited-height-device",
            rack_id=rack["id"],
            device_type_id=device_type["id"],
            start_u=8,
        )
        assert placement["placement_status"] == "estimated"

        with pytest.raises(rack_placement_service.RackPlacementError) as caught:
            rack_service.update_device_type(conn, device_type["id"], u_height=4)

        assert caught.value.code == "DEVICE_TYPE_UPDATE_CONFLICT"
        assert caught.value.status_code == 409
        assert conn.execute("SELECT u_height FROM device_types WHERE id = ?", (device_type["id"],)).fetchone()[0] == 2
    finally:
        conn.close()


def test_rack_power_capacity_columns_are_reconciled(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("power-rack"),
            site_id="site-default",
            rack_code=_id("power-code"),
            power_capacity_watts=3000,
            power_capacity_w=3000,
        )
        assert rack["power_capacity_watts"] == 3000
        assert rack["power_capacity_w"] == 3000

        with pytest.raises(rack_placement_service.RackPlacementError) as caught:
            rack_service.update_rack(
                conn,
                rack["id"],
                power_capacity_watts=4000,
                power_capacity_w=3000,
            )
        assert caught.value.code == "POWER_FIELD_CONFLICT"
        assert caught.value.status_code == 422

        updated = rack_service.update_rack(conn, rack["id"], power_capacity_watts=4000)
        assert updated["power_capacity_watts"] == 4000
        assert updated["power_capacity_w"] == 4000
    finally:
        conn.close()


def test_placement_error_taxonomy_covers_full_depth_and_zero_u(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("error-rack"),
            site_id="site-default",
            total_u=20,
            rack_code=_id("error-code"),
        )
        device_type = rack_service.create_device_type(
            conn,
            model=_id("error-device"),
            vendor="RackVision",
            u_height=2,
        )
        rack_service.create_rack_device(
            conn,
            name="front-device",
            rack_id=rack["id"],
            device_type_id=device_type["id"],
            start_u=5,
            position="front",
        )

        full_depth_result = rack_placement_service.validate(
            conn,
            rack_id=rack["id"],
            device_type_id=device_type["id"],
            start_u=5,
            position="full_depth",
            mount_kind="u_mount",
        )
        with pytest.raises(rack_placement_service.RackPlacementError) as full_depth_error:
            rack_placement_service.raise_validation_failure(full_depth_result)
        assert full_depth_error.value.code == "FULL_DEPTH_CONFLICT"
        assert full_depth_error.value.status_code == 409

        with pytest.raises(rack_placement_service.RackPlacementError) as zero_u_error:
            rack_service.create_rack_device(
                conn,
                name="unlocated-zero-u",
                rack_id=rack["id"],
                device_type_id=device_type["id"],
                start_u=None,
                position="unknown",
                mount_kind="zero_u",
            )
        assert zero_u_error.value.code == "ZERO_U_POSITION_REQUIRED"
        assert zero_u_error.value.status_code == 422
    finally:
        conn.close()


def test_device_type_delete_returns_stable_in_use_error(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("in-use-rack"),
            site_id="site-default",
            rack_code=_id("in-use-code"),
        )
        device_type = rack_service.create_device_type(
            conn,
            model=_id("in-use-device"),
            vendor="RackVision",
            u_height=1,
        )
        rack_service.create_rack_device(
            conn,
            name="in-use-placement",
            rack_id=rack["id"],
            device_type_id=device_type["id"],
            start_u=1,
        )

        with pytest.raises(rack_placement_service.RackPlacementError) as caught:
            rack_service.delete_device_type(conn, device_type["id"])
        assert caught.value.code == "DEVICE_TYPE_IN_USE"
        assert caught.value.status_code == 409
    finally:
        conn.close()


def test_placement_error_taxonomy_covers_overflow_duplicate_asset_and_position(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("taxonomy-rack"),
            site_id="site-default",
            total_u=20,
            rack_code=_id("taxonomy-code"),
        )
        device_type = rack_service.create_device_type(
            conn,
            model=_id("taxonomy-device"),
            vendor="RackVision",
            u_height=2,
        )

        with pytest.raises(rack_placement_service.RackPlacementError) as overflow:
            rack_service.create_rack_device(
                conn,
                name="overflow",
                rack_id=rack["id"],
                device_type_id=device_type["id"],
                start_u=20,
            )
        assert overflow.value.code == "RACK_U_OVERFLOW"
        assert overflow.value.status_code == 409

        with pytest.raises(rack_placement_service.RackPlacementError) as position:
            rack_service.create_rack_device(
                conn,
                name="bad-side-position",
                rack_id=rack["id"],
                device_type_id=device_type["id"],
                start_u=None,
                mount_kind="side_mount",
                position="front",
                location_note="left rail",
            )
        assert position.value.code == "POSITION_NOT_ALLOWED"
        assert position.value.status_code == 422

        asset_id = _id("taxonomy-asset")
        conn.execute(
            """INSERT INTO physical_assets (
                    id, asset_type, site_id, created_at, updated_at
                ) VALUES (?, 'network_device', 'site-default', ?, ?)""",
            (asset_id, "2026-09-06T00:00:00+00:00", "2026-09-06T00:00:00+00:00"),
        )
        conn.commit()
        rack_service.create_rack_device(
            conn,
            name="asset-installation",
            rack_id=rack["id"],
            device_type_id=device_type["id"],
            start_u=5,
            asset_id=asset_id,
        )
        with pytest.raises(rack_placement_service.RackPlacementError) as duplicate:
            rack_service.create_rack_device(
                conn,
                name="duplicate-asset-installation",
                rack_id=rack["id"],
                device_type_id=device_type["id"],
                start_u=10,
                asset_id=asset_id,
            )
        assert duplicate.value.code == "ASSET_ALREADY_INSTALLED"
        assert duplicate.value.status_code == 409
    finally:
        conn.close()
