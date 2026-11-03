from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from services import scheduler_service
from services.scheduled_job_authorization import (
    execution_snapshot,
    manifest_hash,
    normalize_authorization_grant,
)


def test_retired_nsot_job_disables_itself_without_collecting_devices(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    now = datetime.now().isoformat()
    owner = make_user("nsot_scope_owner", role="Operator")
    try:
        conn.execute(
            "UPDATE users SET tenant_id = 'tenant-nsot', scope_mode = 'legacy' WHERE id = ?",
            (owner["user_id"],),
        )
        for device_id, site, status in (
            ("nsot-wh-access-1", "WH-DC-02", "online"),
            ("nsot-wh-gateway-1", "WH-DC-02", "online"),
            ("nsot-wh-old-tenant-1", "WH-DC-02", "online"),
            ("nsot-hq-access-1", "HQ", "online"),
            ("nsot-wh-offline-1", "WH-DC-02", "offline"),
        ):
            device_tenant = "tenant-history-old" if device_id == "nsot-wh-old-tenant-1" else "tenant-nsot"
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, status, role, site, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (device_id, device_id, "192.0.2.10", "h3c_comware", status, "Access Switch", site, device_tenant),
            )
        job = {
            "id": "nsot-site-job",
            "name": "NSOT by site",
            "job_type": "cron",
            "action_type": "nsot",
            "cron_expr": "*/15 * * * *",
            "scheduled_at": "",
            "device_scope": "site",
            "device_filter": "WH-DC-02",
            "commands": "",
            "script_id": "",
            "is_config": 0,
            "config_reason": "",
            "use_admin_creds": 0,
            "enabled": 1,
            "created_by_id": owner["user_id"],
            "tenant_id": "tenant-nsot",
            "authorization_mode": "snapshot",
            "current_authorization_grant_id": "nsot-site-job-grant",
        }
        grant = normalize_authorization_grant({
            "valid_until": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            "max_runs": 5,
            "max_targets": 10,
            "scope": {"type": "site", "filter": "WH-DC-02"},
            "ticket_source_type": "incident",
            "ticket_id": "nsot-scope-fixture-incident",
        })
        job["authorization_grant"] = grant
        job["authorization_manifest_hash"] = manifest_hash(execution_snapshot(conn, job))
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(id, name, job_type, action_type, cron_expr, scheduled_at, device_scope, device_filter, enabled, status, created_at, updated_at, created_by, created_by_id, tenant_id, authorization_mode, authorization_manifest_hash, current_authorization_grant_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job["id"], job["name"], job["job_type"], job["action_type"],
                job["cron_expr"], job["scheduled_at"], job["device_scope"],
                job["device_filter"], job["enabled"], "approved", now, now,
                owner["username"], job["created_by_id"], job["tenant_id"],
                "snapshot", job["authorization_manifest_hash"], job["current_authorization_grant_id"],
            ),
        )
        conn.execute(
            """INSERT INTO scheduled_job_authorization_grants (
                   grant_id, job_id, version, status, owner_id, tenant_id,
                   template_version, manifest_hash, grant_json, valid_until,
                   max_runs, used_runs, max_targets, ticket_source_type,
                   ticket_id, ticket_number, ticket_title, change_order_id,
                   change_order_number, created_by_id, approved_by_id
               ) VALUES (?, ?, 1, 'active', ?, ?, 'nsot-fixture-v1', ?, ?::jsonb,
                         ?::timestamptz, ?, 0, ?, 'incident', ?, 'INC-NSOT-1',
                         'NSOT scope fixture', '', '', ?, 'nsot-approver')""",
            (
                job["current_authorization_grant_id"], job["id"], owner["user_id"],
                job["tenant_id"], job["authorization_manifest_hash"],
                json.dumps(grant, ensure_ascii=False), grant["valid_until"],
                grant["max_runs"], grant["max_targets"], grant["ticket_id"], owner["user_id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    observed_scopes: list[set[str] | None] = []

    def fake_run_unified_nsot_sync(*, device_ids=None):
        observed_scopes.append(device_ids)
        return {"topology": {"status": "complete"}}

    monkeypatch.setattr(
        "services.ip_locator_service.run_unified_nsot_sync",
        fake_run_unified_nsot_sync,
    )

    asyncio.run(scheduler_service.run_scheduled_automation_job("nsot-site-job"))

    assert observed_scopes == []
    conn = isolated_db["module"].get_db_connection()
    try:
        run = conn.execute(
            "SELECT last_run_status, run_count, enabled, status FROM scheduled_jobs WHERE id = ?",
            ("nsot-site-job",),
        ).fetchone()
    finally:
        conn.close()
    assert run["last_run_status"] == "retired"
    assert run["run_count"] == 1
    assert run["enabled"] == 0
    assert run["status"] == "disabled"


def test_historical_scheduled_job_keeps_owner_action_and_device_scope_checks(isolated_db, make_user):
    conn = isolated_db["module"].get_db_connection()
    owner = make_user("history_job_owner", role="Operator", tenant_id="tenant-history-owner")
    try:
        for device_id, tenant_id, site in (
            ("history-job-device-in-scope", "tenant-history-a", "site-allowed"),
            ("history-job-device-out-of-scope", "tenant-history-b", "site-denied"),
        ):
            conn.execute(
                "INSERT INTO devices (id, hostname, status, site, tenant_id) VALUES (?, ?, 'online', ?, ?)",
                (device_id, device_id, site, tenant_id),
            )

        job = {
            "id": "history-scheduled-job",
            "name": "History scheduled job",
            "job_type": "cron",
            "action_type": "inspection",
            "cron_expr": "*/15 * * * *",
            "scheduled_at": "",
            "device_scope": "all",
            "device_filter": "",
            "commands": "",
            "script_id": "",
            "is_config": 0,
            "config_reason": "",
            "use_admin_creds": 0,
            "enabled": 1,
            "created_by_id": owner["user_id"],
            "tenant_id": "tenant-history-job",
            "authorization_mode": "snapshot",
        }
        job["authorization_manifest_hash"] = manifest_hash(execution_snapshot(conn, job))

        revalidated_owner = scheduler_service._authorize_scheduled_job_run(conn, job)
        assert revalidated_owner["id"] == owner["user_id"]
        assert set(scheduler_service._authorize_scheduled_job_targets(
            conn, revalidated_owner, job, ["history-job-device-in-scope"],
        )) == {"history-job-device-in-scope"}

        conn.execute("UPDATE users SET scope_mode = 'restricted' WHERE id = ?", (owner["user_id"],))
        conn.execute(
            """INSERT INTO user_resource_scopes
               (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES ('history-job-site-scope', ?, 'scheduled_job', 'site', 'site-allowed', '[\"execute\"]', ?)""",
            (owner["user_id"], datetime.now().isoformat()),
        )
        conn.commit()

        scoped_owner = {**revalidated_owner, "scope_mode": "restricted"}
        with pytest.raises(PermissionError, match="no longer has scheduled execution access"):
            scheduler_service._authorize_scheduled_job_targets(
                conn, scoped_owner, job,
                ["history-job-device-in-scope", "history-job-device-out-of-scope"],
            )

        viewer = make_user("history_job_viewer", role="Viewer", tenant_id="tenant-history-owner")
        viewer_job = {**job, "created_by_id": viewer["user_id"]}
        viewer_job["authorization_manifest_hash"] = manifest_hash(execution_snapshot(conn, viewer_job))
        with pytest.raises(PermissionError, match="execution authorization"):
            scheduler_service._authorize_scheduled_job_run(conn, viewer_job)
    finally:
        conn.close()
