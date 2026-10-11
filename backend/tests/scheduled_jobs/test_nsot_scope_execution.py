from __future__ import annotations

import asyncio
from datetime import datetime

from services import scheduler_service
from services.scheduled_job_authorization import execution_snapshot, manifest_hash


def test_scheduled_nsot_passes_only_online_devices_from_saved_site_scope(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    now = datetime.now().isoformat()
    owner = make_user("nsot_scope_owner", role="Administrator")
    try:
        conn.execute(
            "UPDATE users SET tenant_id = 'tenant-nsot', scope_mode = 'legacy' WHERE id = ?",
            (owner["user_id"],),
        )
        for device_id, site, status in (
            ("nsot-wh-access-1", "WH-DC-02", "online"),
            ("nsot-wh-gateway-1", "WH-DC-02", "online"),
            ("nsot-hq-access-1", "HQ", "online"),
            ("nsot-wh-offline-1", "WH-DC-02", "offline"),
        ):
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, status, role, site, tenant_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (device_id, device_id, "192.0.2.10", "h3c_comware", status, "Access Switch", site, "tenant-nsot"),
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
        }
        job["authorization_manifest_hash"] = manifest_hash(execution_snapshot(conn, job))
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(id, name, job_type, action_type, cron_expr, scheduled_at, device_scope, device_filter, enabled, status, created_at, updated_at, created_by, created_by_id, tenant_id, authorization_mode, authorization_manifest_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job["id"], job["name"], job["job_type"], job["action_type"],
                job["cron_expr"], job["scheduled_at"], job["device_scope"],
                job["device_filter"], job["enabled"], "approved", now, now,
                owner["username"], job["created_by_id"], job["tenant_id"],
                "snapshot", job["authorization_manifest_hash"],
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

    assert observed_scopes == [{"nsot-wh-access-1", "nsot-wh-gateway-1"}]
    conn = isolated_db["module"].get_db_connection()
    try:
        run = conn.execute(
            "SELECT last_run_status, run_count FROM scheduled_jobs WHERE id = ?",
            ("nsot-site-job",),
        ).fetchone()
    finally:
        conn.close()
    assert run["last_run_status"] == "success"
    assert run["run_count"] == 1
