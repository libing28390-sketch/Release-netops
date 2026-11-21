from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from database import get_db_connection
from services.scheduled_job_authorization import normalize_authorization_grant
from services.scheduled_job_run_service import (
    claim_scheduled_job_run,
    finalize_scheduled_job_run,
    make_scheduled_run_key,
    resolve_unknown_scheduled_job_run,
)


def _insert_job_and_grant(
    *,
    job_id: str,
    grant_id: str,
    max_runs: int = 3,
    used_runs: int = 0,
    valid_until: datetime | None = None,
    max_targets: int = 5,
) -> None:
    now = datetime.now(timezone.utc)
    until = valid_until or (now + timedelta(days=2))
    grant_json = {
        "valid_until": until.isoformat().replace("+00:00", "Z"),
        "max_runs": max_runs,
        "max_targets": max_targets,
        "scope": {"type": "all", "filter": ""},
        "ticket_source_type": "incident",
        "ticket_id": "ticket-fixture",
        "change_order_id": "",
    }
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO scheduled_jobs (
                   id, name, job_type, action_type, cron_expr, device_scope,
                   device_filter, commands, enabled, status, last_run_status,
                   created_by, updated_by, created_at, updated_at, created_by_id,
                   tenant_id, authorization_mode, authorization_manifest_hash,
                   current_authorization_grant_id
               ) VALUES (?, ?, 'cron', 'command', '* * * * *', 'all', '', 'show version',
                         1, 'approved', '', 'operator', 'operator', ?, ?, ?,
                         'tenant-default', 'snapshot', 'snapshot-v1', ?)""",
            (job_id, f"M5 job {job_id}", now.isoformat(), now.isoformat(), "owner-1", grant_id),
        )
        conn.execute(
            """INSERT INTO scheduled_job_authorization_grants (
                   grant_id, job_id, version, status, owner_id, tenant_id,
                   template_version, manifest_hash, grant_json, valid_until,
                   max_runs, used_runs, max_targets, ticket_source_type,
                   ticket_id, ticket_number, ticket_title, change_order_id,
                   change_order_number, created_by_id, approved_by_id
               ) VALUES (?, ?, 1, 'active', 'owner-1', 'tenant-default',
                         'script-sha-v1', 'snapshot-v1', ?::jsonb, ?::timestamptz,
                         ?, ?, ?, 'incident', 'ticket-fixture', 'INC-M5-1',
                         'fixture incident', '', '', 'owner-1', 'approver-1')""",
            (grant_id, job_id, json.dumps(grant_json), grant_json["valid_until"], max_runs, used_runs, max_targets),
        )
        conn.commit()
    finally:
        conn.close()


def test_m5_grant_normalizes_and_binds_exact_scope():
    grant = normalize_authorization_grant({
        "valid_until": "2030-01-01T00:00:00Z",
        "max_runs": 3,
        "max_targets": 20,
        "scope": {"type": "site", "filter": "DC1"},
        "ticket_source_type": "incident",
        "ticket_id": "inc-1",
    })
    assert grant["scope"] == {"type": "site", "filter": "DC1"}
    assert grant["max_runs"] == 3


def test_m5_run_claim_is_idempotent_and_partial_outcome_notifies_once(isolated_db):
    from services.scheduled_job_run_service import list_scheduled_job_runs

    job_id = "m5-idempotent-job"
    grant_id = "m5-idempotent-grant"
    _insert_job_and_grant(job_id=job_id, grant_id=grant_id)
    scheduled_for = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)

    conn = get_db_connection()
    try:
        first = claim_scheduled_job_run(conn, job_id=job_id, scheduled_for=scheduled_for, authorized_manifest_hash="snapshot-v1")
        duplicate = claim_scheduled_job_run(conn, job_id=job_id, scheduled_for=scheduled_for, authorized_manifest_hash="snapshot-v1")
        assert first["claimed"] is True
        assert duplicate["claimed"] is False
        assert duplicate["duplicate"] is True
        assert duplicate["run"]["run_id"] == first["run_id"]
        grant = conn.execute("SELECT used_runs FROM scheduled_job_authorization_grants WHERE grant_id = ?", (grant_id,)).fetchone()
        assert int(grant["used_runs"]) == 1

        final = finalize_scheduled_job_run(
            conn,
            job=first["job"],
            run_id=first["run_id"],
            status="partial_failure",
            target_count=4,
            success_count=3,
            failed_count=1,
            summary="1 台设备执行失败",
            execution_id="execution-m5-1",
            run_count_before=0,
        )
        assert final["status"] == "partial_failure"
        history = list_scheduled_job_runs(conn, job_id=job_id, page=1, per_page=10)
        assert history["total"] == 1
        assert history["items"][0]["authorization_version"] == 1
        assert history["items"][0]["failure_count"] == 1
        delivery = conn.execute(
            "SELECT * FROM alert_delivery_outbox WHERE delivery_key = ?",
            (f"scheduled-run:{make_scheduled_run_key(job_id, scheduled_for)}:outcome:partial_failure:workspace",),
        ).fetchone()
        assert delivery is not None
        assert delivery["channel"] == "workspace"
    finally:
        conn.close()


def test_m5_unknown_run_disables_job_revokes_grant_and_requires_manual_resolution(isolated_db):
    job_id = "m5-unknown-job"
    grant_id = "m5-unknown-grant"
    _insert_job_and_grant(job_id=job_id, grant_id=grant_id)
    scheduled_for = datetime(2030, 1, 2, 12, 0, tzinfo=timezone.utc)
    actor = {"user_id": "owner-1", "id": "owner-1", "username": "operator"}

    conn = get_db_connection()
    try:
        claim = claim_scheduled_job_run(conn, job_id=job_id, scheduled_for=scheduled_for, authorized_manifest_hash="snapshot-v1")
        result = finalize_scheduled_job_run(
            conn,
            job=claim["job"],
            run_id=claim["run_id"],
            status="unknown",
            target_count=2,
            summary="执行过程中连接中断，结果未知",
            error_code="execution_result_unknown",
            run_count_before=0,
        )
        assert result["status"] == "unknown"
        job = conn.execute("SELECT enabled, status FROM scheduled_jobs WHERE id = ?", (job_id,)).fetchone()
        assert int(job["enabled"]) == 0
        assert job["status"] == "reauthorization_required"
        grant = conn.execute("SELECT status FROM scheduled_job_authorization_grants WHERE grant_id = ?", (grant_id,)).fetchone()
        assert grant["status"] == "revoked"
        resolved = resolve_unknown_scheduled_job_run(
            conn, job_id=job_id, run_id=claim["run_id"], outcome="failed",
            note="已核对设备变更记录，未确认命令生效", user=actor,
        )
        assert resolved["status"] == "failed"
        assert resolved["resolved_from_status"] == "unknown"
        assert resolved["resolution_note"]
        again = None
        try:
            resolve_unknown_scheduled_job_run(
                conn, job_id=job_id, run_id=claim["run_id"], outcome="succeeded",
                note="不应覆盖首次复核", user=actor,
            )
        except ValueError as exc:
            again = str(exc)
        assert again and "未知" in again
    finally:
        conn.close()


def test_m5_expired_grant_is_denied_and_notice_is_deduplicated(isolated_db):
    job_id = "m5-expired-job"
    grant_id = "m5-expired-grant"
    _insert_job_and_grant(
        job_id=job_id,
        grant_id=grant_id,
        valid_until=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    scheduled_for = datetime(2030, 1, 3, 12, 0, tzinfo=timezone.utc)
    conn = get_db_connection()
    try:
        first = claim_scheduled_job_run(conn, job_id=job_id, scheduled_for=scheduled_for, authorized_manifest_hash="snapshot-v1")
        duplicate = claim_scheduled_job_run(conn, job_id=job_id, scheduled_for=scheduled_for, authorized_manifest_hash="snapshot-v1")
        assert first["claimed"] is False
        assert first["status"] == "denied"
        assert duplicate["duplicate"] is True
        run = conn.execute("SELECT status, error_code FROM scheduled_job_runs WHERE run_key = ?", (make_scheduled_run_key(job_id, scheduled_for),)).fetchone()
        assert run["status"] == "denied"
        assert run["error_code"] == "grant_expired"
        delivery_count = conn.execute(
            "SELECT COUNT(*) AS count FROM alert_delivery_outbox WHERE delivery_key = ?",
            (f"scheduled-run:{make_scheduled_run_key(job_id, scheduled_for)}:outcome:denied:workspace",),
        ).fetchone()["count"]
        assert int(delivery_count) == 1
    finally:
        conn.close()
