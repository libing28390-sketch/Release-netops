"""Retire full NSOT scheduling and keep ARP on a bounded system schedule."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 306
NAME = "retire_nsot_daily_job"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("NSOT scheduled-job retirement requires PostgreSQL")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    # Soft-delete the exact built-in full refresh. Keep its run history and all
    # operator-created jobs intact for audit and possible manual disposition.
    cursor.execute(
        """UPDATE scheduled_jobs
              SET enabled = 0, status = 'disabled', deleted_at = ?, updated_at = ?
            WHERE id = 'nsot-daily-collection'
              AND name = 'NSOT 网络事实库每日采集'
              AND job_type = 'cron' AND action_type = 'nsot'
              AND cron_expr = '0 2 * * *' AND device_scope = 'all'
              AND COALESCE(device_filter, '') = ''
              AND COALESCE(created_by, '') = 'system'""",
        (now, now),
    )

    existing = cursor.execute(
        "SELECT id FROM scheduled_jobs WHERE id = 'arp-daily-sweep' LIMIT 1"
    ).fetchone()
    if existing:
        return

    cursor.execute(
        """INSERT INTO scheduled_jobs
           (id, name, job_type, action_type, cron_expr, scheduled_at,
            device_scope, device_filter, commands, script_id,
            is_config, config_reason, use_admin_creds, enabled, status,
            approved_by, approved_at, created_by, updated_by, created_at, updated_at,
            created_by_id, tenant_id, authorization_mode)
           VALUES (?, ?, 'cron', 'arp_sweep', '0 2 * * *', '',
                   'all', '', '', '', 0, '', 0, 1, 'approved',
                   'system', ?, 'system', 'system', ?, ?, '', 'tenant-default', 'system')""",
        ("arp-daily-sweep", "ARP 表每日分批采集", now, now, now),
    )
