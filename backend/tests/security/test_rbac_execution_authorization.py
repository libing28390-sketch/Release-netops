from __future__ import annotations

import base64
import hashlib
import hmac
import json
import struct
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException


def test_normal_execution_credentials_never_receive_enable_secret(monkeypatch):
    from api import automation

    monkeypatch.setattr(
        automation,
        "resolve_device_credentials",
        lambda _device: {
            "normal_username": "reader",
            "normal_password": "normal-pass",
            "admin_username": "writer",
            "admin_password": "admin-pass",
            "enable_password": "enable-secret",
        },
    )

    normal = automation._resolve_execution_credentials({}, "normal")
    privileged = automation._resolve_execution_credentials({}, "admin")

    assert normal == {
        "username": "reader",
        "password": "normal-pass",
        "enable_password": "",
        "resolved_role": "normal",
    }
    assert privileged["enable_password"] == "enable-secret"


def test_platform_actions_deny_tenantless_device_for_tenant_admin():
    from services.platform_registry_service import PlatformRegistryError, _authorize_action_device

    tenant_admin = {
        "id": "tenant-admin-id",
        "role": "Administrator",
        "role_profile": "Tenant Administrator",
        "tenant_id": "tenant-a",
    }

    with pytest.raises(PlatformRegistryError) as error:
        _authorize_action_device(tenant_admin, {"id": "legacy-device", "tenant_id": ""})
    assert error.value.status_code == 403


def test_enable_secret_requires_credential_use_for_user_actions():
    from services.platform_registry_service import _enable_secret_for_action

    operator = {"id": "operator-id", "role": "Operator", "tenant_id": "tenant-a"}
    device = {"tenant_id": "tenant-a", "site_id": "site-a", "device_group_id": "group-a"}

    assert _enable_secret_for_action(operator, device, "enable-secret") == ""
    assert _enable_secret_for_action(
        {**operator, "_trusted_service_identity": "collector"}, device, "enable-secret",
    ) == "enable-secret"


def test_instant_execution_history_stores_redacted_output_encrypted(isolated_db):
    from api.devices import _record_instant_execution
    from services.playbook_output_service import load_output

    _record_instant_execution(
        "sensitive-output-device",
        "RBAC output test",
        ["show running-config | include password DemoPassword123"],
        "completed",
        output="username admin password DemoPassword123",
        device_info={"hostname": "test-device", "ip_address": "192.0.2.12"},
    )

    conn = isolated_db["module"].get_db_connection()
    try:
        row = conn.execute(
            "SELECT phases_json, phases_encrypted FROM execution_device_results "
            "WHERE device_id = ? ORDER BY started_at DESC LIMIT 1",
            ("sensitive-output-device",),
        ).fetchone()
    finally:
        conn.close()

    assert row
    assert row["phases_json"] == "{}"
    assert row["phases_encrypted"] and "DemoPassword123" not in row["phases_encrypted"]
    stored = load_output(row["phases_encrypted"], row["phases_json"])
    assert "DemoPassword123" not in json.dumps(stored)
    assert "<REDACTED>" in json.dumps(stored)


