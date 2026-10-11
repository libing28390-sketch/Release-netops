from __future__ import annotations

from datetime import datetime, timezone

from api import scheduled_jobs
from core.scheduler_manager import scheduler


class _FakeTrigger:
    def __init__(self, description: str):
        self.description = description

    def __str__(self) -> str:
        return self.description


class _FakeJob:
    def __init__(self, job_id: str, *, trigger: str = "interval[0:05:00]"):
        self.id = job_id
        self.trigger = _FakeTrigger(trigger)
        self.next_run_time = datetime(2026, 7, 18, 2, 30, tzinfo=timezone.utc)


def test_system_job_catalog_is_limited_to_operator_facing_schedules():
    assert tuple(scheduled_jobs._SYSTEM_JOB_CATALOG) == (
        "daily_backup",
        "inspection_scheduler",
        "password_rotation_sweep",
    )


def test_system_jobs_hide_internal_unknown_and_user_jobs(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "get_jobs",
        lambda: [
            _FakeJob("routing_neighbors_sync"),
            _FakeJob("daily_backup", trigger="cron[hour='2', minute='0']"),
            _FakeJob("dyn_user-created-job"),
            _FakeJob("future_internal_daemon"),
            _FakeJob("inspection_scheduler", trigger="cron[hour='2,14', minute='30']"),
        ],
    )

    response = scheduled_jobs.list_system_scheduled_jobs(_user={"role": "Administrator"})

    assert response["success"] is True
    assert response["data"]["total"] == 2
    assert [item["id"] for item in response["data"]["items"]] == [
        "daily_backup",
        "inspection_scheduler",
    ]
    assert response["data"]["items"][0]["name_zh"] == "配置自动备份"
    assert response["data"]["items"][0]["next_run_at"] == "2026-07-18T02:30:00+00:00"


def test_system_jobs_include_password_rotation_only_when_registered(monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "get_jobs",
        lambda: [_FakeJob("password_rotation_sweep")],
    )

    response = scheduled_jobs.list_system_scheduled_jobs(_user={"role": "Administrator"})

    assert response["data"]["total"] == 1
    assert response["data"]["items"][0]["id"] == "password_rotation_sweep"


def test_system_jobs_fail_closed_when_scheduler_registry_is_unavailable(monkeypatch):
    def _raise():
        raise RuntimeError("scheduler not started")

    monkeypatch.setattr(scheduler, "get_jobs", _raise)

    response = scheduled_jobs.list_system_scheduled_jobs(_user={"role": "Administrator"})

    assert response == {"success": True, "data": {"items": [], "total": 0}}
