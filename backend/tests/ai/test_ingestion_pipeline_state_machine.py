from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.ingestion_pipeline_service import (
    ERROR_CATALOG,
    EXECUTION_TRANSITIONS,
    PHASE_ORDER,
    RETRYABLE_ERROR_CODES,
    IngestionErrorCode,
    IngestionPipeline,
    IngestionPipelineError,
    InvalidPhaseError,
    InvalidTransitionError,
    LeaseError,
    ProgressInvariantError,
    classify_ingestion_error,
    error_catalog,
)


def _pipeline() -> IngestionPipeline:
    return IngestionPipeline()


def _job(pipeline: IngestionPipeline, *, max_retries: int = 0):
    return pipeline.create_job(
        tenant_id="tenant-ingestion",
        job_kind="document_import",
        idempotency_key="source-001",
        scope={"source_id": "src-001", "document_id": "doc-001"},
        max_retries=max_retries,
        actor="operator-1",
    )


def test_ing001_machine_and_error_taxonomy_are_explicit_and_fail_closed():
    assert PHASE_ORDER == ("accepted", "scoped", "fetched", "parsed", "normalized", "classified", "chunked", "embedded", "indexed", "validated", "committed", "completed")
    assert EXECUTION_TRANSITIONS["queued"] == frozenset({"running", "cancel_requested"})
    assert RETRYABLE_ERROR_CODES == {"SOURCE_TIMEOUT", "RATE_LIMITED", "TRANSIENT_DATABASE", "PROVIDER_UNAVAILABLE", "WORKER_LOST", "ROBOTS_UNAVAILABLE"}
    assert set(ERROR_CATALOG) == RETRYABLE_ERROR_CODES | {
        "INVALID_SCOPE", "ACL_DENIED", "PARSER_CONTRACT", "UNSUPPORTED_FORMAT", "SECRET_OR_SSRF_VIOLATION", "DATA_INTEGRITY", "ROBOTS_DISALLOWED", "INTERNAL_ERROR",
    }
    assert error_catalog()["SOURCE_TIMEOUT"]["retryable"] is True
    assert error_catalog()["SECRET_OR_SSRF_VIOLATION"]["retryable"] is False
    with pytest.raises(IngestionPipelineError) as invalid:
        _pipeline().create_job(tenant_id="tenant-ingestion", job_kind="not-a-kind", idempotency_key="bad", scope={})
    assert invalid.value.code == "INVALID_PIPELINE_INPUT"


def test_ing001_idempotency_and_tenant_scope_are_server_owned():
    pipeline = _pipeline()
    first = _job(pipeline)
    replay = pipeline.create_job(
        tenant_id="tenant-ingestion", job_kind="document_import", idempotency_key="source-001", scope={"source_id": "src-001", "document_id": "doc-001"}
    )
    assert replay.id == first.id
    with pytest.raises(IngestionPipelineError) as conflict:
        pipeline.create_job(tenant_id="tenant-ingestion", job_kind="document_import", idempotency_key="source-001", scope={"source_id": "src-002"})
    assert conflict.value.code == "IDEMPOTENCY_KEY_CONFLICT"
    assert pipeline.get_job(first.id, tenant_id="tenant-other") is None
    assert pipeline.list_jobs(tenant_id="tenant-other") == []


def test_ing001_phase_order_requires_explicit_skip_evidence_and_completion_progress():
    pipeline = _pipeline()
    job = _job(pipeline)
    job.claim("worker-1")
    with pytest.raises(InvalidPhaseError) as skip:
        job.advance_phase("fetched")
    assert skip.value.code == "PHASE_SKIP_EVIDENCE_REQUIRED"
    job.advance_phase("scoped", actor="worker")
    job.advance_phase("fetched", actor="worker")
    job.advance_phase("parsed", actor="worker")
    with pytest.raises(InvalidPhaseError):
        job.advance_phase("scoped", actor="worker")
    job.update_progress(total_count=1, actor="worker")
    with pytest.raises(InvalidPhaseError) as no_progress:
        job.advance_phase("completed", actor="worker", evidence={"skipped_phases": list(PHASE_ORDER[4:-1])})
    assert no_progress.value.code == "COMPLETION_PROGRESS_REQUIRED"
    job.update_progress(total_count=1, processed_count=1, parsed_count=1, succeeded_count=1, actor="worker")
    for phase in ("normalized", "classified", "chunked", "embedded", "indexed", "validated", "committed", "completed"):
        job.advance_phase(phase, actor="worker")
    assert job.complete(actor="worker")["execution_state"] == "succeeded"


