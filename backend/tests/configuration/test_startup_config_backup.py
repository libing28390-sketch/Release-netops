"""Tests for Startup-Config collection, unsaved drift check, and policy models."""

from __future__ import annotations

import sqlite3
import pytest

from services.platform_registry_service import (
    ACTION_DEFINITIONS,
    PLATFORM_ACTION_COMMANDS,
)
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
    assert PLATFORM_ACTION_COMMANDS["dptech_ios"]["get_running_config"] == "display current-configuration"
    assert PLATFORM_ACTION_COMMANDS["ruijie_rgos"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["zte_zxros"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["maipu"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["raisecom_ros"]["get_startup_config"] == "show startup-config"
    assert PLATFORM_ACTION_COMMANDS["juniper_junos"]["get_startup_config"] == "show configuration"


def test_backup_policy_model_with_tftp_and_startup():
    """Test policy model creation and parsing with startup config and TFTP fields."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
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
        conn = sqlite3.connect(db_file)
        conn.row_factory = sqlite3.Row
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
