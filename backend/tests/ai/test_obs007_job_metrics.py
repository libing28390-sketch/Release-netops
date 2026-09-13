from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ai.services import job_observability
from ai.services.metrics import AIMetrics
from services.ingestion_pipeline_service import IngestionPipeline


class _FakeCursor:
    description = (("id",), ("status",), ("failed",))

    def __init__(self, jobs, locks):
        self.jobs = jobs
        self.locks = locks
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = str(sql)
        return self

    def fetchall(self):
        if "scheduler_locks" in self.sql:
            return self.locks
        return self.jobs


class _FakeConnection:
    def __init__(self, jobs, locks):
        self.cursor_value = _FakeCursor(jobs, locks)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_value

    def rollback(self):
        return None


def test_obs007_metrics_keep_job_events_and_queue_gauges_bounded():
    metrics = AIMetrics()
    metrics.job_event("import", "enqueued")
    metrics.job_event("reindex", "lease_lost")
    metrics.set_job_queue_snapshot("import", {"queued": 2, "backlog": 2, "failed": 1})

    jobs = metrics.snapshot()["jobs"]
    assert jobs["events"] == {"import:enqueued": 1, "reindex:lease_lost": 1}
    assert jobs["queues"]["import"]["queued"] == 2
    assert jobs["queues"]["import"]["failed"] == 1
    assert "tenant_id" not in str(jobs)


def test_obs007_import_snapshot_counts_backlog_failures_and_expired_leases():
    pipeline = IngestionPipeline()
    queued = pipeline.create_job(
        tenant_id="tenant-obs007-a",
        job_kind="document_import",
        idempotency_key="obs007-queued",
        scope={"source_id": "source-a"},
    )
    assert queued.execution_state == "queued"
    failed = pipeline.create_job(
        tenant_id="tenant-obs007-b",
        job_kind="document_import",
        idempotency_key="obs007-failed",
        scope={"source_id": "source-b"},
        max_retries=0,
    )
    failed.claim("worker-a")
    failed.fail(ValueError("safe failure"))
    running = pipeline.create_job(
        tenant_id="tenant-obs007-c",
        job_kind="document_import",
        idempotency_key="obs007-running",
        scope={"source_id": "source-c"},
    )
    start = datetime.now(timezone.utc) - timedelta(seconds=10)
    running.claim("worker-b", lease_seconds=1, now=start)

    view = pipeline.observability_snapshot(family="import", now=datetime.now(timezone.utc))
    assert view["backlog"] == 1
    assert view["failed"] == 1
    assert view["running"] == 1
    assert view["lease_anomalies"] == 1
    assert view["lease_expired"] >= 1
    assert "tenant-obs007" not in str(view)


def test_obs007_reindex_snapshot_detects_expired_running_lease(monkeypatch):
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).astimezone(
        timezone(timedelta(hours=8))
    )
    jobs = [
        ("reindex-queued", "queued", 0),
        ("reindex-failed", "failed", 2),
        ("reindex-running", "running", 0),
        ("reindex-completed", "completed", 0),
    ]
    locks = [("knowledge_reindex:reindex-running", expired)]
    monkeypatch.setattr(job_observability, "get_db_connection", lambda: _FakeConnection(jobs, locks))
    monkeypatch.setattr(job_observability.database_core, "_USE_PG", True)

    view, source = job_observability._reindex_queue_snapshot()
    assert source == "postgresql"
    assert view["backlog"] == 1
    assert view["failed"] == 1
    assert view["document_failures"] == 2
    assert view["completed"] == 1
    assert view["lease_anomalies"] == 1
    assert view["lease_expired"] == 1


def test_obs007_alerts_are_thresholded_and_payload_is_aggregate(monkeypatch):
    monkeypatch.setenv("AI_JOB_QUEUE_BACKLOG_ALERT_THRESHOLD", "2")
    monkeypatch.setenv("AI_JOB_FAILURE_ALERT_THRESHOLD", "1")
    monkeypatch.setenv("AI_JOB_LEASE_ANOMALY_ALERT_THRESHOLD", "1")
    queue = {key: 0 for key in job_observability._QUEUE_FIELDS}
    queue.update({"backlog": 2, "failed": 1, "lease_anomalies": 1})
    monkeypatch.setattr(job_observability, "_import_queue_snapshot", lambda: (queue, "process_local"))
    monkeypatch.setattr(job_observability, "_reindex_queue_snapshot", lambda: ({key: 0 for key in job_observability._QUEUE_FIELDS}, "postgresql"))

    view = job_observability.snapshot()
    codes = {item["code"] for item in view["alerts"]}
    assert codes == {"IMPORT_QUEUE_BACKLOG", "IMPORT_JOB_FAILURE", "IMPORT_LEASE_ANOMALY"}
    assert view["queues"]["import"]["backlog"] == 2
    assert "source_id" not in str(view)
    assert "tenant" not in str(view).casefold()
