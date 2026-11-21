"""Read-only RBAC audit evidence with a disposable PostgreSQL test source.

This is an audit harness, not application code. It never enters app lifespan
or connects to devices. All database writes belong to its named test database.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import AsyncMock, Mock, patch

EVIDENCE_DIR = Path(__file__).resolve().parent
WORKSPACE = EVIDENCE_DIR.parents[2]
sys.path[:0] = [str(WORKSPACE / "backend"), str(WORKSPACE)]
os.environ["CREDENTIAL_ENCRYPTION_KEY"] = "audit-only-synthetic-encryption-key"
os.environ["ADMIN_PASSWORD"] = "audit-only-synthetic-admin-password"
os.environ["ENVIRONMENT"] = "testing"

TEST_FILES = [
    "backend/tests/security/test_api_access_boundary.py",
    "backend/tests/security/test_audit_regressions.py",
    "backend/tests/security/test_user_tenant_assignment.py",
    "backend/tests/platform_registry/test_playbook_versions.py",
]


def run_policy_probes() -> list[dict]:
    """Prove narrow branch behavior using synthetic identities and fake I/O."""
    from datetime import datetime, timezone
    from starlette.requests import Request
    from core import rbac
    from api.playbooks import routes
    from services import config_approval_service as approval

    findings: list[dict] = []
    viewer_profile = {
        "id": "audit-user", "user_id": "audit-user", "username": "audit-user",
        "role": "Operator", "role_profile": "Platform Viewer", "tenant_id": "audit-tenant",
    }
    request = Request({
        "type": "http", "method": "POST", "path": "/api/scheduled-jobs",
        "headers": [], "client": ("127.0.0.1", 0),
    })
    with patch.object(rbac, "_get_current_user", return_value=viewer_profile):
        coarse_allowed = rbac.require_role("Operator").dependency(request) is viewer_profile
        resource_allowed = rbac.resource_action_allowed(viewer_profile, "playbook", "execute")
    assert coarse_allowed and not resource_allowed
    findings.append({
        "id": "R01", "reproduced": True,
        "behavior": "Operator gate admits a Platform Viewer profile while resource execute denies it",
        "limit": "Dependency behavior only; no scheduled job was created",
    })

    row = {
        "status": "approved", "scheduled_start": "not-a-timestamp", "scheduled_end": "",
        "command_template_json": json.dumps({"scenario_id": "audit-scenario", "platform": "cisco_ios"}),
    }
    routes._assert_change_order_executable(row, "audit-scenario", "cisco_ios", datetime.now(timezone.utc))
    findings.append({
        "id": "R02", "reproduced": True,
        "behavior": "Change execution helper accepts approved status and an invalid start timestamp",
        "limit": "Helper predicate only; no work order or device execution was started",
    })

    class FakeCursor:
        def __init__(self, user):
            self.user = user

        def fetchone(self):
            return self.user

    class FakeConnection:
        def __init__(self, user=None):
            self.user = user
            self.statements = []

        def execute(self, statement, parameters=None):
            self.statements.append(statement)
            return FakeCursor(self.user)

        def commit(self):
            return None

        def close(self):
            return None

    same_user = {
        "id": "audit-user", "username": "audit-user", "role": "Operator",
        "status": "active", "tenant_id": "audit-tenant",
    }
    with patch.object(approval, "get_db_connection", return_value=FakeConnection(same_user)):
        approver, error = approval._get_approver_for_request(
            "audit-user", "audit-user", "audit-user", "audit-tenant",
        )
    assert error is None and approver["id"] == same_user["id"]
    findings.append({
        "id": "R03", "reproduced": True,
        "behavior": "Config approval candidate validation accepts requester as their own approver",
        "limit": "Synthetic database rows; no notification or MFA factor was sent/used",
    })

    synthetic_token = "audit-probe-token-not-a-real-token"
    approval._pending_approvals[synthetic_token] = {
        "code": "audit-otp", "requester_id": "audit-user", "requester": "audit-user",
        "approval_type": "scheduled_job", "verification_method": "email",
        "created_at": time.time(), "verified": False, "attempts": 0,
        "extra_fields": {"job_id": "job-A", "script_id": "script-A"},
    }
    try:
        valid, error = approval.verify_code(
            synthetic_token, "audit-otp", requester_id="audit-user",
            requester_username="audit-user", expected_approval_type="scheduled_job",
        )
        consumed = approval.consume_approval(
            synthetic_token, requester_id="audit-user", expected_approval_type="scheduled_job",
        )
        assert valid and not error and consumed["extra_fields"]["job_id"] == "job-A"
    finally:
        approval._pending_approvals.pop(synthetic_token, None)
    findings.append({
        "id": "R04", "reproduced": True,
        "behavior": "Approval verify/consume requires requester and type but no job/config digest",
        "limit": "Transient synthetic token; this proves missing binding inputs, not a launched replacement job",
    })

    version = {
        "id": "audit-version", "playbook_id": "audit-scenario", "status": "PUBLISHED",
        "name": "Synthetic high-risk version", "risk": "high",
        "definition": {
            "risk": "high", "platform": "cisco_ios",
            "phases": {"execute": [
                {"type": "approval", "title": "Synthetic approval", "message": "Synthetic hold", "required_role": "Administrator"},
                {"action_code": "get_interfaces", "parameters": {}},
            ]},
        },
    }
    resolver = Mock(side_effect=AssertionError("Change gate was reached"))
    fake_connection = FakeConnection()
    with (
        patch.object(routes, "_call_playbook_version", return_value=version),
        patch.object(routes, "get_db_connection", return_value=fake_connection),
        patch.object(routes, "_assert_playbook_device_scope", return_value=[]),
        patch.object(routes, "_resolve_change_order_for_playbook", resolver),
        patch.object(routes, "_create_playbook_execution_snapshot", return_value=("audit-snapshot", 1, "synthetic-checksum")),
        patch.object(routes, "create_execution_approvals", return_value=[{"id": "audit-approval"}]),
        patch.object(routes, "log_audit_event"),
        patch.object(routes, "invalidate_read_cache"),
    ):
        result = asyncio.run(routes.execute_playbook(
            request, {"playbook_version_id": "audit-version", "device_ids": ["audit-device"]},
            {**viewer_profile, "role_profile": "Automation Operator"},
        ))
    assert resolver.call_count == 0 and result["change_order_number"] is None
    findings.append({
        "id": "R05", "reproduced": True,
        "behavior": "Published version marked high risk reaches approval pause without calling the change-order gate",
        "limit": "Device scope/persistence mocked; phase approval held the engine; no network I/O",
    })

    approver_user = {"id": "audit-approver", "username": "audit-approver", "role": "Administrator"}
    execution = {
        "id": "audit-execution", "author": "audit-requester", "device_ids": '["audit-device"]',
        "variables": '{}', "phases_json": '{"execute": []}', "dry_run": 1, "concurrency": 1,
        "platform": "cisco_ios", "commit_confirmed_ttl": 0,
    }

    async def resume_probe():
        run_mock = AsyncMock()
        with patch.object(routes, "_run_playbook", run_mock):
            routes._resume_approved_execution(execution, approver_user)
            await asyncio.sleep(0)
            assert run_mock.call_args.args[-1] is approver_user

    asyncio.run(resume_probe())
    findings.append({
        "id": "R06", "reproduced": True,
        "behavior": "Approval resume passes approval actor as execution actor, replacing stored requester identity",
        "limit": "Engine replaced with AsyncMock; no credentials were resolved",
    })
    return findings


def main() -> int:
    import database.core as database_core
    from backend.tests import pg_test_utils as pg

    state = pg.capture_database_state()
    target = None
    summary = {"test_files": TEST_FILES, "database_isolation": "dedicated disposable source and shared per-test fixtures"}
    log_path = EVIDENCE_DIR / "pytest.log"
    result_path = EVIDENCE_DIR / "audit_checks.json"
    exit_code = 1
    try:
        pg.validate_test_server_url(database_core._DATABASE_URL)
        target = pg.create_test_database(database_core._DATABASE_URL, purpose="rbac_audit_source")
        assert target.name.startswith("nexora_pytest_rbac_audit_source_")
        child_environment = dict(os.environ)
        child_environment["DATABASE_URL"] = target.url
        child_environment["PYTHONIOENCODING"] = "utf-8"
        command = [sys.executable, "-m", "pytest", "-q", *TEST_FILES]
        summary["command"] = ".venv/Scripts/python.exe -m pytest -q " + " ".join(TEST_FILES)
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(command, cwd=WORKSPACE, env=child_environment, stdout=log, stderr=subprocess.STDOUT)
        summary["pytest_exit_code"] = completed.returncode
        summary["policy_probes"] = run_policy_probes()
        exit_code = completed.returncode
    except Exception as error:
        # Do not expose a connection string or configured credentials in errors.
        summary["harness_error_type"] = type(error).__name__
        summary["harness_error_message"] = "Audit harness incomplete; no application database was initialized"
    finally:
        pg.close_temporary_test_connections()
        pg.close_database_pool()
        pg.restore_database_state(state)
        if target is not None:
            try:
                pg.drop_test_database(target)
                summary["dedicated_source_database_removed"] = True
            except Exception as error:
                summary["dedicated_source_database_removed"] = False
                summary["cleanup_error_type"] = type(error).__name__
                exit_code = 1
        result_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pytest_exit_code": summary.get("pytest_exit_code"),
        "probe_count": len(summary.get("policy_probes", [])),
        "source_database_removed": summary.get("dedicated_source_database_removed"),
        "harness_error_type": summary.get("harness_error_type"),
        "evidence": str(result_path),
        "pytest_log": str(log_path),
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
