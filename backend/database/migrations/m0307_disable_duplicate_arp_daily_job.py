"""Disable the daily ARP sweep now that ARP/FDB share one interval job."""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 307
NAME = "disable_duplicate_arp_daily_job"


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("ARP schedule consolidation requires PostgreSQL")

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    cursor.execute(
        """UPDATE scheduled_jobs
              SET enabled = 0, status = 'disabled', deleted_at = ?, updated_at = ?
            WHERE id = 'arp-daily-sweep'
              AND name = 'ARP 表每日分批采集'
              AND job_type = 'cron' AND action_type = 'arp_sweep'
              AND cron_expr = '0 2 * * *' AND device_scope = 'all'
              AND COALESCE(device_filter, '') = ''
              AND COALESCE(created_by, '') = 'system'""",
        (now, now),
    )