def test_approval_mfa_step_is_one_time_and_failures_are_shared(isolated_db):
    from services import config_approval_service as approval

    conn = isolated_db["module"].get_db_connection()
    now = datetime(2026, 10, 11, 4, 0, 0, tzinfo=timezone.utc)
    secret = "JBSWY3DPEHPK3PXP"
    step = int(now.timestamp() // 30)
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    code = f"{value % 1_000_000:06d}"
    try:
        assert approval._matching_totp_step(secret, code, now) == step
        assert approval._consume_mfa_approver_step(conn, "approver-replay-test", step, now)
        assert not approval._consume_mfa_approver_step(conn, "approver-replay-test", step, now)

        attempts = 0
        for _ in range(approval.MAX_MFA_APPROVER_FAILURES):
            state = approval._mfa_approver_failure_state(conn, "approver-lock-test", now)
            assert state == attempts
            approval._record_mfa_approver_failure(conn, "approver-lock-test", state, now)
            attempts += 1
        conn.commit()
        assert approval._mfa_approver_failure_state(conn, "approver-lock-test", now) is None
    finally:
        conn.close()


def test_m0281_does_not_guess_case_insensitive_job_or_script_owners(isolated_db, make_user):
    from database.migrations import m0281_rbac_execution_authorization as migration

    upper = make_user("Alice", role="Administrator")
    lower = make_user("alice", role="Administrator")
    conn = isolated_db["module"].get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("UPDATE users SET tenant_id = 'tenant-a' WHERE id = ?", (upper["user_id"],))
        conn.execute("UPDATE users SET tenant_id = 'tenant-b' WHERE id = ?", (lower["user_id"],))
        for job_id, created_by in (("owner-exact", "Alice"), ("owner-ambiguous", "ALICE")):
            conn.execute(
                """INSERT INTO scheduled_jobs
                   (id, name, job_type, action_type, cron_expr, device_scope, enabled,
                    status, created_by, created_at, updated_at, authorization_mode)
                   VALUES (?, ?, 'cron', 'inspection', '* * * * *', 'all', 1,
                           'pending', ?, ?, ?, 'legacy')""",
                (job_id, job_id, created_by, now, now),
            )
        conn.execute(
            """INSERT INTO scripts (id, name, content, author, status, created_at, updated_at)
               VALUES ('owner-ambiguous-script', 'legacy script', 'show version', 'ALICE', 'released', ?, ?)""",
            (now, now),
        )
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()

        exact = conn.execute(
            "SELECT created_by_id, tenant_id, enabled, status FROM scheduled_jobs WHERE id = 'owner-exact'"
        ).fetchone()
        ambiguous = conn.execute(
            "SELECT created_by_id, tenant_id, enabled, status FROM scheduled_jobs WHERE id = 'owner-ambiguous'"
        ).fetchone()
        script = conn.execute(
            "SELECT created_by_id, tenant_id FROM scripts WHERE id = 'owner-ambiguous-script'"
        ).fetchone()
    finally:
        conn.close()

    assert exact["created_by_id"] == upper["user_id"]
    assert exact["tenant_id"] == "tenant-a"
    assert exact["enabled"] == 0
    assert exact["status"] == "reauthorization_required"
    assert ambiguous["created_by_id"] == ""
    assert ambiguous["tenant_id"] == ""
    assert ambiguous["enabled"] == 0
    assert script["created_by_id"] == ""
    assert script["tenant_id"] == ""


def test_m0281_reduces_legacy_non_admin_profiles_to_scoped_requester(isolated_db, make_user):
    from core.rbac import resource_action_allowed
    from database.migrations import m0281_rbac_execution_authorization as migration

    legacy = make_user("legacy-automation-user", role="Operator")
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """UPDATE users
                  SET tenant_id = 'tenant-legacy', role_profile = 'System Administrator', scope_mode = 'legacy'
                WHERE id = ?""",
            (legacy["user_id"],),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes
               (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES ('legacy-global-execute', ?, 'command', 'global', '', '[\"execute\"]', '2026-01-01')""",
            (legacy["user_id"],),
        )
        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        user = conn.execute(
            "SELECT role, role_profile, tenant_id, scope_mode FROM users WHERE id = ?",
            (legacy["user_id"],),
        ).fetchone()
        scopes = conn.execute(
            """SELECT resource_type, scope_type, scope_id, actions_json
                 FROM user_resource_scopes WHERE user_id = ? ORDER BY resource_type""",
            (legacy["user_id"],),
        ).fetchall()
        legacy_snapshot = conn.execute(
            """SELECT previous_role, previous_role_profile, previous_scopes_json
                 FROM legacy_user_rbac_assignments WHERE user_id = ?""",
            (legacy["user_id"],),
        ).fetchone()
    finally:
        conn.close()

    migrated = dict(user)
    assert migrated == {
        "role": "Viewer",
        "role_profile": "Change Requester",
        "tenant_id": "tenant-legacy",
        "scope_mode": "restricted",
    }
    assert [row["resource_type"] for row in scopes] == ["change_order", "pam"]
    assert all(row["scope_type"] == "tenant" and row["scope_id"] == "tenant-legacy" for row in scopes)
    assert legacy_snapshot["previous_role"] == "Operator"
    assert legacy_snapshot["previous_role_profile"] == "System Administrator"
    assert "legacy-global-execute" in legacy_snapshot["previous_scopes_json"]
    assert not resource_action_allowed(migrated, "command", "execute")
    assert resource_action_allowed(migrated, "pam", "create_change")


@pytest.mark.parametrize("legacy_profile", ["System Administrator", "Automation Operator", "Platform Maintainer"])
def test_viewer_profile_cannot_retain_legacy_privileged_capabilities(legacy_profile):
    from core.rbac import resource_action_allowed

    user = {"role": "Viewer", "role_profile": legacy_profile, "scope_mode": "legacy"}

    assert not resource_action_allowed(user, "command", "execute")
    assert not resource_action_allowed(user, "platform", "publish")
