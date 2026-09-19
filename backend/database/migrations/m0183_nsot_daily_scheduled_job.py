"""Replace the built-in NSOT collector fan-out with one daily job.

The application keeps the manual NSOT trigger, but the high-frequency
APScheduler collectors are no longer registered.  Seed one ordinary,
operator-visible scheduled job so upgraded installations get the same daily
workflow without requiring a second manual setup step.
"""

from __future__ import annotations

from datetime import datetime, timezone


VERSION = 183
NAME = "nsot_daily_scheduled_job"

_JOB_ID = "nsot-daily-collection"
_JOB_NAME = "NSOT 网络事实库每日采集"
_CRON_EXPR = "0 2 * * *"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    """Insert the default job exactly once without overwriting operator data."""
    existing = cursor.execute(
        """SELECT id FROM scheduled_jobs
           WHERE id = ? OR (action_type = 'nsot' AND name = ?)
           LIMIT 1""",
        (_JOB_ID, _JOB_NAME),
    ).fetchone()
    if existing:
        return

    now = _now()
    cursor.execute(
        """INSERT INTO scheduled_jobs
           (id, name, job_type, action_type, cron_expr, scheduled_at,
            device_scope, device_filter, commands, script_id,
            is_config, config_reason, use_admin_creds, enabled, status,
            approved_by, approved_at, created_by, created_at, updated_at)
           VALUES (?, ?, 'cron', 'nsot', ?, '',
                   'all', '', '', '',
                   0, ?, 0, 1, 'approved',
                   'system', ?, 'system', ?, ?)""",
        (
            _JOB_ID,
            _JOB_NAME,
            _CRON_EXPR,
            "统一执行 ARP、终端、路由、邻居、BGP、拓扑和接口状态采集",
            now,
            now,
            now,
        ),
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Do not delete a scheduled job during downgrade; an operator may have
    # edited it or relied on its execution history after the migration ran.
    return None
