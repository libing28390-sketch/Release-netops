from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from api.playbooks.engine import _bind_legacy_phase_commands, _execute_notification_steps, _phase_action_steps
from api.playbooks.routes import execute_playbook, _assert_execution_scope, _assert_playbook_device_scope, _validate_execution_limits
from api.playbooks.scenarios import extract_approval_steps, select_controlled_steps, validate_controlled_phases
from core import crypto
from core.config import settings
from core.rbac import authorize_resource
from services.access_scope_service import replace_user_scopes
from services.playbook_output_service import PlaybookOutputError, cleanup_expired_playbook_outputs, load_output, protect_output
from services.playbook_execution_approval_service import (
    PlaybookApprovalError,
    create_execution_approvals,
    decide_execution_approval,
    execution_start_payload,
    list_execution_approvals,
)

from services.playbook_version_service import (
    PlaybookVersionError,
    approve_version,
    create_version,
    get_version,
    list_versions,
    publish_version,
    rollback_version,
    submit_version,
    update_version,
    validate_version,
)


def _definition():
    return {
        "scenario_id": "custom-playbook",
        "platform": "cisco_ios",
        "phases": {"pre_check": [{"action_code": "get_clock"}], "execute": []},
    }


def test_playbook_version_lifecycle_is_immutable_and_audited(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    author = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}

    version = create_version("custom-playbook", {"name": "受控场景", "definition": _definition()}, author)
    assert version["status"] == "DRAFT"
    assert version["checksum"]
    validation = validate_version(version["id"], author)
    assert validation["valid"] is True
    submitted = submit_version(version["id"], author)
    assert submitted["status"] == "IN_REVIEW"
    approved = approve_version(version["id"], reviewer)
    assert approved["status"] == "APPROVED"
    published = publish_version(version["id"], reviewer)
    assert published["status"] == "PUBLISHED"

    versions = list_versions("custom-playbook", author)
    assert [item["status"] for item in versions] == ["PUBLISHED"]
    assert get_version(version["id"], author)["definition"]["phases"]["pre_check"][0]["action_code"] == "get_clock"

    conn = isolated_db["module"].get_db_connection()
    try:
        audit = conn.execute(
            "SELECT event_type FROM playbook_release_audit_logs WHERE playbook_version_id = ? ORDER BY created_at",
            (version["id"],),
        ).fetchall()
        assert {row["event_type"] for row in audit} >= {"CREATE", "VALIDATE", "SUBMIT", "APPROVE", "PUBLISH"}
    finally:
        conn.close()


