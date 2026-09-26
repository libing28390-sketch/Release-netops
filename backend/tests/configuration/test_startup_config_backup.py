"""Tests for Startup-Config collection, unsaved drift check, and policy models."""

from __future__ import annotations

import uuid

from backend.tests.pg_test_utils import postgresql_test_driver
from services.platform_registry_service import (
    ACTION_DEFINITIONS,
    PLATFORM_ACTION_COMMANDS,
    SYSTEM_PROFILES,
)
from services.config_backup_command_service import (
    get_config_backup_platform,
    get_default_config_backup_commands,
    is_compatible_published_config_action,
    is_config_backup_candidate,
    is_network_device_for_config_backup,
)
from core.platform_utils import normalize_device_platform
from services import config_backup_policy_service as policy_service


def test_platform_registry_action_and_commands():
    """Verify get_startup_config action and multi-vendor commands are registered."""
    action_codes = [a["action_code"] for a in ACTION_DEFINITIONS]
    assert "get_startup_config" in action_codes

    startup_def = next(a for a in ACTION_DEFINITIONS if a["action_code"] == "get_startup_config")
    assert startup_def["name_zh"] == "获取启动配置"
    assert startup_def["risk"] == "sensitive"
    assert "configuration" in startup_def["consumers"]

    # Verify official command mappings for all major platforms
    assert PLATFORM_ACTION_COMMANDS["cisco_ios"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["huawei_vrp"]["get_startup_config"] == "display saved-configuration"
    assert PLATFORM_ACTION_COMMANDS["h3c_comware"]["get_startup_config"] == "display saved-configuration"
    assert PLATFORM_ACTION_COMMANDS["dptech_ios"]["get_startup_config"] == "display saved-configuration"
    assert PLATFORM_ACTION_COMMANDS["dptech_ios"]["get_running_config"] == "show running-config"
    assert PLATFORM_ACTION_COMMANDS["ruijie_rgos"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["zte_zxros"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["maipu"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["raisecom_ros"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["juniper_junos"]["get_startup_config"] == "show configuration"

    expected_dptech_commands = {
        "get_running_config": "show running-config",
        "get_startup_config": "display saved-configuration",
    }
    for dptech_platform in ("dptech_conplat", "dptech_conplat_fw"):
        assert get_default_config_backup_commands("DPtech", dptech_platform) == expected_dptech_commands
    assert get_default_config_backup_commands("Hillstone", "hillstone_stoneos") == {
        "get_running_config": "show configuration",
        "get_startup_config": "show configuration startup",
    }


def test_default_backup_commands_cover_every_builtin_vendor_independent_of_bound_platform():
    expected = {
        "Cisco": ("show running-config", "show startup-config"),
        "Huawei": ("display current-configuration", "display saved-configuration"),
        "H3C": ("display current-configuration", "display saved-configuration"),
        "Juniper": ("show configuration", "show configuration"),
        "Arista": ("show running-config", "show startup-config"),
        "ZTE": ("show running-config", "show startup-config"),
        "Raisecom": ("show running-config", "show startup-config"),
        "Ruijie": ("show running-config", "show startup-config"),
        "DPtech": ("show running-config", "display saved-configuration"),
        "Hillstone": ("show configuration", "show configuration startup"),
        "Maipu": ("show running-config", "show startup-config"),
    }
    supported_vendors = {str(profile["vendor"]) for profile in SYSTEM_PROFILES}
    assert supported_vendors == set(expected)

    for vendor, (running, startup) in expected.items():
        commands = get_default_config_backup_commands(vendor, "cisco_ios")
        assert commands == {
            "get_running_config": running,
            "get_startup_config": startup,
        }

    assert get_default_config_backup_commands("Fortinet", "cisco_ios") == {
        "get_running_config": "show full-configuration",
        "get_startup_config": "show full-configuration",
    }
    assert get_default_config_backup_commands("Other", "fortinet_fortios")["get_running_config"] == "show full-configuration"
    assert get_default_config_backup_commands("UnknownVendor", "cisco_ios") is None
    assert is_network_device_for_config_backup("H3C", "linux") is True
    assert is_network_device_for_config_backup("", "h3c_comware_v7") is True
    assert is_network_device_for_config_backup("Linux", "ubuntu_server") is False
    assert is_network_device_for_config_backup("NotCisco", "linux") is False


def test_backup_vendor_coverage_matches_asset_platform_catalog_and_fails_closed_for_unverified_vendors():
    platform_vendors = [
        "Cisco", "Huawei", "H3C", "Arista", "Juniper", "Ruijie", "Fortinet",
        "Palo Alto", "Hillstone", "Sangfor", "Check Point", "Sophos", "SonicWall",
        "WatchGuard", "F5", "A10 Networks", "Barracuda", "Venustech", "NSFOCUS",
        "Topsec", "Qi An Xin", "ZTE", "Raisecom", "Maipu", "DPtech", "DCN",
        "FiberHome", "Nokia", "Aruba", "Extreme Networks", "Ruckus", "MikroTik",
        "Ubiquiti", "D-Link", "TP-Link", "Dell", "Brocade", "Ciena",
        "Alcatel-Lucent Enterprise", "Allied Telesis", "Edgecore",
    ]
    assert len(platform_vendors) == 41
    assert all(is_network_device_for_config_backup(vendor) for vendor in platform_vendors)

    default_vendors = {
        "Cisco", "Huawei", "H3C", "Juniper", "Arista", "Ruijie", "ZTE",
        "Raisecom", "DPtech", "Maipu", "Fortinet", "Hillstone",
    }
    assert {
        vendor for vendor in platform_vendors
        if get_default_config_backup_commands(vendor, "cisco_ios") is not None
    } == default_vendors
    assert all(
        get_default_config_backup_commands(vendor, "cisco_ios") is None
        for vendor in set(platform_vendors) - default_vendors
    )
    assert is_config_backup_candidate(
        "Palo Alto",
        "paloalto_panos",
        has_published_profile_action=True,
        profile_vendor="Palo Alto",
        profile_platform_code="paloalto_panos",
        profile_parser_platform="paloalto_panos",
    )
    assert not is_config_backup_candidate("Palo Alto", "paloalto_panos")
    assert not is_config_backup_candidate("UnknownVendor", "cisco_ios")
    assert not is_config_backup_candidate(
        "Palo Alto",
        "paloalto_panos",
        has_published_profile_action=True,
        profile_vendor="Cisco",
        profile_platform_code="paloalto_panos",
        profile_parser_platform="paloalto_panos",
    )
    assert is_config_backup_candidate(
        "Huawei",
        "cisco_ios",
        has_published_profile_action=False,
        profile_vendor="Cisco",
        profile_platform_code="cisco_ios",
        profile_parser_platform="cisco_ios",
    )  # A verified vendor default ignores the stale bound platform/profile.
    assert not is_compatible_published_config_action(
        "Palo Alto", "paloalto_panos", "Cisco", "paloalto_panos", "paloalto_panos",
        has_published_profile_action=True,
    )
    assert not is_config_backup_candidate("Dell", "windows", "server", has_published_profile_action=True)


def test_backup_device_list_matches_default_command_capability_and_excludes_server_assets(isolated_db, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO physical_assets (id, asset_type, hostname, created_at, updated_at) "
            "VALUES ('backup-server-asset', 'server', 'backup-server', '2026-09-26', '2026-09-26')"
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, vendor, platform, status) "
            "VALUES ('backup-h3c', 'backup-h3c', '192.0.2.30', 'H3C', 'linux', 'online')"
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, vendor, platform, status) "
            "VALUES ('backup-paloalto', 'backup-paloalto', '192.0.2.31', 'Palo Alto', 'paloalto_panos', 'online')"
        )
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, vendor, platform, status) "
            "VALUES ('backup-unknown-cisco', 'backup-unknown-cisco', '192.0.2.33', 'UnknownVendor', 'cisco_ios', 'online')"
        )
        conn.execute(
            "INSERT INTO devices (id, asset_id, hostname, ip_address, vendor, platform, status) "
            "VALUES ('backup-dell-server', 'backup-server-asset', 'backup-dell-server', '192.0.2.32', 'Dell', 'windows', 'online')"
        )
        conn.commit()
    finally:
        conn.close()

    from api.configs import list_devices_with_backups

    result = list_devices_with_backups(
        search="",
        site_id="",
        asset_type="",
        device_category="",
        device_role="",
        page=1,
        page_size=100,
    )
    ids = {item["id"] for item in result["items"]}
    assert "backup-h3c" in ids  # Explicit vendor remains enough despite an unrelated platform.
    assert "backup-paloalto" not in ids  # No default command or published profile action.
    assert "backup-unknown-cisco" not in ids  # Unknown explicit vendor cannot borrow the platform's default.
    assert "backup-dell-server" not in ids  # Server assets are not network config backups.

    from api.configs import preview_schedule

    monkeypatch.setattr("api.configs._get_schedule_from_db", lambda: {"enabled": False})
    preview = preview_schedule(1)
    preview_ids = {item["id"] for item in preview["devices"]}
    assert "backup-h3c" in preview_ids
    assert "backup-unknown-cisco" not in preview_ids
    assert "backup-dell-server" not in preview_ids


def test_backup_run_and_schedule_stats_exclude_non_network_assets(isolated_db, monkeypatch):
    from datetime import datetime, timezone

    from api import configs

    database = isolated_db["module"]
    run_id = f"backup-stats-{uuid.uuid4().hex}"
    test_stamp = datetime.now(timezone.utc).replace(hour=0, minute=5, second=0, microsecond=0).isoformat()
    asset_rows = [
        ("network-success", "network_device"),
        ("network-failed", "network_device"),
        ("server", "server"),
        ("host", "host"),
        ("physical-server", "physical_server"),
    ]
    device_rows = []
    for suffix, asset_type in asset_rows:
        asset_id = f"{run_id}-{suffix}-asset"
        device_id = f"{run_id}-{suffix}"
        device_rows.append((suffix, asset_id, device_id, asset_type))

    conn = database.get_db_connection()
    try:
        for index, (suffix, asset_id, device_id, asset_type) in enumerate(device_rows, start=10):
            conn.execute(
                "INSERT INTO physical_assets (id, asset_type, hostname, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (asset_id, asset_type, device_id, test_stamp, test_stamp),
            )
            conn.execute(
                """INSERT INTO devices
                   (id, asset_id, hostname, ip_address, vendor, platform, status, site)
                   VALUES (?, ?, ?, ?, 'Cisco', 'cisco_ios', 'online', ?)""",
                (device_id, asset_id, device_id, f"192.0.2.{index}", f"Site-{run_id}"),
            )

        conn.execute(
            """INSERT INTO config_backup_runs
               (id, trigger, author, status, started_at, total_devices, success_count, failed_count, skipped_count)
               VALUES (?, 'scheduled', 'tester', 'completed', ?, 5, 2, 2, 1)""",
            (run_id, test_stamp),
        )
        statuses = {
            "network-success": "success",
            "network-failed": "failed",
            "server": "failed",
            "host": "success",
            "physical-server": "skipped",
        }
        for index, (suffix, _asset_id, device_id, _asset_type) in enumerate(device_rows, start=30):
            status = statuses[suffix]
            conn.execute(
                """INSERT INTO config_backup_run_devices
                   (id, run_id, device_id, hostname, ip_address, platform, status, started_at)
                   VALUES (?, ?, ?, ?, ?, 'cisco_ios', ?, ?)""",
                (
                    f"{run_id}-{suffix}-result",
                    run_id,
                    device_id,
                    device_id,
                    f"192.0.2.{index}",
                    status,
                    test_stamp,
                ),
            )

        for suffix, _asset_id, device_id, _asset_type in device_rows:
            if suffix not in {"network-success", "server"}:
                continue
            conn.execute(
                """INSERT INTO config_snapshots
                   (id, device_id, hostname, vendor, timestamp, trigger, author, file_path, size)
                   VALUES (?, ?, ?, 'Cisco', ?, 'scheduled', 'tester', '', ?)""",
                (f"{run_id}-{suffix}-snapshot", device_id, device_id, test_stamp, 100 if suffix == "network-success" else 500),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(configs, "get_db_connection", database.get_db_connection)

    listed = configs.list_backup_runs(
        device_id="",
        date="",
        start_date="",
        end_date="",
        page=1,
        page_size=100,
    )
    listed_run = next(item for item in listed["items"] if item["id"] == run_id)
    assert (listed_run["total_devices"], listed_run["success_count"], listed_run["failed_count"], listed_run["skipped_count"]) == (2, 1, 1, 0)
    assert listed_run["site_summary"] == [{
        "site": f"Site-{run_id}",
        "total": 2,
        "success": 1,
        "failed": 1,
        "skipped": 0,
        "unknown": 0,
    }]

    detail = configs.get_backup_run(run_id, site="", status="all", search="", page=1, page_size=100)
    assert (detail["run"]["total_devices"], detail["run"]["success_count"], detail["run"]["failed_count"], detail["run"]["skipped_count"]) == (2, 1, 1, 0)
    assert detail["total"] == 2
    network_device_ids = {row[2] for row in device_rows if row[3] == "network_device"}
    assert {item["device_id"] for item in detail["devices"]} == network_device_ids

    stats = configs.get_backup_stats()["data"]
    assert stats["today"] == {
        "total": 2,
        "scheduled": 2,
        "manual": 0,
        "success": 1,
        "failed": 1,
        "skipped": 0,
        "unobserved": 0,
    }
    assert stats["total_snapshots"] == 1
    assert stats["total_devices_backed"] == 1
    assert stats["storage_bytes"] == 100
    assert len(stats["daily_history"]) == 1
    assert stats["daily_history"][0]["total"] == 1
    assert {item["id"] for item in stats["device_stats"]} == network_device_ids
    assert {item["device_id"] for item in stats["recent_backups"]} == {row[2] for row in device_rows if row[0] == "network-success"}


def test_config_backup_driver_family_follows_vendor_on_mismatched_platform():
    assert get_config_backup_platform("Cisco", "huawei_vrp") == "cisco_ios"
    assert get_config_backup_platform("Huawei", "linux") == "huawei_vrp"
    assert get_config_backup_platform("H3C", "cisco_ios") == "h3c_comware"
    assert get_config_backup_platform("Huawei", "huawei_vrpv8") == "huawei_vrpv8"
    assert normalize_device_platform("Cisco", "huawei_vrp") == "cisco_ios"
    assert normalize_device_platform("Huawei", "linux") == "huawei_vrp"


def test_backup_policy_model_with_tftp_and_startup():
    """Test policy model creation and parsing with startup config and TFTP fields."""
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.execute(
        """
        CREATE TABLE config_backup_policies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            cron_expr TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
            priority INTEGER NOT NULL DEFAULT 100,
            scope_json TEXT NOT NULL DEFAULT '{}',
            config_types_json TEXT NOT NULL DEFAULT '["running"]',
            change_only INTEGER NOT NULL DEFAULT 1,
            retention_days INTEGER NOT NULL DEFAULT 90,
            max_versions_per_device INTEGER NOT NULL DEFAULT 30,
            concurrency INTEGER NOT NULL DEFAULT 10,
            retry_count INTEGER NOT NULL DEFAULT 1,
            timeout_seconds INTEGER NOT NULL DEFAULT 30,
            collect_startup_config INTEGER NOT NULL DEFAULT 0,
            tftp_enabled INTEGER NOT NULL DEFAULT 0,
            tftp_server TEXT NOT NULL DEFAULT '',
            tftp_port INTEGER NOT NULL DEFAULT 69,
            tftp_path_prefix TEXT NOT NULL DEFAULT 'backups',
            tftp_protocol TEXT NOT NULL DEFAULT 'tftp',
            tftp_username TEXT NOT NULL DEFAULT '',
            tftp_password TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()

    payload = {
        "name": "DataCenter-Full-Backup",
        "description": "Daily DC running & startup backup with TFTP transfer",
        "cron_expr": "0 3 * * *",
        "timezone": "Asia/Shanghai",
        "priority": 100,
        "scope": {"vendors": ["Huawei", "Cisco"]},
        "config_types": ["running", "startup"],
        "collect_startup_config": True,
        "tftp_enabled": True,
        "tftp_server": "192.168.10.50",
        "tftp_port": 69,
        "tftp_path_prefix": "dc_backups",
    }

    created = policy_service.create_policy(
        conn,
        payload,
        actor="admin",
    )

    assert created["name"] == "DataCenter-Full-Backup"
    assert created["collect_startup_config"] is True
    assert created["tftp_enabled"] is True
    assert created["tftp_server"] == "192.168.10.50"
    assert created["tftp_path_prefix"] == "dc_backups"

    retrieved = policy_service.get_policy(conn, created["id"])
    assert retrieved is not None
    assert retrieved["collect_startup_config"] is True
    assert retrieved["tftp_enabled"] is True
    assert retrieved["tftp_server"] == "192.168.10.50"

    updated = policy_service.update_policy(
        conn,
        created["id"],
        {"tftp_server": "192.168.10.55", "collect_startup_config": False},
        actor="admin",
    )
    assert updated["tftp_server"] == "192.168.10.55"
    assert updated["collect_startup_config"] is False

    conn.close()


def test_finish_backup_run_records_counts_and_tftp(monkeypatch, tmp_path):
    """Verify _finish_backup_run aggregates success count and updates config_backup_runs row."""
    from api.configs import _finish_backup_run

    db_file = str(tmp_path / "test_backup_runs.db")

    def _get_conn():
        conn = postgresql_test_driver.connect(db_file)
        conn.row_factory = postgresql_test_driver.Row
        return conn

    conn = _get_conn()
    conn.executescript(
        """
        CREATE TABLE config_backup_runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            finished_at TEXT,
            total_devices INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT DEFAULT '',
            tftp_status TEXT NOT NULL DEFAULT 'none',
            tftp_server TEXT NOT NULL DEFAULT '',
            tftp_log TEXT NOT NULL DEFAULT '',
            tftp_uploaded_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE config_backup_run_devices (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL
        );
        """
    )
    conn.execute("INSERT INTO config_backup_runs (id, total_devices) VALUES ('run-test-01', 2)")
    conn.execute("INSERT INTO config_backup_run_devices (id, run_id, status) VALUES ('d1', 'run-test-01', 'success')")
    conn.execute("INSERT INTO config_backup_run_devices (id, run_id, status) VALUES ('d2', 'run-test-01', 'success')")
    conn.commit()
    conn.close()

    monkeypatch.setattr("api.configs.get_db_connection", _get_conn)

    _finish_backup_run(
        "run-test-01",
        tftp_status="success",
        tftp_server="10.0.0.1",
        tftp_log="Uploaded 2 files",
        tftp_uploaded_count=2,
    )

    check_conn = _get_conn()
    row = check_conn.execute("SELECT * FROM config_backup_runs WHERE id = 'run-test-01'").fetchone()
    assert row["status"] == "completed"
    assert row["success_count"] == 2
    assert row["failed_count"] == 0
    assert row["total_devices"] == 2
    assert row["tftp_status"] == "success"
    assert row["tftp_server"] == "10.0.0.1"
    assert row["tftp_uploaded_count"] == 2
    check_conn.close()
