from __future__ import annotations

import pytest


def _trace(status: str = "hit") -> dict:
    return {
        "source": "local_rag",
        "status": status,
        "request": {"vendor": "Huawei"},
        "resolution": {"ambiguous": False, "platform_candidates": ["huawei_vrp"], "evidence": "exact"},
        "citations": [],
    }


@pytest.fixture(autouse=True)
def _reset_pipeline_and_traces():
    from ai.services.retrieval_trace_store import clear_retrieval_traces
    from services.ingestion_pipeline_service import ingestion_pipeline

    ingestion_pipeline.reset_for_tests()
    clear_retrieval_traces()
    yield
    ingestion_pipeline.reset_for_tests()
    clear_retrieval_traces()


def test_legacy_ingestion_jobs_are_visible_without_opening_other_users_jobs(monkeypatch):
    from api import knowledge_ingestion
    from core import tenant_policy
    from services.ingestion_pipeline_service import ingestion_pipeline

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    alice_old = ingestion_pipeline.create_job(
        tenant_id="tenant-history-a", job_kind="document_import", idempotency_key="alice-old", actor="alice",
    )
    alice_other_tenant = ingestion_pipeline.create_job(
        tenant_id="tenant-history-b", job_kind="document_import", idempotency_key="alice-default", actor="alice",
    )
    bob_old = ingestion_pipeline.create_job(
        tenant_id="tenant-history-a", job_kind="document_import", idempotency_key="bob-old", actor="bob",
    )
    monkeypatch.setattr(
        knowledge_ingestion,
        "authorize_resource",
        lambda user, resource, action, **scope: action == "read",
    )

    result = knowledge_ingestion.api_list_ingestion_jobs(
        user={"id": "alice", "username": "alice", "tenant_id": "tenant-history-a", "role": "Viewer"},
    )

    assert result["total"] == 2
    assert {item["id"] for item in result["items"]} == {alice_old.id, alice_other_tenant.id}

    with pytest.raises(Exception) as hidden:
        knowledge_ingestion.api_get_ingestion_job(
            job_id=bob_old.id,
            user={"id": "alice", "username": "alice", "tenant_id": "tenant-history-a", "role": "Viewer"},
        )
    assert getattr(hidden.value, "status_code", None) == 404

    cancelled = knowledge_ingestion.api_cancel_ingestion_job(
        job_id=alice_old.id,
        payload=None,
        user={"id": "alice", "username": "alice", "tenant_id": "tenant-history-a", "role": "Viewer"},
    )
    assert cancelled["data"]["execution_state"] == "cancelled"
    with pytest.raises(Exception) as denied:
        knowledge_ingestion.api_cancel_ingestion_job(
            job_id=bob_old.id,
            payload=None,
            user={"id": "alice", "username": "alice", "tenant_id": "tenant-history-a", "role": "Viewer"},
        )
    assert getattr(denied.value, "status_code", None) == 404

    failed_alice = ingestion_pipeline.create_job(
        tenant_id="tenant-history-a", job_kind="document_import", idempotency_key="alice-failed", actor="alice",
    )
    failed_alice.claim("importer")
    failed_alice.fail(ValueError("synthetic import failure"), actor="importer")
    retried = knowledge_ingestion.api_retry_ingestion_job(
        job_id=failed_alice.id,
        payload=None,
        user={"id": "alice", "username": "alice", "tenant_id": "tenant-history-a", "role": "Viewer"},
    )
    assert retried["data"]["tenant_id"] == "tenant-default"
    assert retried["data"]["retry_of_job_id"] == failed_alice.id


def test_ingestion_manage_permission_allows_cross_user_history(monkeypatch):
    from api import knowledge_ingestion
    from core import tenant_policy
    from services.ingestion_pipeline_service import ingestion_pipeline

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    first = ingestion_pipeline.create_job(
        tenant_id="tenant-history-a", job_kind="document_import", idempotency_key="managed-a", actor="alice",
    )
    second = ingestion_pipeline.create_job(
        tenant_id="tenant-history-b", job_kind="document_import", idempotency_key="managed-b", actor="bob",
    )
    def authorize(user, resource, action, **scope):
        if action == "manage":
            assert (resource, scope) == ("knowledge_import", {"tenant_id": None})
        return action in {"read", "manage"}

    monkeypatch.setattr(knowledge_ingestion, "authorize_resource", authorize)

    result = knowledge_ingestion.api_list_ingestion_jobs(
        user={"id": "admin", "username": "admin", "tenant_id": "tenant-history-a", "role": "Administrator"},
    )

    assert result["total"] == 2
    assert {item["id"] for item in result["items"]} == {first.id, second.id}


