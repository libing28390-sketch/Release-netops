from __future__ import annotations

import pytest
from fastapi import HTTPException
from concurrent.futures import ThreadPoolExecutor

from api.knowledge_ingestion import (
    IngestionJobCancelRequest,
    IngestionJobRetryRequest,
    api_cancel_ingestion_job,
    api_get_ingestion_job_errors,
    api_list_ingestion_jobs,
    api_retry_ingestion_job,
    router,
)
from services.ingestion_pipeline_service import IngestionPipeline, IngestionPipelineError, ingestion_pipeline


@pytest.fixture(autouse=True)
def _reset_global_pipeline():
    ingestion_pipeline.reset_for_tests()
    yield
    ingestion_pipeline.reset_for_tests()


def _job(pipeline: IngestionPipeline, *, tenant: str = "tenant-control", max_retries: int = 1):
    return pipeline.create_job(
        tenant_id=tenant,
        job_kind="document_import",
        idempotency_key="control-source-001",
        scope={"source_id": "src-control", "document_id": "doc-control"},
        max_retries=max_retries,
        actor="operator-1",
    )


def test_ing016_api_routes_and_permission_catalog_are_explicit():
    from core.rbac import permission_catalog

    paths = {(route.path, tuple(sorted(route.methods or []))) for route in router.routes}
    assert ("/knowledge-v2/ingestion/jobs", ("GET",)) in paths
    assert ("/knowledge-v2/ingestion/jobs/{job_id}", ("GET",)) in paths
    assert ("/knowledge-v2/ingestion/jobs/{job_id}/errors", ("GET",)) in paths
    assert ("/knowledge-v2/ingestion/jobs/{job_id}/cancel", ("POST",)) in paths
    assert ("/knowledge-v2/ingestion/jobs/{job_id}/retry", ("POST",)) in paths
    assert set(permission_catalog()["knowledge_import"]) >= {"read", "cancel", "retry"}


def test_ing017_same_process_claim_race_has_one_winner():
    pipeline = IngestionPipeline()
    job = _job(pipeline)

    def claim(worker: str):
        try:
            return pipeline.claim_job(job.id, tenant_id="tenant-control", worker_id=worker)
        except Exception as exc:  # the loser must be a stable lease error
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("worker-a", "worker-b")))
    winners = [value for value in results if not isinstance(value, Exception)]
    losers = [value for value in results if isinstance(value, Exception)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert getattr(losers[0], "code", "") == "LEASE_HELD"


def test_ing016_cancel_is_tenant_scoped_and_queued_jobs_are_acknowledged():
    pipeline = IngestionPipeline()
    job = _job(pipeline)

    with pytest.raises(IngestionPipelineError) as hidden:
        pipeline.request_cancel(job.id, tenant_id="tenant-other", actor="operator-2")
    assert hidden.value.code == "JOB_NOT_FOUND"

    cancelled = pipeline.request_cancel(
        job.id,
        tenant_id="tenant-control",
        actor="operator-1",
        reason="source retired",
        request_id="cancel-001",
    )
    assert cancelled.execution_state == "cancelled"
    assert cancelled.phase == "cancelled"
    assert cancelled.cancellation_reason == "source retired"
    assert any(event["event_type"] == "cancel_requested" for event in cancelled.audit_events)

    replay = pipeline.request_cancel(job.id, tenant_id="tenant-control", actor="operator-1", request_id="cancel-001")
    assert replay.id == job.id
    assert replay.execution_state == "cancelled"


def test_ing016_retry_creates_a_new_attempt_and_never_replays_success():
    pipeline = IngestionPipeline()
    failed = _job(pipeline)
    failed.claim("worker-1")
    failed.fail(ValueError("integrity hash mismatch; sensitive-value-should-not-persist"), actor="worker-1", request_id="fail-001")
    assert failed.execution_state == "failed"
    assert failed.phase == "failed"
    assert failed.last_error_code == "DATA_INTEGRITY"
    assert "sensitive-value-should-not-persist" not in str(failed.to_dict())

    retry = pipeline.retry_job(failed.id, tenant_id="tenant-control", actor="operator-1", request_id="retry-001")
    assert retry.id != failed.id
    assert retry.retry_of_job_id == failed.id
    assert retry.execution_state == "queued"
    assert retry.phase == "accepted"

    replay = pipeline.retry_job(failed.id, tenant_id="tenant-control", actor="operator-1", request_id="retry-001")
    assert replay.id == retry.id

    success = pipeline.create_job(
        tenant_id="tenant-control",
        job_kind="document_import",
        idempotency_key="control-source-success",
        scope={"source_id": "src-control-success"},
        actor="operator-1",
    )
    success.claim("worker-1")
    success.update_progress(total_count=1, processed_count=1, parsed_count=1, succeeded_count=1)
    for phase in ("scoped", "fetched", "parsed", "normalized", "classified", "chunked", "embedded", "indexed", "validated", "committed", "completed"):
        # The first phase is accepted -> scoped; all remaining transitions are
        # explicit so the test also protects the completion gate.
        if phase == "scoped":
            success.advance_phase(phase)
        else:
            success.advance_phase(phase)
    success.complete()
    with pytest.raises(IngestionPipelineError) as no_replay:
        pipeline.retry_job(success.id, tenant_id="tenant-control", actor="operator-1")
    assert no_replay.value.code == "RETRY_NOT_ALLOWED"


def test_ing016_api_exposes_progress_and_safe_error_details_with_rbac_boundaries():
    user = {"id": "operator-1", "username": "operator", "tenant_id": "tenant-control", "role": "Operator"}
    job = ingestion_pipeline.create_job(
        tenant_id="tenant-control",
        job_kind="document_import",
        idempotency_key="api-control-001",
        scope={"source_id": "src-api"},
        actor="operator-1",
    )
    job.claim("worker-api")
    running_view = api_list_ingestion_jobs(execution_state="running", user=user)
    assert running_view["count"] == 1
    assert "fencing_token" not in str(running_view)
    assert running_view["data"][0]["lease_owner"] == ""
    job.fail(ValueError("token=secret raw output"), actor="worker-api")

    listed = api_list_ingestion_jobs(execution_state="", user=user)
    assert listed["success"] is True
    assert listed["count"] == 1
    assert listed["data"][0]["progress_percent"] == 100.0

    errors = api_get_ingestion_job_errors(job.id, user=user)
    assert errors["data"]["last_error_code"] == "SECRET_OR_SSRF_VIOLATION"
    assert "token=secret" not in str(errors).casefold()
    assert "raw output" not in str(errors).casefold()

    queued = ingestion_pipeline.create_job(
        tenant_id="tenant-control",
        job_kind="document_import",
        idempotency_key="api-control-002",
        scope={"source_id": "src-api-2"},
        actor="operator-1",
    )
    cancel_result = api_cancel_ingestion_job(
        queued.id,
        payload=IngestionJobCancelRequest(reason="stop", request_id="api-cancel-001"),
        user=user,
    )
    assert cancel_result["success"] is True
    assert cancel_result["data"]["execution_state"] == "cancelled"

    with pytest.raises(HTTPException) as terminal:
        api_cancel_ingestion_job(
            job.id,
            payload=IngestionJobCancelRequest(reason="late"),
            user=user,
        )
    assert terminal.value.status_code == 409
    assert terminal.value.detail["code"] == "CANCEL_NOT_ALLOWED"
