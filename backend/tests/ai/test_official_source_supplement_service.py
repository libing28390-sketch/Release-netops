from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import official_source_supplement_service as service


def _request() -> SimpleNamespace:
    return SimpleNamespace(vendor="Huawei", product_model="S5700", product_series="", software_release="V200R023", software_train="", feature="ospf", feature_domain="routing")


def test_no_match_suggestions_are_durable_searchable_and_rejectable(isolated_db, monkeypatch) -> None:
    from core import tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    rows = service.record_official_source_suggestions(
        _request(), tenant_id="tenant-a", trace_id="rt-miss-1", request_id="req-1", query="Huawei S5700 OSPF"
    )
    assert rows
    assert all(item["status"] == "pending" for item in rows)
    page = service.list_official_source_suggestions(tenant_id="tenant-a", status="pending", search="S5700")
    assert page["total"] == len(rows)
    rejected = service.review_official_source_suggestion(
        rows[0]["id"], tenant_id="tenant-a", user={"id": "admin"}, decision="reject", fields={}
    )
    assert rejected["status"] == "rejected"


def test_approval_requires_complete_scope_and_creates_collection_job(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    from core import tenant_policy

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    request = _request()
    request.software_release = ""
    item = service.record_official_source_suggestions(
        request, tenant_id="tenant-a", trace_id="rt-miss-2", request_id="req-2", query="Huawei S5700 OSPF"
    )[0]
    with pytest.raises(service.OfficialSourceSupplementError) as incomplete:
        service.review_official_source_suggestion(
            item["id"], tenant_id="tenant-a", user={"id": "admin"}, decision="approve",
            fields={"software_release": ""},
        )
    assert incomplete.value.code == "OFFICIAL_SUGGESTION_SCOPE_INCOMPLETE"

    captured_payload: dict[str, object] = {}

    def import_official_url(user, payload):
        captured_payload.update(payload)
        return {
            "success": True,
            "continuation_required": True,
            "source": {"id": "source-1"},
            "job": {"id": "job-1"},
        }

    monkeypatch.setattr(service, "import_single_official_url", import_official_url)
    reviewed = service.review_official_source_suggestion(
        item["id"], tenant_id="tenant-a", user={"id": "admin"}, decision="approve",
        fields={
            "vendor": "Huawei", "product_model": "S5700", "software_release": "V200R023",
            "feature": "ospf", "url": item["suggested_url"], "source_kind": item["source_kind"],
        },
    )
    assert reviewed["status"] == "collecting"
    assert reviewed["source_registry_id"] == "source-1"
    assert reviewed["ingestion_job_id"] == "job-1"
    assert captured_payload["terms_review_status"] == "approved"


def test_single_org_suggestion_reads_cross_tenants_and_new_suggestions_use_default(isolated_db, monkeypatch) -> None:
    from api.knowledge_ingestion import api_list_official_source_suggestions, api_review_official_source_suggestion
    from core import tenant_policy
    from api.knowledge_ingestion import OfficialSourceSuggestionReviewRequest

    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", True)
    historical_a = service.record_official_source_suggestions(
        _request(), tenant_id="tenant-history-a", trace_id="rt-history-a", query="historical a",
    )[0]
    historical_b = service.record_official_source_suggestions(
        _request(), tenant_id="tenant-history-b", trace_id="rt-history-b", query="historical b",
    )[0]
    monkeypatch.setattr(tenant_policy, "TENANT_ISOLATION_ENABLED", False)

    response = api_list_official_source_suggestions(
        status="pending", search="S5700", page=1, page_size=20,
        user={"id": "reviewer", "tenant_id": "tenant-history-a", "role": "Administrator"},
    )
    reviewed = api_review_official_source_suggestion(
        historical_b["id"],
        OfficialSourceSuggestionReviewRequest(decision="reject"),
        user={"id": "reviewer", "tenant_id": "tenant-history-a", "role": "Administrator"},
    )
    newly_recorded = service.record_official_source_suggestions(
        _request(), tenant_id="tenant-history-a", trace_id="rt-new", query="new suggestion",
    )[0]

    assert {item["id"] for item in response["data"]["items"]} >= {historical_a["id"], historical_b["id"]}
    assert reviewed["data"]["status"] == "rejected"
    assert newly_recorded["tenant_id"] == "tenant-default"