def test_ing001_progress_is_server_derived_and_invariants_reject_client_corruption():
    job = _job(_pipeline())
    assert job.to_dict()["progress_percent"] == 100.0
    with pytest.raises(ProgressInvariantError):
        job.update_progress(total_count=2, processed_count=3)
    with pytest.raises(ProgressInvariantError):
        job.update_progress(total_count=2, processed_count=1, parsed_count=2)
    job.update_progress(total_count=4, processed_count=2, parsed_count=2, succeeded_count=2, actor="worker")
    assert job.progress_percent == 50.0
    assert job.to_dict()["progress_percent"] == 50.0
    with pytest.raises(ProgressInvariantError):
        job.update_progress(total_count=3)


def test_ing001_error_classification_is_stable_retryable_and_redacted():
    timeout = classify_ingestion_error(TimeoutError("password=do-not-persist"), phase="fetched", item_id="item-1", source_id="source-1", attempt_no=2, correlation_id="req-1")
    assert timeout.code == "SOURCE_TIMEOUT"
    assert timeout.retryable is True
    assert "password" not in timeout.safe_message.casefold()
    assert "do-not-persist" not in str(timeout.to_dict())
    worker_lost = classify_ingestion_error("WORKER_LOST", phase="parsed")
    assert worker_lost.code == "WORKER_LOST"
    blocked = classify_ingestion_error(RuntimeError("SSRF blocked by policy with token=secret"), phase="fetched")
    assert blocked.code == "SECRET_OR_SSRF_VIOLATION"
    assert blocked.retryable is False
    robots = classify_ingestion_error("ROBOTS_DISALLOWED", phase="scoped")
    assert robots.code == "ROBOTS_DISALLOWED"
    assert robots.retryable is False
    unknown = classify_ingestion_error(RuntimeError("unclassified raw device output"), phase="parsed")
    assert unknown.code == "INTERNAL_ERROR"
    assert "device output" not in str(unknown.to_dict())


def test_ing001_retry_budget_and_lease_fencing_prevent_duplicate_workers():
    pipeline = _pipeline()
    job = _job(pipeline, max_retries=1)
    claimed = job.claim("worker-a", lease_seconds=30)
    token = claimed["fencing_token"]
    with pytest.raises(LeaseError) as held:
        job.claim("worker-b", lease_seconds=30)
    assert held.value.code == "LEASE_HELD"
    with pytest.raises(LeaseError) as stale:
        job.heartbeat("worker-b", token)
    assert stale.value.code == "STALE_LEASE"
    retry = job.fail(TimeoutError("network timeout"), actor="worker-a")
    assert retry["execution_state"] == "retry_wait"
    reclaimed = job.claim("worker-b", now=datetime.now(timezone.utc) + timedelta(seconds=1))
    assert reclaimed["execution_state"] == "running"
    assert reclaimed["attempt_no"] == 2
    assert reclaimed["fencing_token"] != token


def test_ing001_expired_lease_is_recoverable_once_and_old_worker_is_fenced():
    pipeline = _pipeline()
    job = _job(pipeline, max_retries=1)
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    claimed = job.claim("worker-a", lease_seconds=1, now=past)
    recovered = job.recover_expired_lease(now=datetime.now(timezone.utc))
    assert recovered["execution_state"] == "retry_wait"
    assert recovered["last_error_code"] == "WORKER_LOST"
    with pytest.raises(LeaseError):
        job.heartbeat("worker-a", claimed["fencing_token"])
    assert job.claim("worker-b", now=datetime.now(timezone.utc) + timedelta(seconds=1))["execution_state"] == "running"


def test_ing001_cancellation_is_cooperative_idempotent_and_auditable():
    job = _job(_pipeline())
    job.claim("worker-a")
    requested = job.request_cancel("operator-1", reason="source retired", request_id="req-cancel")
    assert requested["execution_state"] == "cancel_requested"
    assert job.request_cancel("operator-1", reason="duplicate", request_id="req-cancel")["execution_state"] == "cancel_requested"
    cancelled = job.acknowledge_cancel("worker-a", requested["fencing_token"], request_id="req-cancel")
    assert cancelled["execution_state"] == "cancelled"
    assert cancelled["phase"] == "cancelled"
    assert cancelled["cancelled_at"]
    assert any(event["event_type"] == "cancel_requested" for event in cancelled["audit_events"])
    assert job.acknowledge_cancel("worker-a")["execution_state"] == "cancelled"


def test_ing001_failed_terminal_state_requires_structured_error_and_v1_is_not_touched():
    job = _job(_pipeline())
    job.claim("worker-a")
    with pytest.raises(IngestionPipelineError) as invalid:
        job.transition_execution_state("failed")
    assert invalid.value.code == "FAILED_WITHOUT_ERROR"
    failed = job.fail(ValueError("integrity hash mismatch"), actor="worker-a")
    assert failed["execution_state"] == "failed"
    assert failed["phase"] == "failed"
    assert failed["last_error_code"] == "DATA_INTEGRITY"
    assert failed["errors"][0]["safe_message"]
