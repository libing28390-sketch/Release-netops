from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.knowledge_ingestion import api_list_ingestion_jobs
from services.ingestion_pipeline_service import IngestionPipeline, ingestion_pipeline


@pytest.fixture(autouse=True)
def _reset_global_pipeline(monkeypatch):
    from api import knowledge_ingestion
    from core import tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    monkeypatch.setattr(knowledge_ingestion, "authorize_resource", lambda user, resource, action, **scope: action == "manage")
    ingestion_pipeline.reset_for_tests()
    yield
    ingestion_pipeline.reset_for_tests()


def _create(pipeline: IngestionPipeline, *, tenant: str, suffix: str):
    return pipeline.create_job(
        tenant_id=tenant,
        job_kind="document_import",
        idempotency_key=f"list-{suffix}",
        scope={"source_id": f"source-{suffix}"},
        actor="operator-1",
    )


def _user(tenant: str = "tenant-list"):
    return {"id": "operator-1", "username": "operator", "tenant_id": tenant, "role": "Operator"}


def test_ing020_list_is_tenant_scoped_and_bounded_with_stable_pagination():
    for suffix in ("a", "b", "c"):
        _create(ingestion_pipeline, tenant="tenant-list", suffix=suffix)
    _create(ingestion_pipeline, tenant="tenant-other", suffix="other")

    first = api_list_ingestion_jobs(page=1, page_size=2, user=_user())
    second = api_list_ingestion_jobs(page=2, page_size=2, user=_user())

    assert first["success"] is True
    assert first["total"] == 3
    assert first["count"] == 3
    assert first["page"] == 1
    assert first["page_size"] == 2
    assert first["total_pages"] == 2
    assert len(first["items"]) == 2
    assert len(second["data"]) == 1
    for item in first["items"] + second["items"]:
        assert item["lease_owner"] == ""
        assert "tenant_id" not in item
        assert "errors" not in item
        assert "audit_events" not in item
        assert "phase_history" not in item
        assert "fencing_token" not in str(item)


def test_ing020_filters_by_state_phase_and_safe_error_code():
    running = _create(ingestion_pipeline, tenant="tenant-list", suffix="running")
    running.claim("worker-1")
    running.advance_phase("scoped", actor="worker-1")

    failed = _create(ingestion_pipeline, tenant="tenant-list", suffix="failed")
    failed.claim("worker-1")
    failed.fail(ValueError("raw token=must-not-escape"), actor="worker-1")

    scoped = api_list_ingestion_jobs(execution_state="running", phase="scoped", user=_user())
    by_error = api_list_ingestion_jobs(search="INTERNAL_ERROR", user=_user())

    assert scoped["total"] == 1
    assert scoped["items"][0]["id"] == running.id
    assert scoped["items"][0]["phase"] == "scoped"
    assert by_error["total"] == 1
    assert by_error["items"][0]["last_error_code"] == "INTERNAL_ERROR"
    assert "raw token=must-not-escape" not in str(by_error)


def test_ing020_rejects_invalid_phase_without_leaking_backend_details():
    with pytest.raises(HTTPException) as exc:
        api_list_ingestion_jobs(phase="not-a-phase", user=_user())
    assert exc.value.status_code == 400
    assert exc.value.detail == {"code": "INVALID_PIPELINE_INPUT", "message": "phase is not supported"}
