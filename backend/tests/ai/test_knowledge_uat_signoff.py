from __future__ import annotations

import pytest

from core.rbac import authorize_resource
from services import knowledge_uat_service as service


def test_uat_catalog_is_four_vendor_case_scoped_and_pending_by_default(isolated_db) -> None:
    data = service.list_uat_cases(tenant_id="tenant-a", suite="UAT-01")

    assert data["total"] == 20
    assert data["summary"]["total"] == 20
    assert data["summary"]["pending"] == 20
    assert data["summary"]["signed"] == 0
    assert {item["vendor"] for item in data["items"]} == {"Huawei", "Cisco", "H3C", "锐捷"}
    assert all(item["signoff_status"] == "pending" for item in data["items"])


def test_uat_signoff_is_server_owned_tenant_scoped_and_audited(isolated_db) -> None:
    result = service.sign_uat_case(
        "UAT-HUA-01",
        tenant_id="tenant-a",
        user={"id": "reviewer-1", "username": "release-reviewer"},
        decision="approved",
        comment="浏览器终态、官方来源和安全边界符合验收要求。",
    )

    assert result["item"]["signoff_status"] == "approved"
    assert result["item"]["reviewer_id"] == "reviewer-1"
    assert result["item"]["reviewer_name"] == "release-reviewer"
    assert result["item"]["signed_at"]
    assert result["item"]["history_count"] == 1
    assert result["summary"]["approved"] == 1

    history = service.list_uat_case_history("UAT-HUA-01", tenant_id="tenant-a")
    assert len(history) == 1
    assert history[0]["previous_status"] == "pending"
    assert history[0]["new_status"] == "approved"
    assert history[0]["reviewer_id"] == "reviewer-1"

    other_tenant = service.list_uat_cases(tenant_id="tenant-b", suite="UAT-01")
    assert other_tenant["summary"]["pending"] == 20
    assert other_tenant["items"][0]["signoff_status"] == "pending"


def test_uat_partial_and_rejected_signoffs_require_reason(isolated_db) -> None:
    with pytest.raises(service.KnowledgeUATError) as partial_error:
        service.sign_uat_case(
            "UAT-CISCO-01",
            tenant_id="tenant-a",
            user={"id": "reviewer-1"},
            decision="partial",
        )
    assert partial_error.value.code == "UAT_COMMENT_REQUIRED"

    with pytest.raises(service.KnowledgeUATError) as rejected_error:
        service.sign_uat_case(
            "UAT-CISCO-01",
            tenant_id="tenant-a",
            user={"id": "reviewer-1"},
            decision="rejected",
        )
    assert rejected_error.value.code == "UAT_COMMENT_REQUIRED"


def test_only_release_manager_or_administrator_can_sign_uat() -> None:
    viewer = {"id": "viewer-1", "role": "Viewer", "tenant_id": "tenant-a"}
    operator = {"id": "operator-1", "role": "Operator", "tenant_id": "tenant-a"}
    reviewer = {"id": "reviewer-1", "role": "Operator", "role_profile": "Release Manager", "tenant_id": "tenant-a"}
    administrator = {"id": "admin-1", "role": "Administrator", "tenant_id": "tenant-a"}

    assert not authorize_resource(viewer, "knowledge_uat", "sign", tenant_id="tenant-a")
    assert not authorize_resource(operator, "knowledge_uat", "sign", tenant_id="tenant-a")
    assert authorize_resource(reviewer, "knowledge_uat", "sign", tenant_id="tenant-a")
    assert authorize_resource(administrator, "knowledge_uat", "sign", tenant_id="tenant-a")
