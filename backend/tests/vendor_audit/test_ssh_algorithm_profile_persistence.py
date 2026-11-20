from __future__ import annotations

from api import assets
from api import devices
from database import get_db_connection


def test_asset_profile_is_persisted_and_synced_to_linked_device(isolated_db):
    created = assets.create_asset(
        assets.AssetCreate(
            asset_type="network_device",
            hostname="legacy-profile-switch",
            management_ip="192.0.2.210",
            vendor="Cisco",
            model="old-ios",
            platform="cisco_ios",
            ssh_algorithm_profile="legacy_break_glass",
        )
    )

    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT ssh_algorithm_profile FROM physical_assets WHERE id = ?",
            (created["id"],),
        ).fetchone()
        device = conn.execute(
            "SELECT ssh_algorithm_profile FROM devices WHERE id = ?",
            (created["device_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert asset["ssh_algorithm_profile"] == "legacy_break_glass"
    assert device["ssh_algorithm_profile"] == "legacy_break_glass"

    assets.update_asset(
        created["id"],
        assets.AssetUpdate(ssh_algorithm_profile="modern"),
    )

    conn = get_db_connection()
    try:
        asset = conn.execute(
            "SELECT ssh_algorithm_profile FROM physical_assets WHERE id = ?",
            (created["id"],),
        ).fetchone()
        device = conn.execute(
            "SELECT ssh_algorithm_profile FROM devices WHERE id = ?",
            (created["device_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert asset["ssh_algorithm_profile"] == "modern"
    assert device["ssh_algorithm_profile"] == "modern"


def test_unknown_asset_profile_fails_closed_to_auto():
    body = assets.AssetCreate(
        asset_type="network_device",
        hostname="profile-normalization",
        management_ip="192.0.2.211",
        ssh_algorithm_profile="unsupported-profile",
    )
    assert body.ssh_algorithm_profile == "auto"


def test_direct_device_profile_is_persisted_and_updates_linked_asset(isolated_db):
    created = devices.create_device(
        {
            "id": "direct-profile-device",
            "hostname": "direct-profile-device",
            "ip_address": "192.0.2.212",
            "vendor": "Huawei",
            "platform": "huawei_vrp",
            "ssh_algorithm_profile": "legacy_break_glass",
        },
        user={"tenant_id": "tenant-default", "username": "operator", "role": "Operator"},
    )
    assert created["ssh_algorithm_profile"] == "legacy_break_glass"

    devices.update_device(
        "direct-profile-device",
        {"ssh_algorithm_profile": "modern"},
    )

    conn = get_db_connection()
    try:
        device = conn.execute(
            "SELECT ssh_algorithm_profile, asset_id FROM devices WHERE id = ?",
            ("direct-profile-device",),
        ).fetchone()
        asset = conn.execute(
            "SELECT ssh_algorithm_profile FROM physical_assets WHERE id = ?",
            (device["asset_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert device["ssh_algorithm_profile"] == "modern"
    assert asset["ssh_algorithm_profile"] == "modern"
