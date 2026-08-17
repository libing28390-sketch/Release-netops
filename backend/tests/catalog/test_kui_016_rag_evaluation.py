from __future__ import annotations

import pytest


def _user(tenant_id: str = "tenant-kui016") -> dict:
    return {"username": "kui016-admin", "role": "Administrator", "tenant_id": tenant_id}


def _raw_report() -> dict:
    return {
        "baseline_id": "kui016-test",
        "system_under_test": "test-rag",
        "database": "PostgreSQL",
        "metrics": {
            "retrieval_accuracy": 1.0,
            "wrong_vendor_rate": 0.0,
            "version_conflict_rate": 0.0,
            "citation_accuracy": 1.0,
            "latency_ms": {"average": 1.2, "p50": 1.0, "p95": 2.0, "max": 3.0},
        },
        "cases": [
            {
                "id": "Q01",
                "query": "show ospf peer",
                "expected_ids": ["secret-document-id"],
                "returned_ids": ["secret-document-id"],
                "retrieval_correct": True,
                "citation_precision": 1.0,
                "vendor_mismatch": False,
                "version_conflict": False,
                "latency_ms": 1.2,
                "debug": {"sql": "SELECT secret"},
            }
        ],
    }


def test_kui016_status_is_empty_until_postgresql_run(monkeypatch):
    import services.knowledge_evaluation_service as service

    monkeypatch.setattr(service, "_LAST_REPORT", None)
    report = service.get_evaluation_report(_user())
    assert report["status"] == "not_run"
    assert report["database"] == "PostgreSQL"
    assert report["case_count"] == 10
    assert report["cases"] == []
    assert report["production_database_write"] is False
    assert "sqlite" not in str(report).lower()


def test_kui016_projection_redacts_ids_and_debug(monkeypatch):
    import services.knowledge_evaluation_service as service

    monkeypatch.setattr(service, "_LAST_REPORT", None)
    monkeypatch.setattr(service, "_run_postgresql_baseline", _raw_report)
    report = service.run_evaluation(_user())
    assert report["status"] == "passed"
    assert report["database"] == "PostgreSQL"
    assert report["rollback"] == "transaction_rollback"
    assert report["cases"][0]["id"] == "Q01"
    assert "secret-document-id" not in str(report)
    assert "SELECT secret" not in str(report)
    assert "debug" not in str(report).lower()
    assert report["gates"] and all(item["passed"] for item in report["gates"])


def test_kui016_tenant_projection_is_request_scoped(monkeypatch):
    import services.knowledge_evaluation_service as service

    monkeypatch.setattr(service, "_LAST_REPORT", None)
    monkeypatch.setattr(service, "_run_postgresql_baseline", _raw_report)
    first = service.run_evaluation(_user("tenant-a"))
    second = service.get_evaluation_report(_user("tenant-b"))
    assert first["tenant_id"] == "tenant-a"
    assert second["tenant_id"] == "tenant-b"
    assert second["baseline_id"] == "kui016-test"


def test_kui016_api_contract_and_suite_validation():
    from api.knowledge_evaluation import EvaluationRunRequest, api_get_evaluation, api_run_evaluation, router

    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes}
    assert any(path.endswith("/knowledge-v2/evaluation") and "GET" in methods for path, methods in paths)
    assert any(path.endswith("/knowledge-v2/evaluation/run") and "POST" in methods for path, methods in paths)
    with pytest.raises(Exception):
        EvaluationRunRequest.model_validate({"suite": "v1_baseline_postgresql", "raw_sql": "SELECT 1"})
    assert api_get_evaluation(user=_user())["success"] is True
    with pytest.raises(Exception) as exc:
        api_run_evaluation(EvaluationRunRequest(suite="unsupported"), user=_user())
    assert getattr(exc.value, "status_code", None) == 422
