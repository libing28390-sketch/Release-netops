from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api.automation import _build_approval_manifest
from database import schema as database_schema
from services import execution_history_service, scheduler_service


def test_missing_job_grant_is_recorded_in_tenant_execution_history(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    owner = make_user("scheduled_denied_owner", role="Operator", tenant_id="tenant-denied-history")
    now = datetime.now().isoformat()
    try:
        conn.execute(
            "INSERT INTO scheduled_jobs "
            "(id, name, job_type, action_type, enabled, status, created_by, created_by_id, tenant_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "scheduled-denied-history-job", "Denied scheduled Linux inspection", "cron", "inspection",
                1, "approved", owner["username"], owner["user_id"], owner["tenant_id"], now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    scheduled_for = datetime(2031, 1, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(scheduler_service, "_scheduled_occurrence_time", lambda *_args: scheduled_for)
    result = asyncio.run(scheduler_service.run_scheduled_automation_job("scheduled-denied-history-job"))
    assert result["status"] == "denied"
    assert result["reason"] == "grant_missing"
    duplicate = asyncio.run(scheduler_service.run_scheduled_automation_job("scheduled-denied-history-job"))
    assert duplicate["duplicate"] is True

    history = execution_history_service.get_execution_history(
        page=1,
        page_size=20,
        trigger_type="job",
        query="",
        user={"role": "Operator", "tenant_id": owner["tenant_id"]},
        include_playbooks=True,
        include_backup_runs=False,
    )
    denied_runs = [
        item for item in history["items"]
        if item["source"] == "playbook" and item["name"] == "Denied scheduled Linux inspection"
    ]
    assert len(denied_runs) == 1
    assert denied_runs[0]["status"] == "denied"
    assert denied_runs[0]["trigger_type"] == "job"
    assert denied_runs[0]["name"] == "Denied scheduled Linux inspection"
    assert denied_runs[0]["created_by"] == owner["username"]

    conn = isolated_db["module"].get_db_connection()
    try:
        job = conn.execute(
            "SELECT last_run_status, run_count FROM scheduled_jobs WHERE id = ?",
            ("scheduled-denied-history-job",),
        ).fetchone()
        execution = conn.execute(
            "SELECT device_ids, phases_json, tenant_id FROM playbook_executions WHERE id = ?",
            (denied_runs[0]["id"],),
        ).fetchone()
        ledger = conn.execute(
            "SELECT status, error_code, error_summary FROM scheduled_job_runs WHERE run_id = ?",
            (denied_runs[0]["id"],),
        ).fetchone()
    finally:
        conn.close()

    assert job["last_run_status"] == "denied"
    assert job["run_count"] == 1
    assert json.loads(execution["device_ids"]) == []
    assert execution["tenant_id"] == owner["tenant_id"]
    assert json.loads(execution["phases_json"])["authorization"]["reason"] == "作业没有有效的授权记录"
    assert ledger["status"] == "denied"
    assert ledger["error_code"] == "grant_missing"
    assert ledger["error_summary"] == json.loads(execution["phases_json"])["authorization"]["reason"]


def test_deleted_job_is_skipped_and_duplicate_trigger_is_audited_once(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    owner = make_user("scheduled_deleted_owner", role="Operator", tenant_id="tenant-deleted-job")
    now = datetime.now().isoformat()
    try:
        conn.execute(
            """INSERT INTO scheduled_jobs
                   (id, name, job_type, action_type, enabled, status, created_by,
                    created_by_id, tenant_id, created_at, updated_at, deleted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NOW())""",
            (
                "scheduled-deleted-job", "Deleted scheduled job", "cron", "command",
                0, "deleted", owner["username"], owner["user_id"], owner["tenant_id"], now, now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    scheduled_for = datetime(2031, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(scheduler_service, "_scheduled_occurrence_time", lambda *_args: scheduled_for)

    first = asyncio.run(scheduler_service.run_scheduled_automation_job("scheduled-deleted-job"))
    duplicate = asyncio.run(scheduler_service.run_scheduled_automation_job("scheduled-deleted-job"))

    assert first["status"] == "skipped"
    assert first["reason"] == "job_deleted"
    assert duplicate["duplicate"] is True
    assert duplicate["status"] == "skipped"

    conn = isolated_db["module"].get_db_connection()
    try:
        runs = conn.execute(
            "SELECT COUNT(*) AS total FROM scheduled_job_runs WHERE job_id = ?",
            ("scheduled-deleted-job",),
        ).fetchone()
        execution = conn.execute(
            "SELECT COUNT(*) AS total FROM playbook_executions WHERE scenario_id = ?",
            ("scheduled:scheduled-deleted-job",),
        ).fetchone()
        run = conn.execute(
            "SELECT status, error_code FROM scheduled_job_runs WHERE job_id = ?",
            ("scheduled-deleted-job",),
        ).fetchone()
    finally:
        conn.close()
    assert int(runs["total"]) == 1
    assert int(execution["total"]) == 0
    assert run["status"] == "skipped"
    assert run["error_code"] == "job_deleted"


def test_standard_script_digest_refresh_tracks_current_released_system_content(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    content = "#!/bin/sh\necho refreshed inspection script\n"
    try:
        conn.execute(
            "UPDATE scripts SET content = ?, content_sha256 = ? WHERE id = ?",
            (content, "stale-digest", "insp_linux_full"),
        )
        assert database_schema._refresh_standard_script_digests(conn) == 1
        row = conn.execute(
            "SELECT content_sha256 FROM scripts WHERE id = ?",
            ("insp_linux_full",),
        ).fetchone()
        conn.commit()
    finally:
        conn.close()

    assert row["content_sha256"] == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_stale_published_script_approval_request_returns_conflict(isolated_db, make_user):
    conn = isolated_db["module"].get_db_connection()
    requester = make_user("stale_script_approval_requester", role="Operator", tenant_id="tenant-stale-script")
    try:
        conn.execute(
            "UPDATE scripts SET content_sha256 = ? WHERE id = ?",
            ("stale-digest", "insp_linux_full"),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(HTTPException) as exc_info:
        _build_approval_manifest(
            "scheduled_job",
            {"operation_manifest": {"operation": "CREATE", "script_id": "insp_linux_full"}},
            requester,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "已发布脚本内容摘要无效，必须重新审批"