def test_playbook_version_rejects_self_approval_and_cross_tenant_access(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    author = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    other_tenant = {"id": "other-1", "username": "other", "role": "Operator", "tenant_id": "tenant-2"}
    version = create_version("tenant-playbook", {"definition": _definition()}, author)
    validate_version(version["id"], author)
    submit_version(version["id"], author)
    with pytest.raises(PlaybookVersionError) as self_approval:
        approve_version(version["id"], author)
    assert self_approval.value.code == "SELF_APPROVAL_FORBIDDEN"
    with pytest.raises(PlaybookVersionError) as scope_error:
        get_version(version["id"], other_tenant)
    assert scope_error.value.code == "PLAYBOOK_SCOPE_DENIED"


def test_playbook_version_updates_draft_and_invalidates_validation(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    author = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}
    version = create_version("editable-playbook", {"name": "v1", "definition": _definition()}, author)
    assert validate_version(version["id"], author)["valid"] is True
    updated = update_version(version["id"], {"name": "v2", "definition": {"phases": {"execute": [{"action_code": "get_version"}]}}}, author)
    assert updated["name"] == "v2"
    assert updated["validation_status"] == "PENDING"
    assert updated["definition"]["phases"]["execute"][0]["action_code"] == "get_version"
    with pytest.raises(PlaybookVersionError) as raw_error:
        update_version(version["id"], {"definition": {"phases": {"execute": ["show version"]}}}, author)
    assert raw_error.value.code == "RAW_COMMAND_DISABLED"
    validate_version(version["id"], author)
    submit_version(version["id"], author)
    approve_version(version["id"], reviewer)
    publish_version(version["id"], reviewer)
    with pytest.raises(PlaybookVersionError) as immutable_error:
        update_version(version["id"], {"definition": _definition()}, author)
    assert immutable_error.value.code == "PLAYBOOK_VERSION_IMMUTABLE"


def test_playbook_version_rollback_publishes_previous_version(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    author = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    reviewer = {"id": "reviewer-1", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}

    first = create_version("rollback-playbook", {"definition": _definition()}, author)
    validate_version(first["id"], author)
    submit_version(first["id"], author)
    approve_version(first["id"], reviewer)
    publish_version(first["id"], reviewer)

    second = create_version("rollback-playbook", {"definition": _definition()}, author)
    validate_version(second["id"], author)
    submit_version(second["id"], author)
    approve_version(second["id"], reviewer)
    publish_version(second["id"], reviewer)

    restored = rollback_version("rollback-playbook", first["id"], reviewer)
    assert restored["status"] == "PUBLISHED"
    all_versions = {item["id"]: item for item in list_versions("rollback-playbook", reviewer)}
    assert all_versions[first["id"]]["status"] == "PUBLISHED"
    assert all_versions[second["id"]]["status"] == "DEPRECATED"


def test_playbook_version_rejects_raw_steps_when_registry_enabled(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    user = {"id": "author-1", "username": "author", "role": "Operator", "tenant_id": "tenant-1"}
    with pytest.raises(PlaybookVersionError) as error:
        create_version("unsafe-playbook", {"definition": {"phases": {"execute": ["show clock"]}}}, user)
    assert error.value.code == "RAW_COMMAND_DISABLED"


def test_controlled_playbook_steps_have_bounded_shape():
    errors = validate_controlled_phases({"execute": [{"action_code": "get_clock"}] * 201})
    assert {item["code"] for item in errors} == {"PLAYBOOK_STEP_LIMIT_EXCEEDED"}
    assert validate_controlled_phases({"execute": [{"action_code": "get_clock", "repeat": 10}]}) == []
    assert validate_controlled_phases({"execute": [{"action_code": "get_clock", "repeat": 11}]})[0]["code"] == "REPEAT_LIMIT_EXCEEDED"


def test_controlled_action_repeat_is_honored_by_execution_engine():
    actions = _phase_action_steps([{"action_code": "get_clock", "repeat": 3, "parameters": {"detail": "brief"}}])
    assert len(actions) == 3
    assert actions == [
        {"action_code": "get_clock", "parameters": {"detail": "brief"}},
        {"action_code": "get_clock", "parameters": {"detail": "brief"}},
        {"action_code": "get_clock", "parameters": {"detail": "brief"}},
    ]


def test_controlled_branch_has_bounded_condition_and_selected_path():
    branch = {
        "type": "branch",
        "condition": {
            "source": "variables",
            "field": "mode",
            "operator": "equals",
            "value": "safe",
        },
        "then": [{"action_code": "get_clock"}],
        "else": [{"action_code": "get_version"}],
    }
    assert validate_controlled_phases({"execute": [branch]}) == []
    assert select_controlled_steps([branch], variables={"mode": "safe"}) == [{"action_code": "get_clock"}]
    assert select_controlled_steps([branch], variables={"mode": "change"}) == [{"action_code": "get_version"}]


def test_controlled_branch_rejects_unsafe_or_unsupported_steps():
    unsafe_device_field = {
        "type": "branch",
        "condition": {"source": "device", "field": "password", "operator": "exists"},
        "then": [{"action_code": "get_clock"}],
    }
    errors = validate_controlled_phases({"execute": [unsafe_device_field, {"type": "unsupported"}]})
    assert {item["code"] for item in errors} == {"UNSAFE_DEVICE_CONDITION_FIELD", "UNSUPPORTED_STEP_TYPE"}


def test_controlled_approval_steps_are_top_level_and_pre_execute_only():
    approval = {
        "type": "approval",
        "title": "变更审批",
        "message": "请确认窗口和回滚方案",
        "required_role": "Administrator",
    }
    phases = {"pre_check": [approval], "execute": [{**approval, "title": "执行审批"}]}
    assert validate_controlled_phases(phases) == []
    assert extract_approval_steps(phases) == [
        {
            "step_path": "phases.pre_check[0]",
            "title": "变更审批",
            "message": "请确认窗口和回滚方案",
            "required_role": "Administrator",
        },
        {
            "step_path": "phases.execute[0]",
            "title": "执行审批",
            "message": "请确认窗口和回滚方案",
            "required_role": "Administrator",
        },
    ]

    nested = {
        "type": "branch",
        "condition": {"source": "variables", "field": "mode", "operator": "equals", "value": "change"},
        "then": [approval],
    }
    errors = validate_controlled_phases({"post_check": [approval], "execute": [nested]})
    assert {item["code"] for item in errors} == {"APPROVAL_PHASE_UNSUPPORTED", "APPROVAL_STEP_MUST_BE_TOP_LEVEL"}
    errors = validate_controlled_phases({"execute": [{**approval, "unexpected": True}]})
    assert errors == [{"path": "phases.execute[0]", "code": "INVALID_APPROVAL_FIELDS"}]


def test_playbook_execution_approval_gate_is_scoped_and_starts_after_all_decisions(isolated_db):
    phases = {
        "pre_check": [{
            "type": "approval",
            "title": "变更审批",
            "message": "确认变更窗口",
        }],
        "execute": [{
            "type": "approval",
            "title": "执行审批",
            "message": "确认开始执行",
        }],
    }
    requester = {"id": "requester-1", "username": "requester", "role": "Operator", "tenant_id": "tenant-1"}
    approver = {"id": "approver-1", "username": "approver", "role": "Administrator", "tenant_id": "tenant-1"}
    execution_id = "approval-execution-1"
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO playbook_executions (id, tenant_id, status, commit_confirmed_ttl) VALUES (?, ?, ?, ?)",
            (execution_id, "tenant-1", "awaiting_approval", 120),
        )
        approvals = create_execution_approvals(conn, execution_id, phases, requester)
        conn.commit()
    finally:
        conn.close()

    assert len(approvals) == 2
    assert [item["status"] for item in list_execution_approvals(execution_id, requester)] == ["PENDING", "PENDING"]
    with pytest.raises(PlaybookApprovalError) as scope_error:
        list_execution_approvals(execution_id, {**requester, "tenant_id": "tenant-2"})
    assert scope_error.value.code == "RESOURCE_SCOPE_DENIED"

    first = decide_execution_approval(execution_id, approvals[0]["id"], "APPROVED", approver)
    assert first["should_start"] is False
    second = decide_execution_approval(execution_id, approvals[1]["id"], "APPROVED", approver)
    assert second["should_start"] is True
    assert second["execution"]["status"] == "pending"
    assert execution_start_payload({
        "id": execution_id,
        "device_ids": '["device-1"]',
        "variables": "{}",
        "phases_json": "{}",
        "dry_run": 0,
        "concurrency": 2,
        "platform": "cisco_ios",
        "commit_confirmed_ttl": 120,
    })["commit_confirmed_ttl"] == 120


def test_playbook_execution_approval_rejects_self_approval_and_blocks_execution(isolated_db):
    phases = {"execute": [{
        "type": "approval",
        "title": "执行审批",
        "message": "确认开始执行",
    }]}
    requester = {"id": "admin-requester", "username": "admin-requester", "role": "Administrator", "tenant_id": "tenant-1"}
    execution_id = "approval-execution-2"
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO playbook_executions (id, tenant_id, status) VALUES (?, ?, ?)",
            (execution_id, "tenant-1", "awaiting_approval"),
        )
        approvals = create_execution_approvals(conn, execution_id, phases, requester)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(PlaybookApprovalError) as self_approval:
        decide_execution_approval(execution_id, approvals[0]["id"], "APPROVED", requester)
    assert self_approval.value.code == "SELF_APPROVAL_FORBIDDEN"

    reviewer = {"id": "reviewer-2", "username": "reviewer", "role": "Administrator", "tenant_id": "tenant-1"}
    rejected = decide_execution_approval(execution_id, approvals[0]["id"], "REJECTED", reviewer, "窗口未确认")
    assert rejected["should_start"] is False
    assert rejected["execution"]["status"] == "approval_rejected"


def test_execute_playbook_enters_approval_gate_without_starting_engine(isolated_db, monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    monkeypatch.setattr("api.playbooks.routes.log_audit_event", lambda **_: None)
    scheduled = []
    monkeypatch.setattr("api.playbooks.routes.asyncio.create_task", lambda coroutine: scheduled.append(coroutine))
    user = {"id": "queue-author", "username": "queue-author", "role": "Operator", "tenant_id": "tenant-1"}
    device_id = "approval-queue-device"
    conn = isolated_db["module"].get_db_connection()
    try:
        existing_columns = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'playbook_executions'"
            ).fetchall()
        }
        required_columns = {
            "scenario_id": "TEXT",
            "scenario_name": "TEXT",
            "platform": "TEXT",
            "variables": "TEXT DEFAULT '{}'",
            "dry_run": "INTEGER DEFAULT 0",
            "author": "TEXT DEFAULT ''",
            "concurrency": "INTEGER DEFAULT 1",
        }
        for name, definition in required_columns.items():
            if name not in existing_columns:
                conn.execute(f"ALTER TABLE playbook_executions ADD COLUMN {name} {definition}")
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, tenant_id, site,
                device_group_id, platform_source, platform_locked)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (device_id, device_id, "192.0.2.20", "cisco_ios", "active", "tenant-1", "site-a", "group-a", "MANUAL", 0),
        )
        conn.commit()
    finally:
        conn.close()

    request = Request({
        "type": "http", "method": "POST", "path": "/api/playbooks/execute",
        "headers": [], "query_string": b"", "scheme": "http",
        "client": ("127.0.0.1", 1234), "server": ("localhost", 80),
    })
    result = asyncio.run(execute_playbook(
        request,
        {
            "name": "Approval-gated execution",
            "device_ids": [device_id],
            "variables": {"ticket": "CHG-42"},
            "dry_run": False,
            "concurrency": 2,
            "commit_confirmed_ttl": 120,
            "phases": {"execute": [{
                "type": "approval",
                "title": "变更审批",
                "message": "确认窗口",
            }]},
        },
        user,
    ))
    assert result["status"] == "awaiting_approval"
    assert len(result["approval_ids"]) == 1
    assert scheduled == []

    conn = isolated_db["module"].get_db_connection()
    try:
        execution = conn.execute(
            "SELECT status, commit_confirmed_ttl, device_ids FROM playbook_executions WHERE id = ?",
            (result["execution_id"],),
        ).fetchone()
        assert execution["status"] == "awaiting_approval"
        assert execution["commit_confirmed_ttl"] == 120
        assert json.loads(execution["device_ids"]) == [device_id]
        approval = conn.execute(
            "SELECT status, step_path FROM playbook_execution_approvals WHERE execution_id = ?",
            (result["execution_id"],),
        ).fetchone()
        assert dict(approval) == {"status": "PENDING", "step_path": "phases.execute[0]"}
    finally:
        conn.close()


