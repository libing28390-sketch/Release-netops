from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from services.platform_registry_service import (
    PlatformRegistryError,
    _coerce_field_types,
    _field_contract,
    _normalize_records,
    create_profile,
    create_release,
    delete_profile,
    delete_release,
    execute_platform_action,
    is_safe_read_command,
    list_profiles,
    list_release_actions,
    preview_platform_action,
    transition_release,
    update_profile,
    update_release_action,
    iter_action_definitions,
)
from services.platform_registry_health_service import get_profile_health


def test_migration_seeds_registry_and_action_catalog(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        tables = {
            row["table_name"]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            ).fetchall()
        }
        assert {"platform_profiles", "platform_releases", "action_definitions", "platform_release_actions", "platform_action_runs", "parser_templates", "parser_template_versions", "playbook_versions", "custom_scenarios"} <= tables
        profile_columns = {
            row["column_name"]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'platform_profiles'"
            ).fetchall()
        }
        assert {"adaptation_status", "sample_status"} <= profile_columns
        execution_columns = {
            row["column_name"]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'playbook_executions'"
            ).fetchall()
        }
        assert {"playbook_version_id", "tenant_id", "results_encrypted", "raw_output_expires_at"} <= execution_columns
        assert "tenant_id" in {
            row["column_name"]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'custom_scenarios'"
            ).fetchall()
        }
        version_columns = {
            row["column_name"]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'playbook_versions'"
            ).fetchall()
        }
        assert {"validation_status", "validation_result_json", "submitted_by", "approved_by", "published_by", "lock_version"} <= version_columns
        assert conn.execute("SELECT COUNT(*) AS count FROM action_definitions").fetchone()["count"] == len(iter_action_definitions())
        release = conn.execute(
            """SELECT p.platform_code, r.status, r.release_number
               FROM platform_profiles p JOIN platform_releases r ON r.id = p.current_release_id
               WHERE p.platform_code = 'zte_5900_v6'"""
        ).fetchone()
        assert dict(release) == {"platform_code": "zte_5900_v6", "status": "PUBLISHED", "release_number": 1}
        domestic_status = conn.execute(
            "SELECT adaptation_status, sample_status FROM platform_profiles WHERE platform_code = 'zte_5900_v6'"
        ).fetchone()
        assert dict(domestic_status) == {"adaptation_status": "UNVERIFIED", "sample_status": "MISSING"}
        h3c_actions = conn.execute(
            """SELECT COUNT(*) AS count
               FROM platform_release_actions a
               JOIN platform_releases r ON r.id = a.release_id
               JOIN platform_profiles p ON p.id = r.profile_id
               WHERE p.platform_code = 'h3c_comware' AND r.status = 'PUBLISHED'"""
        ).fetchone()
        assert h3c_actions["count"] > 0
        h3c_action = conn.execute(
            """SELECT a.command
               FROM platform_release_actions a
               JOIN platform_releases r ON r.id = a.release_id
               JOIN platform_profiles p ON p.id = r.profile_id
               WHERE p.platform_code = 'h3c_comware' AND a.action_code = 'get_bgp_neighbors'"""
         ).fetchone()
        assert h3c_action["command"] == "display bgp peer ipv4 unicast"
        assert (Path(__file__).parents[2] / ".." / "data" / "textfsm_templates" / "h3c_comware_v7_display_bgp_peer_ipv4_unicast.textfsm").resolve().exists()
    finally:
        conn.close()


def test_read_command_guard_rejects_config_and_shell_chaining():
    assert is_safe_read_command("show version", "cisco_ios")
    assert is_safe_read_command("display version", "huawei_vrp")
    assert not is_safe_read_command("configure terminal", "cisco_ios")
    assert not is_safe_read_command("show version; reload", "cisco_ios")
    assert not is_safe_read_command("show version && whoami", "cisco_ios")
    assert not is_safe_read_command("show version\nshow running-config", "cisco_ios")


