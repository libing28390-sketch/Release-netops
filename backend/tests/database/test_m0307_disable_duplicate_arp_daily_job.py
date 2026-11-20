from __future__ import annotations

from database import get_db_connection
from database.migrations.m0307_disable_duplicate_arp_daily_job import upgrade


def test_upgrade_disables_only_the_builtin_daily_arp_job_idempotently(isolated_db):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT id FROM scheduled_jobs WHERE id = 'arp-daily-sweep'"
        ).fetchone()
        assert row is not None
        conn.execute(
            "UPDATE scheduled_jobs SET enabled=1,status='approved',deleted_at=NULL "
            "WHERE id='arp-daily-sweep'"
        )
        conn.commit()

        upgrade(conn.cursor(), True)
        first = conn.execute(
            "SELECT enabled,status,deleted_at FROM scheduled_jobs WHERE id='arp-daily-sweep'"
        ).fetchone()
        upgrade(conn.cursor(), True)
        second = conn.execute(
            "SELECT enabled,status,deleted_at FROM scheduled_jobs WHERE id='arp-daily-sweep'"
        ).fetchone()

        assert first['enabled'] == 0 and first['status'] == 'disabled'
        assert first['deleted_at']
        assert dict(first) == dict(second)
    finally:
        conn.close()