def test_controlled_notification_step_rejects_destinations_and_accepts_bounded_content():
    notification = {
        "type": "notification",
        "title": "变更完成 {{ ticket }}",
        "message": "设备 {{ hostname }} 已完成校验",
        "severity": "info",
    }
    assert validate_controlled_phases({"post_check": [notification]}) == []
    errors = validate_controlled_phases({"post_check": [{**notification, "webhook_url": "https://example.invalid"}]})
    assert errors == [{"path": "phases.post_check[0]", "code": "INVALID_NOTIFICATION_FIELDS"}]


def test_notification_step_is_tenant_scoped_and_filters_secret_variables(monkeypatch):
    calls = []
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    monkeypatch.setattr(
        "services.notification_service.dispatch_to_tenant_users",
        lambda alert, tenant_id: calls.append((alert, tenant_id)) or [{"platform": "feishu", "success": True}],
    )
    monkeypatch.setattr("services.audit_service.log_audit_event", lambda **_: "audit-1")
    monkeypatch.setattr("api.playbooks.engine.ws_manager.emit", lambda *args, **kwargs: asyncio.sleep(0))

    result = asyncio.run(_execute_notification_steps(
        "execution-1",
        {"id": "device-1", "hostname": "edge-1", "ip_address": "192.0.2.1", "tenant_id": "tenant-1"},
        [{"title": "{{ ticket }}", "message": "{{ password }} / {{ hostname }}", "severity": "info"}],
        variables={"ticket": "CHG-1", "password": "do-not-send", "hostname": "edge-override"},
        dry_run=False,
        actor={"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"},
    ))
    assert result["notification_success"] is True
    assert calls[0][1] == "tenant-1"
    assert "do-not-send" not in calls[0][0]["message"]
    assert "edge-override" in calls[0][0]["message"]