def test_registry_read_model_returns_tenant_scoped_binding_stats(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.executemany(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, platform_profile_id, tenant_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                ("registry-device-1", "edge-tenant-1", "192.0.2.20", "cisco_ios", "online", "system-profile-cisco_ios", "tenant-1"),
                ("registry-device-2", "edge-tenant-2", "192.0.2.21", "cisco_ios", "online", "system-profile-cisco_ios", "tenant-2"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    profiles = list_profiles({"role": "Viewer", "tenant_id": "tenant-1"})
    cisco = next(item for item in profiles if item["platform_code"] == "cisco_ios")
    assert cisco["bound_device_count"] == 1
    assert cisco["online_device_count"] == 1
    assert cisco["current_release_status"] == "PUBLISHED"
    assert cisco["current_action_count"] > 0


def test_custom_profile_can_be_updated_and_unbound_profile_archived(isolated_db):
    user = {"id": "profile-owner", "username": "profile-owner", "role": "Operator", "tenant_id": "tenant-1"}
    profile = create_profile(
        {"platform_code": "crud_lab", "name_en": "CRUD Lab", "vendor": "Acme", "connection_driver": "netmiko", "parser_platform": "cisco_ios"},
        user,
    )

    updated = update_profile(profile["id"], {"name_en": "CRUD Lab Updated", "description": "editable metadata"}, user)
    assert updated["name_en"] == "CRUD Lab Updated"
    assert updated["description"] == "editable metadata"

    deleted = delete_profile(profile["id"], user)
    assert deleted == {"id": profile["id"], "status": "ARCHIVED", "deleted": True, "bound_device_count": 0}
    assert all(item["id"] != profile["id"] for item in list_profiles(user))


def test_bound_profile_cannot_delete_or_change_identity_but_can_change_metadata(isolated_db):
    user = {"id": "bound-owner", "username": "bound-owner", "role": "Operator", "tenant_id": "tenant-1"}
    profile = create_profile(
        {"platform_code": "bound_lab", "name_en": "Bound Lab", "vendor": "Acme", "connection_driver": "netmiko", "parser_platform": "cisco_ios"},
        user,
    )
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, platform, platform_profile_id, tenant_id) VALUES (?, ?, ?, ?, ?)",
            ("bound-profile-device", "bound-device", "bound_lab", profile["id"], "tenant-1"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(PlatformRegistryError) as identity_error:
        update_profile(profile["id"], {"platform_code": "bound_lab_v2"}, user)
    assert identity_error.value.code == "PLATFORM_IDENTITY_LOCKED"

    metadata = update_profile(profile["id"], {"vendor": "Acme Updated"}, user)
    assert metadata["vendor"] == "Acme Updated"

    with pytest.raises(PlatformRegistryError) as delete_error:
        delete_profile(profile["id"], user)
    assert delete_error.value.code == "PLATFORM_BOUND_DEVICES"
    assert delete_error.value.status_code == 409


def test_system_profile_is_read_only_for_profile_crud(isolated_db):
    user = {"id": "system-editor", "username": "system-editor", "role": "Administrator", "tenant_id": "tenant-1"}
    system_profile_id = "system-profile-cisco_ios"

    with pytest.raises(PlatformRegistryError) as update_error:
        update_profile(system_profile_id, {"name_en": "Do not edit"}, user)
    assert update_error.value.code == "SYSTEM_PROFILE_READ_ONLY"

    with pytest.raises(PlatformRegistryError) as delete_error:
        delete_profile(system_profile_id, user)
    assert delete_error.value.code == "SYSTEM_PROFILE_READ_ONLY"


def test_standard_normalizer_applies_contract_aliases_and_scalar_types():
    contract = _field_contract({
        "required": ["ip_address", "interface"],
        "types": {"prefix_length": "integer"},
    })
    records = _normalize_records(
        [{"IP ADDRESS": "192.0.2.1", "PORT": "Gi1/0/1", "PREFIX-LENGTH": "24"}],
        10,
        expected_fields={"ip_address", "interface", "prefix_length"},
    )
    _coerce_field_types(records, contract)
    assert records == [{
        "ip_address": "192.0.2.1",
        "port": "Gi1/0/1",
        "prefix_length": 24,
        "interface": "Gi1/0/1",
    }]


def test_operational_catalog_uses_published_registry_commands(isolated_db):
    from services.operational_data_service import _resolve_commands

    assert _resolve_commands("h3c_comware", ["bgp", "neighbors"]) == {
        "bgp": ["display bgp peer ipv4 unicast"],
        "neighbors": ["display lldp neighbor-information list"],
    }
    assert _resolve_commands("cisco_ios", ["neighbors"]) == {"neighbors": ["show lldp neighbors"]}
    assert _resolve_commands("huawei_vrp", ["eth_trunk"]) == {"eth_trunk": ["display eth-trunk"]}


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


def test_new_release_reuses_draft_and_copies_published_action_snapshot(isolated_db):
    author = {"id": "author-copy", "username": "author-copy", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-copy", "username": "reviewer-copy", "role": "Administrator", "tenant_id": "tenant-1"}
    profile = create_profile(
        {"platform_code": "copy_release_lab", "name_zh": "复制测试", "connection_driver": "netmiko", "parser_platform": "cisco_ios"},
        author,
    )
    first = create_release(profile["id"], {}, author)
    update_release_action(first["id"], "get_clock", {"command": "show clock"}, author)
    transition_release(first["id"], "submit", author)
    transition_release(first["id"], "approve", reviewer)
    transition_release(first["id"], "publish", reviewer)

    draft = create_release(profile["id"], {}, author)
    same_draft = create_release(profile["id"], {}, author)
    assert same_draft["id"] == draft["id"]
    mapping = next(item for item in list_release_actions(profile["id"], author, draft["id"]) if item["action_code"] == "get_clock")
    assert mapping["command"] == "show clock"


def test_draft_release_can_be_deleted_before_review(isolated_db):
    author = {"id": "author-delete", "username": "author-delete", "role": "Operator", "tenant_id": "tenant-1"}
    profile = create_profile(
        {"platform_code": "delete_release_lab", "name_zh": "删除草稿测试", "connection_driver": "netmiko", "parser_platform": "cisco_ios"},
        author,
    )
    release = create_release(profile["id"], {}, author)
    deleted = delete_release(release["id"], author)
    assert deleted == {"id": release["id"], "profile_id": profile["id"], "deleted": True}
    conn = isolated_db["module"].get_db_connection()
    try:
        assert conn.execute("SELECT 1 FROM platform_releases WHERE id = ?", (release["id"],)).fetchone() is None
        assert conn.execute("SELECT 1 FROM platform_release_actions WHERE release_id = ?", (release["id"],)).fetchone() is None
    finally:
        conn.close()


def test_release_rejection_returns_to_draft_with_reason(isolated_db):
    author = {"id": "author-reject", "username": "author-reject", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-reject", "username": "reviewer-reject", "role": "Administrator", "tenant_id": "tenant-1"}
    profile = create_profile(
        {"platform_code": "reject_release_lab", "name_zh": "驳回测试", "connection_driver": "netmiko", "parser_platform": "cisco_ios"},
        author,
    )
    release = create_release(profile["id"], {}, author)
    update_release_action(release["id"], "get_clock", {"command": "show clock"}, author)
    transition_release(release["id"], "submit", author)
    rejected = transition_release(release["id"], "reject", reviewer, reason="请补充目标解析版本")
    assert rejected["status"] == "DRAFT"
    assert rejected["validation_status"] == "PENDING"
    conn = isolated_db["module"].get_db_connection()
    try:
        audit = conn.execute(
            "SELECT event_type, metadata_json FROM platform_release_audit_logs WHERE release_id = ? AND event_type = 'REJECT' ORDER BY created_at DESC LIMIT 1",
            (release["id"],),
        ).fetchone()
    finally:
        conn.close()
    assert audit["event_type"] == "REJECT"
    assert "请补充目标解析版本" in audit["metadata_json"]


def test_release_submitter_can_withdraw_in_review_release(isolated_db):
    author = {"id": "author-withdraw", "username": "author-withdraw", "role": "Operator", "tenant_id": "tenant-1"}
    other = {"id": "other-withdraw", "username": "other-withdraw", "role": "Operator", "tenant_id": "tenant-1"}
    profile = create_profile(
        {"platform_code": "withdraw_release_lab", "name_zh": "撤回测试", "connection_driver": "netmiko", "parser_platform": "cisco_ios"},
        author,
    )
    release = create_release(profile["id"], {}, author)
    update_release_action(release["id"], "get_clock", {"command": "show clock"}, author)
    transition_release(release["id"], "submit", author)
    with pytest.raises(PlatformRegistryError) as forbidden:
        transition_release(release["id"], "withdraw", other)
    assert forbidden.value.code == "RELEASE_WITHDRAW_FORBIDDEN"
    withdrawn = transition_release(release["id"], "withdraw", author)
    assert withdrawn["status"] == "DRAFT"


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
        captured_device = {}

        @classmethod
        def get_driver(cls, _driver_type, device_info):
            cls.captured_device = dict(device_info)
            return FakeDriver()

    result = execute_platform_action(
        "device-1",
        "get_clock",
        user={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
        connection_options={
            "conn_timeout": 60,
            "timeout": 60,
            "banner_timeout": 60,
            "auth_timeout": 60,
            "blocking_timeout": 60,
            "session_timeout": 120,
            "read_timeout": 60,
            "command_read_timeout": 60,
        },
        driver_factory=FakeFactory,
    )
    assert result["success"] is True
    assert result["action_code"] == "get_clock"
    assert result["platform_release_id"] == "system-release-cisco_ios-v1"
    assert result["release_number"] == 1
    assert result["command"] == "show clock"
    assert result["raw_output"] is None
    assert FakeFactory.captured_device["banner_timeout"] == 60
    assert FakeFactory.captured_device["command_read_timeout"] == 60

    telemetry = isolated_db["module"].get_db_connection()
    try:
        run = telemetry.execute(
            "SELECT status, action_code, failure_stage, output_bytes FROM platform_action_runs WHERE device_id = ?",
            ("device-1",),
        ).fetchone()
        assert dict(run) == {"status": "SUCCESS", "action_code": "get_clock", "failure_stage": None, "output_bytes": 0}
    finally:
        telemetry.close()

    health = get_profile_health(
        "system-profile-cisco_ios",
        {"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
    )
    assert health["recent_run_count"] == 1
    assert health["recent_success_rate_pct"] == 100.0
    assert health["health_score_available"] is True

    with pytest.raises(PlatformRegistryError) as scope_error:
        execute_platform_action(
            "device-1",
            "get_clock",
            user={"id": "operator-2", "username": "operator-2", "role": "Operator"},
            driver_factory=FakeFactory,
        )
    assert scope_error.value.code == "DEVICE_SCOPE_DENIED"

    with pytest.raises(PlatformRegistryError) as error:
        execute_platform_action(
            "device-1",
            "does_not_exist",
            user={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
            driver_factory=FakeFactory,
        )
    assert error.value.code == "UNSUPPORTED_ACTION"


def test_h3c_v7_action_executes_with_the_published_v7_textfsm_template(isolated_db):
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "cli"
        / "h3c"
        / "h3c_comware"
        / "display_cpu_usage"
        / "comware_v7_summary.txt"
    ).read_text(encoding="utf-8")
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, username, password,
                connection_method, platform_profile_id, platform_source, tenant_id)
               VALUES ('h3c-v7-action-device', 'h3c-v7-edge', '192.0.2.77',
                       'h3c_comware', 'active', 'u', 'p', 'mock',
                       'system-profile-h3c_comware', 'SYSTEM', 'tenant-1')"""
        )
        conn.commit()
    finally:
        conn.close()

    class V7Driver:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send_command(self, command):
            assert command == "display cpu-usage"
            return SimpleNamespace(success=True, output=fixture, error=None)

    class V7Factory:
        @classmethod
        def get_driver(cls, _driver_type, _device_info):
            return V7Driver()

    result = execute_platform_action(
        "h3c-v7-action-device",
        "get_cpu",
        user={"id": "operator-v7", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
        driver_factory=V7Factory,
    )

    assert result["success"] is True
    assert result["command"] == "display cpu-usage"
    assert result["template"] == "h3c_comware_v7_display_cpu_usage.textfsm"
    assert result["parser"] == "textfsm:h3c_comware_v7_display_cpu_usage.textfsm"
    assert result["parser_selection"] == "automatic"
    assert result["records"]


def test_execute_applies_resolved_collector_credentials_before_driver(isolated_db, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, username, password,
                connection_method, platform_profile_id, tenant_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "credential-device-1",
                "credential-edge-1",
                "192.0.2.30",
                "cisco_ios",
                "active",
                "stale-user",
                "stale-password",
                "mock",
                "system-profile-cisco_ios",
                "tenant-1",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device, ssh_role="normal": {
            "ssh": {
                "username": "center-user",
                "password": "center-password",
                "enable_password": "",
                "role": ssh_role,
            }
        },
    )

    captured = {}

    class CredentialCaptureDriver:
        def __init__(self, device_info):
            captured.update({
                "username": device_info.get("username"),
                "password": device_info.get("password"),
            })

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send_command(self, _command):
            return SimpleNamespace(success=True, output="", error=None)

    class CredentialCaptureFactory:
        @classmethod
        def get_driver(cls, *_args, **_kwargs):
            return CredentialCaptureDriver(_args[1])

    result = execute_platform_action(
        "credential-device-1",
        "get_clock",
        user={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
        driver_factory=CredentialCaptureFactory,
    )

    assert result["success"] is True
    assert captured == {"username": "center-user", "password": "center-password"}


def test_parameterized_action_preview_is_rendered_and_restricted(isolated_db):
    user = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}
    profile = create_profile(
        {"platform_code": "param_lab", "name_zh": "参数平台", "connection_driver": "netmiko", "parser_platform": "cisco_ios"},
        user,
    )
    release = create_release(profile["id"], {}, user)
    update_release_action(
        release["id"],
        "get_route_table",
        {"command": "show ip route {{target}}"},
        user,
    )
    transition_release(release["id"], "submit", user)
    transition_release(release["id"], "approve", reviewer)
    transition_release(release["id"], "publish", reviewer)
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, platform, status, username, password, connection_method, platform_profile_id, tenant_id)
               VALUES ('param-device', 'param-edge', '192.0.2.20', 'param_lab', 'active', 'u', 'p', 'mock', ?, 'tenant-1')""",
            (profile["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    preview = preview_platform_action(
        "param-device",
        "get_route_table",
        user=user,
        parameters={"target": "192.0.2.1"},
    )
    assert preview["command"] == "show ip route 192.0.2.1"
    assert preview["resolved_command_checksum"]
    with pytest.raises(PlatformRegistryError) as error:
        preview_platform_action(
            "param-device",
            "get_route_table",
            user=user,
            parameters={"target": "192.0.2.1;reload"},
        )
    assert error.value.code == "INVALID_ACTION_PARAMETERS"
