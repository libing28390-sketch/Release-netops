from __future__ import annotations

import asyncio
from datetime import datetime

from services import scheduler_service


def test_scheduled_nsot_passes_only_online_devices_from_saved_site_scope(isolated_db, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    now = datetime.now().isoformat()
    try:
        for device_id, site, status in (
            ("nsot-wh-access-1", "WH-DC-02", "online"),
            ("nsot-wh-gateway-1", "WH-DC-02", "online"),
            ("nsot-hq-access-1", "HQ", "online"),
            ("nsot-wh-offline-1", "WH-DC-02", "offline"),
        ):
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, status, role, site) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (device_id, device_id, "192.0.2.10", "h3c_comware", status, "Access Switch", site),
            )
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(id, name, job_type, action_type, cron_expr, scheduled_at, device_scope, device_filter, enabled, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "nsot-site-job",
                "NSOT by site",
                "cron",
                "nsot",
                "*/15 * * * *",
                "",
                "site",
                "WH-DC-02",
                1,
                "approved",
                now,
                now,
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