def test_bound_devices_preserve_controlled_branch_and_notification_steps():
    branch = {
        "type": "branch",
        "condition": {"source": "variables", "field": "mode", "operator": "equals", "value": "safe"},
        "then": [{"action_code": "get_clock"}],
    }
    notification = {"type": "notification", "title": "Done", "message": "Completed", "severity": "info"}
    bound, rejected = _bind_legacy_phase_commands(
        {"id": "device-1", "platform_profile_id": "profile-1"},
        {"execute": [branch, notification]},
    )
    assert rejected == []
    assert bound["execute"] == [branch, notification]


def test_controlled_validation_covers_platform_phase_catalogs():
    errors = validate_controlled_phases({"cisco_ios": {"execute": ["show version"]}})
    assert errors == [{"path": "phases.cisco_ios.execute[0]", "code": "RAW_COMMAND_DISABLED"}]


def test_repeat_counts_toward_total_playbook_step_limit():
    steps = [{"action_code": "get_clock", "repeat": 10}] * 21
    assert validate_controlled_phases({"execute": steps})[-1]["code"] == "PLAYBOOK_STEP_LIMIT_EXCEEDED"


def test_playbook_execution_limits_reject_unsafe_request_shapes():
    normalized = _validate_execution_limits(["device-1"], {"ticket": "CHG-1"}, 4, True, 0)
    assert normalized == (["device-1"], {"ticket": "CHG-1"}, 4, True, 0)
    with pytest.raises(HTTPException) as duplicate:
        _validate_execution_limits(["device-1", "device-1"], {}, 1, True, 0)
    assert duplicate.value.detail["code"] == "DUPLICATE_DEVICE_TARGET"
    with pytest.raises(HTTPException) as concurrency:
        _validate_execution_limits(["device-1"], {}, 21, False, 0)
    assert concurrency.value.detail["code"] == "CONCURRENCY_LIMIT_EXCEEDED"


