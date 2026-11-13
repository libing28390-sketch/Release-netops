"""PostgreSQL-backed claims, outcomes and audit history for scheduled jobs."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from services.monitoring_notification_outbox_service import enqueue_alert_delivery


NOTIFIABLE_RUN_STATUSES = frozenset({"failed", "partial_failure", "unknown", "denied"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime | str) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def make_scheduled_run_key(job_id: str, scheduled_for: datetime | str) -> str:
    canonical = f"scheduled-job-run:v1:{_text(job_id)}:{iso_utc(scheduled_for)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _job_run_snapshot(job: dict[str, Any], grant: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "id": _text(job.get("id")),
        "name": _text(job.get("name")),
        "job_type": _text(job.get("job_type")),
        "action_type": _text(job.get("action_type")),
        "owner_id": _text(job.get("created_by_id")),
        "tenant_id": _text(job.get("tenant_id")),
        "grant_id": _text(grant.get("grant_id")) if grant else "",
        "grant_version": int(grant.get("version") or 0) if grant else 0,
        "snapshot_hash": _text(job.get("authorization_manifest_hash")),
        "ticket_source_type": _text(grant.get("ticket_source_type")) if grant else "",
        "ticket_id": _text(grant.get("ticket_id")) if grant else "",
        "ticket_number": _text(grant.get("ticket_number")) if grant else "",
        "ticket_title": _text(grant.get("ticket_title")) if grant else "",
        "change_order_id": _text(grant.get("change_order_id")) if grant else "",
        "change_order_number": _text(grant.get("change_order_number")) if grant else "",
    }


def _enqueue_run_notification(
    conn,
    *,
    job: dict[str, Any],
    run: dict[str, Any],
    status: str,
    success_count: int,
    failed_count: int,
    summary: str,
) -> None:
    if status not in NOTIFIABLE_RUN_STATUSES:
        return
    now = datetime.now(timezone.utc)
    payload = {
        "title": f"定时作业结果需要处理：{_text(job.get('name'))}",
        "object_name": _text(job.get("name")),
        "ip_address": "N/A",
        "status": "active",
        "severity": "major",
        "message": (
            f"作业：{_text(job.get('name'))}\n"
            f"运行编号：{_text(run.get('run_id'))}\n"
            f"运行状态：{status}\n"
            f"关联工单：{_text(run.get('ticket_number'))}\n"
            f"成功设备：{max(0, int(success_count))}；失败设备：{max(0, int(failed_count))}\n"
            f"说明：{_text(summary)[:1000]}"
        ),
        "first_occurrence": iso_utc(now),
        "last_occurrence": iso_utc(now),
        "tenant_id": _text(job.get("tenant_id")),
        "event_kind": "active",
    }
    enqueue_alert_delivery(
        delivery_key=f"scheduled-run:{_text(run.get('run_key'))}:outcome:{status}:workspace",
        channel="workspace",
        payload=payload,
        connection=conn,
    )


def _insert_run(
    conn,
    *,
    job: dict[str, Any],
    scheduled_for: datetime | str,
    grant: dict[str, Any] | None,
    status: str,
    run_id: str,
    run_key: str,
    started: bool,
    error_code: str = "",
    error_summary: str = "",
) -> None:
    snapshot = _job_run_snapshot(job, grant)
    now = datetime.now(timezone.utc)
    conn.execute(
        """INSERT INTO scheduled_job_runs (
               run_id, run_key, job_id, job_name, job_type, action_type,
               trigger_type, scheduled_for, grant_id, grant_version,
               snapshot_hash, ticket_source_type, ticket_id, ticket_number,
               ticket_title, change_order_id, change_order_number, owner_id,
               tenant_id, status, started_at, finished_at, error_code,
               error_summary, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?::timestamptz, NULLIF(?, ''), ?, ?,
                     ?, ?, ?, ?, ?, ?, ?, ?, ?,
                     CASE WHEN ? THEN ?::timestamptz ELSE NULL END,
                     CASE WHEN ? THEN ?::timestamptz ELSE NULL END,
                     ?, ?, ?::timestamptz, ?::timestamptz)
           ON CONFLICT (run_key) DO NOTHING""",
        (
            run_id, run_key, snapshot["id"], snapshot["name"], snapshot["job_type"],
            snapshot["action_type"], _text(job.get("job_type")) or "cron",
            iso_utc(scheduled_for), snapshot["grant_id"], snapshot["grant_version"],
            snapshot["snapshot_hash"], snapshot["ticket_source_type"], snapshot["ticket_id"],
            snapshot["ticket_number"], snapshot["ticket_title"], snapshot["change_order_id"],
            snapshot["change_order_number"], snapshot["owner_id"], snapshot["tenant_id"],
            status, started, iso_utc(now), not started, iso_utc(now), error_code,
            error_summary[:2000], iso_utc(now), iso_utc(now),
        ),
    )


def _grant_for_update(conn, job: dict[str, Any]) -> dict[str, Any] | None:
    grant_id = _text(job.get("current_authorization_grant_id"))
    if not grant_id:
        return None
    row = conn.execute(
        """SELECT * FROM scheduled_job_authorization_grants
             WHERE grant_id = ? AND job_id = ? FOR UPDATE""",
        (grant_id, _text(job.get("id"))),
    ).fetchone()
    return dict(row) if row else None


def claim_scheduled_job_run(
    conn,
    *,
    job_id: str,
    scheduled_for: datetime | str,
    authorized_manifest_hash: str,
) -> dict[str, Any]:
    """Atomically claim one occurrence and consume one authorized run."""
    conn.execute("BEGIN")
    job_row = conn.execute(
        "SELECT * FROM scheduled_jobs WHERE id = ? FOR UPDATE", (_text(job_id),),
    ).fetchone()
    if not job_row:
        conn.rollback()
        return {"claimed": False, "status": "skipped", "reason": "job_not_found"}
    job = dict(job_row)
    occurrence = _utc(scheduled_for)
    run_key = make_scheduled_run_key(job_id, occurrence)
    existing = conn.execute(
        "SELECT * FROM scheduled_job_runs WHERE run_key = ? FOR UPDATE", (run_key,),
    ).fetchone()
    if existing:
        conn.rollback()
        existing_run = dict(existing)
        return {
            "claimed": False,
            "duplicate": True,
            "run_id": _text(existing_run.get("run_id")),
            "status": _text(existing_run.get("status")),
            "error": _text(existing_run.get("error_summary")),
            "run": existing_run,
            "job": job,
        }

    run_id = str(uuid.uuid4())
    is_system = job.get("authorization_mode") == "system"
    grant = None if is_system else _grant_for_update(conn, job)
    if job.get("deleted_at") is not None:
        _insert_run(
            conn, job=job, scheduled_for=occurrence, grant=grant, status="skipped",
            run_id=run_id, run_key=run_key, started=False,
            error_code="job_deleted", error_summary="作业已删除，本次未执行",
        )
        conn.commit()
        return {
            "claimed": False,
            "run_id": run_id,
            "run_key": run_key,
            "status": "skipped",
            "reason": "job_deleted",
        }
    if not bool(job.get("enabled")):
        _insert_run(
            conn, job=job, scheduled_for=occurrence, grant=grant, status="skipped",
            run_id=run_id, run_key=run_key, started=False,
            error_code="job_disabled", error_summary="作业已停用，本次未执行",
        )
        conn.commit()
        return {"claimed": False, "run_id": run_id, "run_key": run_key, "status": "skipped"}

    denied_code = ""
    denied_message = ""
    if not is_system:
        if not grant:
            denied_code, denied_message = "grant_missing", "作业没有有效的授权记录"
        elif _text(grant.get("status")) != "active":
            denied_code, denied_message = "grant_inactive", "作业授权已撤销或失效"
        elif _text(grant.get("manifest_hash")) != _text(authorized_manifest_hash):
            denied_code, denied_message = "snapshot_mismatch", "作业内容与授权快照不一致"
        else:
            expiry = _utc(grant.get("valid_until"))
            if expiry <= datetime.now(timezone.utc):
                conn.execute(
                    "UPDATE scheduled_job_authorization_grants SET status = 'expired' WHERE grant_id = ?",
                    (_text(grant.get("grant_id")),),
                )
                denied_code, denied_message = "grant_expired", "作业授权已到期"
            elif int(grant.get("used_runs") or 0) >= int(grant.get("max_runs") or 0):
                conn.execute(
                    "UPDATE scheduled_job_authorization_grants SET status = 'exhausted' WHERE grant_id = ?",
                    (_text(grant.get("grant_id")),),
                )
                denied_code, denied_message = "grant_exhausted", "作业授权次数已用完"

    running = conn.execute(
        "SELECT run_id FROM scheduled_job_runs WHERE job_id = ? AND status = 'running' LIMIT 1 FOR UPDATE",
        (_text(job_id),),
    ).fetchone()
    if running:
        _insert_run(
            conn, job=job, scheduled_for=occurrence, grant=grant, status="skipped",
            run_id=run_id, run_key=run_key, started=False,
            error_code="job_already_running", error_summary="上一轮仍在运行，本次已跳过",
        )
        conn.commit()
        return {"claimed": False, "run_id": run_id, "run_key": run_key, "status": "skipped"}

    if denied_code:
        _insert_run(
            conn, job=job, scheduled_for=occurrence, grant=grant, status="denied",
            run_id=run_id, run_key=run_key, started=False,
            error_code=denied_code, error_summary=denied_message,
        )
        conn.execute(
            """UPDATE scheduled_jobs
                  SET enabled = 0, status = 'reauthorization_required',
                      last_run_at = ?, last_run_status = 'denied',
                      run_count = run_count + 1, updated_at = ?
                WHERE id = ?""",
            (iso_utc(datetime.now(timezone.utc)), iso_utc(datetime.now(timezone.utc)), _text(job_id)),
        )
        denied_row = conn.execute(
            "SELECT * FROM scheduled_job_runs WHERE run_id = ?", (run_id,),
        ).fetchone()
        _enqueue_run_notification(
            conn, job=job, run=dict(denied_row), status="denied",
            success_count=0, failed_count=0, summary=denied_message,
        )
        conn.commit()
        return {
            "claimed": False, "run_id": run_id, "run_key": run_key, "status": "denied",
            "reason": denied_code, "error_code": denied_code,
            "job": job, "error": denied_message,
        }

    if grant:
        updated = conn.execute(
            """UPDATE scheduled_job_authorization_grants
                  SET used_runs = used_runs + 1,
                      status = CASE WHEN used_runs + 1 >= max_runs THEN 'exhausted' ELSE status END
                WHERE grant_id = ? AND status = 'active'
                  AND used_runs < max_runs AND valid_until > NOW()
            RETURNING used_runs, max_runs""",
            (_text(grant.get("grant_id")),),
        ).fetchone()
        if not updated:
            denied_message = "作业授权已发生变化，必须重新申请审批"
            _insert_run(
                conn, job=job, scheduled_for=occurrence, grant=grant, status="denied",
                run_id=run_id, run_key=run_key, started=False,
                error_code="grant_claim_race", error_summary=denied_message,
            )
            conn.execute(
                """UPDATE scheduled_jobs
                      SET enabled = 0, status = 'reauthorization_required',
                          last_run_at = ?, last_run_status = 'denied',
                          run_count = run_count + 1, updated_at = ?
                    WHERE id = ?""",
                (iso_utc(datetime.now(timezone.utc)), iso_utc(datetime.now(timezone.utc)), _text(job_id)),
            )
            denied_row = conn.execute(
                "SELECT * FROM scheduled_job_runs WHERE run_id = ?", (run_id,),
            ).fetchone()
            _enqueue_run_notification(
                conn, job=job, run=dict(denied_row), status="denied",
                success_count=0, failed_count=0, summary=denied_message,
            )
            conn.commit()
            return {
                "claimed": False, "run_id": run_id, "run_key": run_key, "status": "denied",
                "reason": "grant_claim_race", "error_code": "grant_claim_race",
                "job": job, "error": denied_message,
            }
        grant["used_runs"] = int(dict(updated)["used_runs"])

    try:
        _insert_run(
            conn, job=job, scheduled_for=occurrence, grant=grant, status="running",
            run_id=run_id, run_key=run_key, started=True,
        )
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    return {"claimed": True, "run_id": run_id, "run_key": run_key, "job": job, "grant": grant}


def finalize_scheduled_job_run(
    conn,
    *,
    job: dict[str, Any],
    run_id: str,
    status: str,
    target_count: int = 0,
    success_count: int = 0,
    failed_count: int = 0,
    summary: str = "",
    error_code: str = "",
    execution_id: str = "",
    run_count_before: int = 0,
) -> dict[str, Any]:
    if status not in {"succeeded", "failed", "partial_failure", "unknown", "denied", "skipped"}:
        raise ValueError("scheduled job run outcome is invalid")
    conn.execute("BEGIN")
    row = conn.execute(
        "SELECT * FROM scheduled_job_runs WHERE run_id = ? FOR UPDATE", (_text(run_id),),
    ).fetchone()
    if not row:
        conn.rollback()
        raise ValueError("scheduled job run does not exist")
    run = dict(row)
    if run["status"] != "running":
        conn.rollback()
        return run
    now = datetime.now(timezone.utc)
    conn.execute(
        """UPDATE scheduled_job_runs
              SET status = ?, finished_at = ?::timestamptz,
                  target_count = ?, success_count = ?, failed_count = ?,
                  error_code = ?, error_summary = ?, execution_id = ?, updated_at = ?::timestamptz
            WHERE run_id = ?""",
        (
            status, iso_utc(now), max(0, int(target_count)), max(0, int(success_count)),
            max(0, int(failed_count)), _text(error_code), _text(summary)[:2000],
            _text(execution_id), iso_utc(now), _text(run_id),
        ),
    )
    legacy_status = {"succeeded": "success", "partial_failure": "partial"}.get(status, status)
    conn.execute(
        """UPDATE scheduled_jobs
              SET last_run_at = ?, last_run_status = ?,
                  run_count = GREATEST(run_count, ?),
                  enabled = CASE WHEN ? THEN 0 ELSE enabled END,
                  status = CASE WHEN ? THEN 'reauthorization_required' ELSE status END,
                  updated_at = ?
            WHERE id = ?""",
        (
            iso_utc(now), legacy_status, max(0, int(run_count_before)) + 1,
            status == "unknown" or status == "denied",
            status == "unknown" or status == "denied",
            iso_utc(now), _text(job.get("id")),
        ),
    )
    if status == "unknown" and _text(run.get("grant_id")):
        conn.execute(
            "UPDATE scheduled_job_authorization_grants SET status = 'revoked' WHERE grant_id = ? AND status = 'active'",
            (_text(run.get("grant_id")),),
        )
    if _text(run.get("grant_id")):
        grant_row = conn.execute(
            "SELECT used_runs, max_runs, status FROM scheduled_job_authorization_grants WHERE grant_id = ? FOR UPDATE",
            (_text(run.get("grant_id")),),
        ).fetchone()
        if grant_row and int(dict(grant_row).get("used_runs") or 0) >= int(dict(grant_row).get("max_runs") or 0):
            conn.execute(
                "UPDATE scheduled_jobs SET enabled = 0, status = 'reauthorization_required' WHERE id = ?",
                (_text(job.get("id")),),
            )
    _enqueue_run_notification(
        conn, job=job, run=run, status=status,
        success_count=success_count, failed_count=failed_count, summary=summary,
    )
    final = conn.execute(
        "SELECT * FROM scheduled_job_runs WHERE run_id = ?", (_text(run_id),),
    ).fetchone()
    conn.commit()
    return dict(final)

def serialize_scheduled_job_run(item: Any) -> dict[str, Any]:
    row = dict(item)
    status = _text(row.get("status"))
    detail = _text(row.get("error_summary"))
    return {
        "run_id": _text(row.get("run_id")),
        "run_key": _text(row.get("run_key")),
        "scheduled_for": iso_utc(row["scheduled_for"]) if row.get("scheduled_for") else None,
        "started_at": iso_utc(row["started_at"]) if row.get("started_at") else None,
        "finished_at": iso_utc(row["finished_at"]) if row.get("finished_at") else None,
        "status": status,
        "target_count": int(row.get("target_count") or 0),
        "success_count": int(row.get("success_count") or 0),
        "failure_count": int(row.get("failed_count") or 0),
        "summary": detail if status in {"succeeded", "skipped"} else "",
        "error": detail if status in {"failed", "partial_failure", "unknown", "denied"} else "",
        "error_code": _text(row.get("error_code")),
        "authorization_version": int(row.get("grant_version") or 0),
        "snapshot_hash": _text(row.get("snapshot_hash")),
        "ticket_source_type": _text(row.get("ticket_source_type")),
        "ticket_id": _text(row.get("ticket_id")),
        "ticket_number": _text(row.get("ticket_number")),
        "ticket_title": _text(row.get("ticket_title")),
        "change_order_id": _text(row.get("change_order_id")),
        "change_order_number": _text(row.get("change_order_number")),
        "resolved_by_username": _text(row.get("resolved_by_username")),
        "resolution_note": _text(row.get("resolution_note")),
    }


def list_scheduled_job_runs(conn, *, job_id: str, page: int, per_page: int) -> dict[str, Any]:
    safe_page = max(1, int(page))
    safe_size = min(100, max(1, int(per_page)))
    total_row = conn.execute(
        "SELECT COUNT(*) AS total FROM scheduled_job_runs WHERE job_id = ?", (_text(job_id),),
    ).fetchone()
    total = int(dict(total_row).get("total") or 0) if total_row else 0
    rows = conn.execute(
        """SELECT * FROM scheduled_job_runs WHERE job_id = ?
             ORDER BY scheduled_for DESC, run_id DESC LIMIT ? OFFSET ?""",
        (_text(job_id), safe_size, (safe_page - 1) * safe_size),
    ).fetchall()
    items = [serialize_scheduled_job_run(item) for item in rows]
    return {
        "items": items,
        "total": total,
        "page": safe_page,
        "per_page": safe_size,
        "total_pages": max(1, (total + safe_size - 1) // safe_size),
    }


def resolve_unknown_scheduled_job_run(
    conn,
    *,
    job_id: str,
    run_id: str,
    outcome: str,
    note: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    if outcome not in {"succeeded", "partial_failure", "failed"}:
        raise ValueError("人工核实结论无效")
    clean_note = _text(note)
    if not clean_note or len(clean_note) > 2000:
        raise ValueError("人工核实说明必填且不能超过 2000 字")
    conn.execute("BEGIN")
    row = conn.execute(
        """SELECT * FROM scheduled_job_runs
             WHERE run_id = ? AND job_id = ? FOR UPDATE""",
        (_text(run_id), _text(job_id)),
    ).fetchone()
    if not row:
        conn.rollback()
        raise ValueError("运行记录不存在")
    current = dict(row)
    if current.get("status") != "unknown":
        conn.rollback()
        raise ValueError("只有结果未知的运行记录可以人工核实")
    now = datetime.now(timezone.utc)
    actor_id = _text(user.get("user_id") or user.get("id"))
    actor_name = _text(user.get("username"))
    conn.execute(
        """UPDATE scheduled_job_runs
              SET resolved_from_status = 'unknown', resolved_outcome = ?, status = ?,
                  resolved_by_id = ?, resolved_by_username = ?, resolved_at = ?::timestamptz,
                  resolution_note = ?, error_summary = ?, updated_at = ?::timestamptz
            WHERE run_id = ?""",
        (outcome, outcome, actor_id, actor_name, iso_utc(now), clean_note, clean_note, iso_utc(now), _text(run_id)),
    )
    final = conn.execute(
        "SELECT * FROM scheduled_job_runs WHERE run_id = ?", (_text(run_id),),
    ).fetchone()
    conn.commit()
    return dict(final)
