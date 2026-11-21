"""Synthetic RBAC branch evidence. Every persistence/driver call is mocked."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock, patch

EVIDENCE_DIR = Path(__file__).resolve().parent
WORKSPACE = EVIDENCE_DIR.parents[2]
sys.path[:0] = [str(WORKSPACE / "backend"), str(WORKSPACE)]
os.environ["CREDENTIAL_ENCRYPTION_KEY"] = "audit-only-synthetic-encryption-key"
os.environ["ENVIRONMENT"] = "testing"


class Cursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, selector=None):
        self.selector = selector or (lambda *_: Cursor())
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))
        return self.selector(statement, parameters)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def main():
    from starlette.requests import Request
    import database.core as database_core
    from core import rbac
    from api import automation, devices
    from services import access_scope_service, audit_service, operational_data_service, scheduler_service, vault_service

    evidence = []
    request = Request({
        "type": "http", "method": "POST", "path": "/api/automation/execute",
        "headers": [], "client": ("127.0.0.1", 0),
    })
    user = {
        "id": "audit-user", "user_id": "audit-user", "username": "audit-user",
        "role": "Operator", "role_profile": "Automation Operator", "tenant_id": "audit-tenant-a",
    }
    device = {
        "id": "audit-device", "hostname": "synthetic-server", "ip_address": "192.0.2.1",
        "platform": "linux", "device_category": "server", "platform_profile_id": None,
        "tenant_id": "audit-tenant-b", "is_active": 1,
    }
    harmless_script = "#!/bin/sh\nprintf audit-marker"

    def automation_rows(statement, _):
        if statement.startswith("SELECT platform,"):
            return Cursor(rows=[device])
        if statement.startswith("SELECT * FROM devices"):
            return Cursor(row=device)
        return Cursor()

    executor = Mock()
    executor.execute_commands.return_value = [{"success": True, "output": "synthetic-only"}]
    consume = Mock(side_effect=AssertionError("Approval consumption was attempted"))
    with (
        patch.object(automation, "get_db_connection", return_value=Connection(automation_rows)),
        patch.object(automation, "AutomationService", return_value=executor),
        patch.object(automation, "consume_approval", consume),
        patch.object(automation, "_resolve_execution_credentials", return_value={
            "username": "synthetic-normal", "password": "synthetic-only", "enable_password": "",
        }),
        patch.object(automation, "parse_device_cli_output", return_value=None),
        patch.object(automation, "_record_instant_execution"),
    ):
        result = asyncio.run(automation.execute_task(request, {
            "device_ids": [device["id"]], "command": harmless_script, "isConfig": True,
        }, user))
    assert result["status"] == "success"
    assert executor.execute_commands.call_args.kwargs["is_config"] is False
    assert consume.call_count == 0
    evidence.append({
        "id": "R07", "reproduced": True,
        "behavior": "Operator shell request reaches mocked execution with is_config=False and no approval consumption, even when isConfig=True",
        "limit": "Direct route call with synthetic identity/device; global HTTP guard tested separately; driver, credentials and history mocked",
    })

    # The collector is mocked. This benign string demonstrates shell syntax is
    # admitted by a prefix test, without executing any shell expression.
    benign_compound_command = "pwd ; printf audit-marker"
    collector = Mock(return_value={"synthetic": True})
    with (
        patch.object(devices, "get_db_connection", return_value=Connection(lambda *_: Cursor(row=device))),
        patch.object(devices, "collect_custom_command_data", collector),
        patch.object(devices, "_record_instant_execution"),
    ):
        devices.collect_device_parsed_command(device["id"], {"command": benign_compound_command, "auth_role": "admin"})
    assert collector.call_args.kwargs["command"] == benign_compound_command
    assert collector.call_args.kwargs["auth_role"] == "admin"
    evidence.append({
        "id": "R08", "reproduced": True,
        "behavior": "Parsed-command read-prefix gate accepts a compound shell expression and passes client-selected admin auth_role to the collector",
        "limit": "Benign printf expression only; actual collector mocked; bound-platform downstream controls not bypassed by this probe",
    })

    with patch.object(database_core, "get_db_connection", return_value=Connection()):
        tenantless_allowed = rbac.authorize_resource(
            {**user, "tenant_id": None}, "playbook", "execute", tenant_id="audit-tenant-b",
        )
    assert tenantless_allowed
    evidence.append({
        "id": "R09", "reproduced": True,
        "behavior": "Tenantless Operator with a permitted profile and no scope rows is allowed against a tenant-bearing resource",
        "limit": "Central predicate only; empty scopes mocked; no other tenant data was read",
    })

    global_admin_allowed = rbac.authorize_resource(
        {**user, "role": "Administrator", "role_profile": "System Administrator"},
        "playbook", "execute", tenant_id="audit-tenant-b",
    )
    assert global_admin_allowed
    evidence.append({
        "id": "R10", "reproduced": True,
        "behavior": "Coarse Administrator bypasses target tenant comparison",
        "limit": "Documents the current global-admin policy; a defect only if the account is intended to be a tenant administrator",
    })

    scope_connection = Connection(lambda statement, _: (
        Cursor(row={"id": user["id"], "username": user["username"]})
        if statement.startswith("SELECT id, username FROM users") else Cursor()
    ))
    with (
        patch.object(access_scope_service, "get_db_connection", return_value=scope_connection),
        patch.object(access_scope_service, "list_user_scopes", return_value=[]),
        patch.object(access_scope_service, "log_audit_event"),
    ):
        saved = access_scope_service.replace_user_scopes(user["id"], [{
            "scope_type": "site", "scope_id": "audit-site", "resource_type": "playbok",
            "actions": ["execute"],
        }], changed_by="audit-admin")
    assert saved[0]["resource_type"] == "playbok"
    assert any("INSERT INTO user_resource_scopes" in statement for statement, _ in scope_connection.statements)
    evidence.append({
        "id": "R11", "reproduced": True,
        "behavior": "Scope service accepts and attempts to persist an unknown resource name (playbok)",
        "limit": "All SQL calls mocked; persistence admission, not a change to actual user scopes",
    })

    job = {
        "id": "audit-job", "name": "Synthetic audit job", "enabled": 1, "status": "approved",
        "action_type": "script_run", "job_type": "cron", "device_scope": "composite",
        "device_filter": "invalid-json", "script_id": "audit-draft-script", "commands": "",
        "is_config": 0, "use_admin_creds": 1, "created_by": "audit-disabled-owner",
    }
    script = {"name": "Synthetic mutable draft", "content": "printf audit-marker", "script_type": "cli"}

    def scheduler_rows(statement, _):
        if statement.startswith("SELECT * FROM scheduled_jobs"):
            return Cursor(row=job)
        if statement.startswith("SELECT id FROM devices"):
            return Cursor(rows=[{"id": device["id"]}])
        if statement.startswith("SELECT name, content, script_type FROM scripts"):
            return Cursor(row=script)
        if statement.startswith("SELECT * FROM devices"):
            return Cursor(rows=[device])
        return Cursor()

    schedule_connection = Connection(scheduler_rows)
    schedule_executor = Mock()
    schedule_executor.execute_commands.return_value = [{"success": True, "output": "synthetic-only"}]
    with (
        patch.object(scheduler_service, "get_db_connection", return_value=schedule_connection),
        patch.object(scheduler_service, "AutomationService", return_value=schedule_executor),
        patch.object(scheduler_service, "resolve_device_credentials", return_value={
            "normal_username": "synthetic-normal", "normal_password": "synthetic-only",
            "admin_username": "synthetic-privileged", "admin_password": "synthetic-only", "enable_password": "",
        }),
        patch.object(scheduler_service, "notify_job_failure", AsyncMock()),
    ):
        asyncio.run(scheduler_service.run_scheduled_automation_job(job["id"]))
    assert schedule_executor.execute_commands.call_count == 1
    assert schedule_executor.execute_commands.call_args.args[0]["username"] == "synthetic-privileged"
    queries = [statement for statement, _ in schedule_connection.statements]
    device_query = next(statement for statement in queries if statement.startswith("SELECT id FROM devices"))
    assert "tenant_id" not in device_query and "site =" not in device_query
    assert not any("FROM users" in statement for statement in queries)
    assert any("SELECT name, content, script_type FROM scripts" in statement for statement in queries)
    evidence.append({
        "id": "R12", "reproduced": True,
        "behavior": "Invalid composite filter falls back to active-device universe; runner reads current script without publication fields, chooses privileged credentials, and never queries the creator identity",
        "limit": "Entire persistence/credential/driver/notification path mocked; shows runner checks, not a real disabled account or actual administrator credential use",
    })

    sanitized = audit_service.redact_audit_value({"changes": {
        "approval_token": "synthetic-token", "approval_code": "synthetic-otp",
    }})
    assert sanitized["changes"]["approval_token"] == "[REDACTED]"
    assert sanitized["changes"]["approval_code"] == "synthetic-otp"
    evidence.append({
        "id": "R13", "reproduced": True,
        "behavior": "Audit sanitizer redacts approval_token but keeps approval_code",
        "limit": "Pure function with synthetic values; no log or database was modified",
    })

    with (
        patch.object(vault_service, "resolve_device_credentials", return_value={
            "normal_username": "synthetic-normal", "normal_password": "synthetic-only",
            "admin_username": "synthetic-privileged", "admin_password": "synthetic-only", "enable_password": "",
        }),
        patch.object(operational_data_service, "build_netmiko_compatibility_kwargs", return_value={}),
    ):
        parameters = operational_data_service._build_connection_params(device, auth_role="admin")
    assert parameters["username"] == "synthetic-privileged"
    evidence.append({
        "id": "R14", "reproduced": True,
        "behavior": "Operational collector credential helper selects the admin pair for client-selected admin auth_role; helper has no actor input",
        "limit": "Synthetic vault and compatibility options; no SSH client was constructed; read together with the unauthorised selection route evidence",
    })

    result_path = EVIDENCE_DIR / "additional_policy_probes.json"
    result_path.write_text(json.dumps({"policy_probes": evidence}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"probe_count": len(evidence), "evidence": str(result_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