def test_playbook_execution_scope_rejects_cross_tenant_reads(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO playbook_executions (id, tenant_id) VALUES (?, ?)",
            ("execution-1", "tenant-1"),
        )
        conn.commit()
        owner = {"id": "owner-1", "username": "owner", "role": "Operator", "tenant_id": "tenant-1"}
        assert _assert_execution_scope(conn, "execution-1", owner)["tenant_id"] == "tenant-1"

        other_tenant = {"id": "other-1", "username": "other", "role": "Operator", "tenant_id": "tenant-2"}
        with pytest.raises(HTTPException) as error:
            _assert_execution_scope(conn, "execution-1", other_tenant)
        assert error.value.status_code == 403
    finally:
        conn.close()


def test_site_and_device_group_scopes_are_enforced_for_playbook_read_and_execute(isolated_db, monkeypatch):
    monkeypatch.setattr("services.access_scope_service.log_audit_event", lambda **_: None)
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT UNIQUE, password TEXT,
                role TEXT, status TEXT, last_login TEXT, avatar_url TEXT, created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS user_resource_scopes (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, resource_type TEXT NOT NULL,
                scope_type TEXT NOT NULL, scope_id TEXT NOT NULL DEFAULT '',
                actions_json TEXT DEFAULT '[]', created_at TEXT NOT NULL
            )"""
        )
        conn.execute("INSERT INTO users (id, username, role, status) VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING", ("scope-user", "scope-user", "Operator", "active"))
        first_device = "scope-device-a"
        second_device = "scope-device-b"
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, tenant_id, site,
                device_group_id, platform_source, platform_locked)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (first_device, first_device, "192.0.2.10", "unknown", "active", "tenant-1", "site-a", "group-a", "LEGACY", 0),
        )
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, tenant_id, site,
                device_group_id, platform_source, platform_locked)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (second_device, second_device, "192.0.2.11", "unknown", "active", "tenant-1", "site-b", "group-b", "LEGACY", 0),
        )
        conn.execute("UPDATE devices SET site_id = ?, device_group_id = ? WHERE id = ?", ("site-a", "group-a", first_device))
        conn.execute("UPDATE devices SET site_id = ?, device_group_id = ? WHERE id = ?", ("site-b", "group-b", second_device))
        conn.commit()
    finally:
        conn.close()

    user = {"id": "scope-user", "username": "scope-user", "role": "Operator", "tenant_id": "tenant-1"}
    replace_user_scopes(
        "scope-user",
        [
            {"resource_type": "playbook", "scope_type": "site", "scope_id": "site-a", "actions": ["view"]},
            {"resource_type": "playbook", "scope_type": "device_group", "scope_id": "group-a", "actions": ["execute"]},
            {"resource_type": "platform", "scope_type": "site", "scope_id": "site-a", "actions": ["bind_device"]},
        ],
        changed_by="admin",
    )
    assert authorize_resource(user, "playbook", "view", tenant_id="tenant-1", site_id="site-a", device_group_id="group-a") is True
    assert authorize_resource(user, "playbook", "view", tenant_id="tenant-1", site_id="site-b", device_group_id="group-b") is False
    assert authorize_resource(user, "playbook", "execute", tenant_id="tenant-1", site_id="site-a", device_group_id="group-a") is True
    assert authorize_resource(user, "playbook", "execute", tenant_id="tenant-1", site_id="site-a", device_group_id="group-b") is False
    assert authorize_resource(user, "platform", "bind_device", tenant_id="tenant-1", site_id="site-a", device_group_id="group-a") is True

    conn = isolated_db["module"].get_db_connection()
    try:
        assert _assert_playbook_device_scope(conn, [first_device], user)[0]["id"] == first_device
        with pytest.raises(HTTPException) as device_scope:
            _assert_playbook_device_scope(conn, [second_device], user)
        assert device_scope.value.detail["code"] == "RESOURCE_SCOPE_DENIED"
        conn.execute(
            "INSERT INTO playbook_executions (id, tenant_id, device_ids, status) VALUES (?, ?, ?, ?)",
            ("scope-execution", "tenant-1", json.dumps([first_device, second_device]), "completed"),
        )
        conn.commit()
        with pytest.raises(HTTPException) as execution_scope:
            _assert_execution_scope(conn, "scope-execution", user)
        assert execution_scope.value.detail["code"] == "RESOURCE_SCOPE_DENIED"
    finally:
        conn.close()


def test_playbook_device_scope_checks_tenant_site_and_device_group(isolated_db, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    try:
        existing_columns = {
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'devices'"
            ).fetchall()
        }
        if "site_id" not in existing_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN site_id TEXT DEFAULT ''")
        if "site" not in existing_columns:
            conn.execute("ALTER TABLE devices ADD COLUMN site TEXT DEFAULT ''")
        conn.execute(
            "INSERT INTO devices (id, tenant_id, site_id, site, device_group_id) VALUES (?, ?, ?, ?, ?)",
            ("device-scope-1", "tenant-1", "site-a", "Site A", "group-a"),
        )
        conn.commit()
        calls = []

        def allow(_user, resource_type, action, **scope):
            calls.append((resource_type, action, scope))
            return True

        monkeypatch.setattr("api.playbooks.routes.authorize_resource", allow)
        user = {"id": "operator-1", "role": "Operator", "tenant_id": "tenant-1"}
        rows = _assert_playbook_device_scope(conn, ["device-scope-1"], user)
        assert rows[0]["id"] == "device-scope-1"
        assert {item[0] for item in calls} == {"playbook", "command"}
        assert all(item[2] == {
            "tenant_id": "tenant-1",
            "site_id": "site-a",
            "device_group_id": "group-a",
        } for item in calls)

        with pytest.raises(HTTPException) as error:
            _assert_playbook_device_scope(conn, ["device-scope-1"], {**user, "tenant_id": "tenant-2"})
        assert error.value.status_code == 403
    finally:
        conn.close()


def test_playbook_output_is_encrypted_and_round_trips(monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "test-playbook-output-key")
    monkeypatch.setattr(crypto, "_aes_key", None)

    ciphertext, legacy, expiry, encrypted = protect_output({"output": "secret", "records": [{"id": 1}]})

    assert encrypted is True
    assert ciphertext and ciphertext.startswith("enc:v2:")
    assert legacy == "{}"
    assert expiry
    assert load_output(ciphertext, legacy) == {"output": "secret", "records": [{"id": 1}]}


def test_playbook_output_fails_closed_without_encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "change-me-to-a-random-secret")
    monkeypatch.setattr(crypto, "_aes_key", None)

    ciphertext, legacy, expiry, encrypted = protect_output({"output": "secret"})

    assert encrypted is False
    assert ciphertext is None
    assert legacy == "{}"
    assert expiry is None


def test_historical_plaintext_playbook_output_is_rejected():
    with pytest.raises(PlaybookOutputError, match="plaintext"):
        load_output(None, '{"output":"secret"}')


def test_expired_playbook_output_is_removed(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            "INSERT INTO playbook_executions "
            "(id, results_json, results_encrypted, raw_output_expires_at) "
            "VALUES (?, ?, ?, ?)",
            ("expired-execution", '{"output":"secret"}', "enc:v2:stale", "2000-01-01T00:00:00+00:00"),
        )
        conn.commit()
        assert cleanup_expired_playbook_outputs(conn) == 1
        row = conn.execute(
            "SELECT results_json, results_encrypted, raw_output_expires_at "
            "FROM playbook_executions WHERE id = ?",
            ("expired-execution",),
        ).fetchone()
        assert dict(row) == {
            "results_json": "{}",
            "results_encrypted": None,
            "raw_output_expires_at": None,
        }
    finally:
        conn.close()