def test_retrieval_trace_writes_default_and_api_reads_legacy_tenant(monkeypatch):
    from ai.services.retrieval_trace_store import record_retrieval_trace
    from api.knowledge_traces import api_get_retrieval_trace, api_list_retrieval_traces
    from core import tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    legacy_trace = record_retrieval_trace(
        tenant_id="tenant-history-a", user_id="alice", query="legacy", trace=_trace(),
    )
    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    new_trace = record_retrieval_trace(
        tenant_id="tenant-history-a", user_id="alice", query="new", trace=_trace(),
    )

    legacy = api_get_retrieval_trace(
        trace_id=legacy_trace,
        user={"id": "alice", "tenant_id": "tenant-history-b", "role": "Administrator"},
    )
    listed = api_list_retrieval_traces(
        limit=50,
        status="all",
        user={"id": "alice", "tenant_id": "tenant-history-b", "role": "Administrator"},
    )

    assert legacy["data"]["trace_id"] == legacy_trace
    assert {item["trace_id"] for item in listed["data"]["items"]} == {legacy_trace, new_trace}
    new_item = next(item for item in listed["data"]["items"] if item["trace_id"] == new_trace)
    assert new_item["tenant_id"] == "tenant-default"


def test_knowledge_import_helpers_use_default_tenant_for_new_records(monkeypatch):
    from core import tenant_policy
    from services.enterprise_sop_import_service import _tenant as sop_tenant
    from services.local_official_file_import_service import _tenant as local_tenant
    from services.official_seed_batch_service import _tenant as seed_tenant
    from services.official_url_import_service import _tenant as official_tenant

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    legacy_user = {"id": "alice", "tenant_id": "tenant-history-a"}

    assert official_tenant(legacy_user) == "tenant-default"
    assert local_tenant(legacy_user) == "tenant-default"
    assert sop_tenant(legacy_user) == "tenant-default"
    assert seed_tenant(legacy_user) == "tenant-default"


def test_evaluation_projection_uses_default_tenant_in_single_org(monkeypatch):
    from core import tenant_policy
    from services import knowledge_evaluation_service

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    monkeypatch.setattr(knowledge_evaluation_service, "_LAST_REPORT", None)
    monkeypatch.setattr(knowledge_evaluation_service, "_run_postgresql_baseline", lambda: {
        "baseline_id": "single-org-eval",
        "metrics": {},
        "cases": [],
    })

    report = knowledge_evaluation_service.run_evaluation({"tenant_id": "tenant-history-a"})
    visible = knowledge_evaluation_service.get_evaluation_report({"tenant_id": "tenant-history-b"})

    assert report["tenant_id"] == "tenant-default"
    assert visible["tenant_id"] == "tenant-default"


def test_source_registry_api_lists_sources_with_historical_tenant_labels(isolated_db, make_user, monkeypatch):
    from api.knowledge_sources import api_list_sources
    from core import tenant_policy
    from services.knowledge_v1_source_service import create_source

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    source_a = create_source(
        {
            "source_type": "internal",
            "source_kind": "internal",
            "canonical_url": "https://kb.internal.example/legacy/a",
            "name": "Legacy source A",
            "metadata": {},
        },
        make_user("knowledge-scope-a", role="Administrator", tenant_id="tenant-history-a"),
    )
    source_b = create_source(
        {
            "source_type": "internal",
            "source_kind": "internal",
            "canonical_url": "https://kb.internal.example/legacy/b",
            "name": "Legacy source B",
            "metadata": {},
        },
        make_user("knowledge-scope-b", role="Administrator", tenant_id="tenant-history-b"),
    )
    reader = make_user("knowledge-scope-reader", role="Administrator", tenant_id="tenant-history-a")
    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    created = create_source(
        {
            "source_type": "internal",
            "source_kind": "internal",
            "canonical_url": "https://kb.internal.example/single-org/new",
            "name": "Single organization source",
            "metadata": {},
        },
        reader,
    )

    response = api_list_sources(
        status="all", tenant_id=None, page=1, page_size=20, sort_by="updated_at", sort_order="desc", user=reader,
    )

    assert response["success"] is True
    assert {item["id"] for item in response["data"]} >= {source_a["id"], source_b["id"], created["id"]}
    assert created["tenant_id"] == "tenant-default"


def test_observability_api_passes_no_tenant_filter_in_single_org(monkeypatch):
    from api import knowledge_evaluation
    from core import tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)
    captured: dict[str, object] = {}
    monkeypatch.setattr(knowledge_evaluation, "get_experiment_observability", lambda **kwargs: captured.update(kwargs) or {})

    response = knowledge_evaluation.api_get_experiment_observability(
        limit=50,
        user={"id": "observer", "tenant_id": "tenant-history-a", "role": "Administrator"},
    )

    assert response["success"] is True
    assert captured == {"tenant_id": None, "limit": 50}
