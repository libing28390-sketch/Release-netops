from __future__ import annotations

import pytest

from services.ingestion_job_lease_service import ImportJobLease, IngestionJobLeaseCoordinator
from services.ingestion_pipeline_service import IngestionPipeline, LeaseError


def test_ing017_database_lease_blocks_duplicate_worker_and_fences_release(isolated_db):
    first = ImportJobLease("tenant-ing017", "ing_job_001", "worker-a", lease_seconds=30)
    second = ImportJobLease("tenant-ing017", "ing_job_001", "worker-b", lease_seconds=30)

    assert first.acquire() is True
    assert second.acquire() is False
    assert first.heartbeat() is True
    assert first.release() is True
    assert second.acquire() is True
    assert second.release() is True


def test_ing017_coordinator_joins_database_lock_to_state_machine_and_tenant_scope(isolated_db):
    pipeline = IngestionPipeline()
    job = pipeline.create_job(
        tenant_id="tenant-ing017",
        job_kind="document_import",
        idempotency_key="ing017-source",
        scope={"source_id": "source-ing017"},
        actor="operator-1",
    )
    coordinator = IngestionJobLeaseCoordinator(pipeline)
    claim = coordinator.claim(job.id, tenant_id="tenant-ing017", worker_id="worker-a")
    assert claim.job.execution_state == "running"
    assert claim.snapshot()["lease_held"] is True
    assert "fencing_token" not in claim.snapshot()

    with pytest.raises(LeaseError) as duplicate:
        coordinator.claim(job.id, tenant_id="tenant-ing017", worker_id="worker-b")
    assert duplicate.value.code == "LEASE_HELD"

    # A tenant-scoped lock name allows the same opaque job id in another
    # tenant, while the state-machine lookup still rejects a cross-tenant job.
    other_tenant = ImportJobLease("tenant-other", job.id, "worker-other", lease_seconds=30)
    assert other_tenant.acquire() is True
    other_tenant.release()

    claim.job.fail(ValueError("integrity hash mismatch"), actor="worker-a")
    assert coordinator.release(claim) is True

