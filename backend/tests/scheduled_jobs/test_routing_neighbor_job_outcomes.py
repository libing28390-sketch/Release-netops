"""A mixed SNMP routing job must persist partial status, never full success."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import pytest
from database import get_db_connection
from services import scheduler_service

@pytest.mark.parametrize('protocol,updated,failed,expected', [
    ('bgp', 2, 0, 'success'),
    ('bgp', 1, 1, 'partial'),
    ('bgp', 0, 2, 'failed'),
    ('ospf', 1, 1, 'partial'),
])
def test_routing_job_persists_partial_device_failures(isolated_db, monkeypatch, protocol, updated, failed, expected):
    from services import ip_locator_service
    conn = get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    job_id = 'routing-outcome-test'
    conn.execute(
        "INSERT INTO scheduled_jobs (id,name,job_type,action_type,cron_expr,device_scope,enabled,status,created_at,updated_at) "
        "VALUES (?,?,'cron',?,'*/15 * * * *','all',1,'approved',?,?)",
        (job_id, 'SNMP routing outcome', protocol + '_neighbors', now, now),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(scheduler_service, '_authorize_scheduled_job_run', lambda *a: None)
    monkeypatch.setattr(scheduler_service, '_resolve_nsot_target_device_ids', lambda *a: ['device-a', 'device-b'])
    monkeypatch.setattr(scheduler_service, '_scheduled_job_max_targets', lambda *a: None)
    calls = []
    def collect(**kwargs):
        calls.append(kwargs)
        return {'collected_protocols': [protocol] if updated else [], 'updated_devices': updated, 'failed_devices': failed, 'target_count': 2}
    monkeypatch.setattr(ip_locator_service, 'sync_routing_neighbors_job', collect)
    result = asyncio.run(scheduler_service._run_scheduled_automation_job_body(job_id, run_id='routing-proof'))
    assert calls == [{'device_ids': {'device-a', 'device-b'}, 'explicit_protocols': {protocol}}]
    assert result['status'] == expected
    assert result['success_count'] == updated
    assert result['failed_count'] == failed
    conn = get_db_connection()
    try:
        row = conn.execute('SELECT last_run_status,run_count FROM scheduled_jobs WHERE id=?',(job_id,)).fetchone()
        assert row['last_run_status'] == expected
        assert row['run_count'] == 1
    finally:
        conn.close()
    if expected == 'partial':
        assert scheduler_service._normalized_scheduled_run_status(result['status']) == 'partial_failure'
