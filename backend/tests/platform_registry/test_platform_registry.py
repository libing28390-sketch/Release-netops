from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.platform_registry_service import (
    PlatformRegistryError,
    create_profile,
    create_release,
    execute_platform_action,
    is_safe_read_command,
    list_release_actions,
    transition_release,
    update_release_action,
)


def test_migration_seeds_registry_and_action_catalog(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert {"platform_profiles", "platform_releases", "action_definitions", "platform_release_actions", "parser_templates", "parser_template_versions"} <= tables
        assert conn.execute("SELECT COUNT(*) AS count FROM action_definitions").fetchone()["count"] == 20
        release = conn.execute(
            """SELECT p.platform_code, r.status, r.release_number
               FROM platform_profiles p JOIN platform_releases r ON r.id = p.current_release_id
               WHERE p.platform_code = 'zte_5900_v6'"""
        ).fetchone()
        assert dict(release) == {"platform_code": "zte_5900_v6", "status": "PUBLISHED", "release_number": 1}
    finally:
        conn.close()


def test_read_command_guard_rejects_config_and_shell_chaining():
    assert is_safe_read_command("show version", "cisco_ios")
    assert is_safe_read_command("display version", "huawei_vrp")
    assert not is_safe_read_command("configure terminal", "cisco_ios")
    assert not is_safe_read_command("show version; reload", "cisco_ios")
    assert not is_safe_read_command("show version && whoami", "cisco_ios")
    assert not is_safe_read_command("show version\nshow running-config", "cisco_ios")


def test_release_flow_rejects_self_approval_and_publishes_atomically(isolated_db):
    user = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}
    profile = create_profile({"platform_code": "acme_lab", "name_zh": "测试平台", "connection_driver": "netmiko", "parser_platform": "cisco_ios"}, user)
    release = create_release(profile["id"], {}, user)
    update_release_action(release["id"], "get_clock", {"command": "show clock"}, user)
    transition_release(release["id"], "submit", user)
    with pytest.raises(PlatformRegistryError, match="creator cannot approve"):
        transition_release(release["id"], "approve", user)
    transition_release(release["id"], "approve", reviewer)
    published = transition_release(release["id"], "publish", reviewer)
    assert published["status"] == "PUBLISHED"
    actions = list_release_actions(profile["id"], reviewer)
    assert any(item["action_code"] == "get_clock" and item["command"] == "show clock" for item in actions)


def test_execute_uses_published_release_and_returns_traceability(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status, username, password, connection_method, platform_profile_id, platform_source, tenant_id)
               VALUES ('device-1', 'edge-1', '192.0.2.10', 'cisco_ios', 'active', 'u', 'p', 'mock', 'system-profile-cisco_ios', 'SYSTEM', 'tenant-1')"""
        )
        conn.commit()
    finally:
        conn.close()

    class FakeDriver:
        def __init__(self, *_args, **_kwargs):
            self.commands = []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send_command(self, command):
            self.commands.append(command)
            return SimpleNamespace(success=True, output="", error=None)

    class FakeFactory:
        @classmethod
        def get_driver(cls, *_args, **_kwargs):
            return FakeDriver()

    result = execute_platform_action(
        "device-1",
        "get_clock",
        user={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
        driver_factory=FakeFactory,
    )
    assert result["success"] is True
    assert result["action_code"] == "get_clock"
    assert result["platform_release_id"] == "system-release-cisco_ios-v1"
    assert result["release_number"] == 1
    assert result["command"] == "show clock"

    with pytest.raises(PlatformRegistryError) as error:
        execute_platform_action(
            "device-1",
            "does_not_exist",
            user={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
            driver_factory=FakeFactory,
        )
    assert error.value.code == "UNSUPPORTED_ACTION"
