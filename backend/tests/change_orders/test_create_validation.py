from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


def test_create_route_runs_change_requester_dependency_before_handler(monkeypatch):
    from api import users as users_api
    from main import app

    monkeypatch.setattr(users_api, "validate_session_token", lambda _token: None)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/change-orders", json={"title": "Dependency injection regression"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_authenticated_requester_can_create_change_order_and_persist_rollback_plan(
    isolated_db, make_user, monkeypatch,
):
    from api import users as users_api
    from main import app
    from services.change_order_service import get_change_order

    requester = make_user("change-create-requester", tenant_id="tenant-default")
    result_reviewer = make_user("change-create-result-reviewer", role="Viewer", tenant_id="tenant-default")
    actor = {
        "id": requester["user_id"],
        "user_id": requester["user_id"],
        "username": requester["username"],
        "role": requester["role"],
        "tenant_id": requester["tenant_id"],
    }
    monkeypatch.setattr(users_api, "validate_session_token", lambda token: actor if token == "requester-token" else None)
    client = TestClient(app)

    response = client.post(
        "/api/change-orders",
        headers={"Authorization": "Bearer requester-token"},
        json={
            "title": "Create route dependency regression",
            "status": "draft",
            "rollback_plan": "Restore the previous interface configuration.",
            "control_sheet": {
                "implementer": {"id": requester["user_id"], "username": requester["username"]},
                "co_reviewer": {"id": result_reviewer["user_id"], "username": result_reviewer["username"]},
                "rollback_plan": "Restore the previous interface configuration.",
            },
        },
    )

    assert response.status_code == 200, response.text
    order_id = response.json()["data"]["id"]
    connection = isolated_db["module"].get_db_connection()
    try:
        saved = get_change_order(connection, order_id)
    finally:
        connection.close()
    assert saved["rollback_plan"] == "Restore the previous interface configuration."
    assert saved["control_sheet"]["rollback_plan"] == "Restore the previous interface configuration."


def test_update_change_order_authorization_exempt_uses_integer_for_postgresql(isolated_db):
    from services.change_order_service import create_change_order, get_change_order, update_change_order

    connection = isolated_db["module"].get_db_connection()
    try:
        order = create_change_order(
            connection,
            title="Authorization exemption type regression",
            status="draft",
            authorization_exempt=False,
        )

        updated = update_change_order(connection, order["id"], {"authorization_exempt": True})
        assert updated["authorization_exempt"] is True
        stored_value = connection.execute(
            "SELECT authorization_exempt FROM change_orders WHERE id = ?",
            (order["id"],),
        ).fetchone()
        assert dict(stored_value)["authorization_exempt"] == 1

        reverted = update_change_order(connection, order["id"], {"authorization_exempt": False})
        assert reverted["authorization_exempt"] is False
        assert get_change_order(connection, order["id"])["authorization_exempt"] is False
    finally:
        connection.close()


def test_initial_review_requires_control_sheet_even_when_feature_flag_is_disabled(
    isolated_db, make_user, monkeypatch,
):
    from api import change_orders as change_orders_api
    from api import users as users_api
    from main import app

    requester = make_user("change-create-control-sheet-requester", tenant_id="tenant-default")
    reviewer = make_user(
        "change-create-control-sheet-reviewer",
        role="Administrator",
        change_groups=["initial_reviewer"],
        tenant_id="tenant-default",
    )
    actor = {
        "id": requester["user_id"],
        "user_id": requester["user_id"],
        "username": requester["username"],
        "role": requester["role"],
        "tenant_id": requester["tenant_id"],
    }
    monkeypatch.setattr(users_api, "validate_session_token", lambda token: actor if token == "requester-token" else None)
    monkeypatch.setattr(change_orders_api, "FEATURE_CONTROL_SHEET", False)
    client = TestClient(app)

    response = client.post(
        "/api/change-orders",
        headers={"Authorization": "Bearer requester-token"},
        json={
            "title": "Control sheet required before review",
            "status": "initial_review",
            "assigned_initial_reviewer_id": reviewer["user_id"],
        },
    )

    assert response.status_code == 400
    assert "必须填写完整的变更控制表" in response.json()["detail"]


def test_initial_reviewer_must_be_an_administrator_in_the_initial_review_group(
    isolated_db, make_user,
):
    from api.change_orders.helpers import _resolve_assignment_user

    operator = make_user("initial-review-operator", role="Operator", change_groups=["initial_reviewer"])
    administrator = make_user(
        "initial-review-administrator",
        role="Administrator",
        change_groups=["initial_reviewer"],
    )
    connection = isolated_db["module"].get_db_connection()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _resolve_assignment_user(connection, operator["user_id"], "initial")
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Initial reviewer must be an Administrator"
        assert _resolve_assignment_user(connection, administrator["user_id"], "initial")["id"] == administrator["user_id"]
    finally:
        connection.close()


def test_operator_cannot_process_initial_review_even_if_previously_assigned(
    isolated_db, make_user, monkeypatch,
):
    from api import users as users_api
    from main import app
    from services.change_order_service import create_change_order

    requester = make_user("initial-review-requester", role="Administrator", tenant_id="tenant-default")
    operator = make_user(
        "initial-review-assigned-operator",
        role="Operator",
        change_groups=["initial_reviewer"],
        tenant_id="tenant-default",
    )
    final_approver = make_user(
        "initial-review-final-approver",
        role="Administrator",
        change_groups=["final_approver"],
        tenant_id="tenant-default",
    )
    connection = isolated_db["module"].get_db_connection()
    try:
        order = create_change_order(
            connection,
            title="Assigned operator cannot review",
            description="",
            status="initial_review",
            requester_id=requester["user_id"],
            requester_username=requester["username"],
            tenant_id=requester["tenant_id"],
            assigned_initial_reviewer_id=operator["user_id"],
            assigned_initial_reviewer_username=operator["username"],
            commit=False,
        )
        connection.commit()
    finally:
        connection.close()

    operator_actor = {
        "id": operator["user_id"],
        "user_id": operator["user_id"],
        "username": operator["username"],
        "role": operator["role"],
        "tenant_id": operator["tenant_id"],
    }
    monkeypatch.setattr(users_api, "validate_session_token", lambda token: operator_actor if token == "operator-token" else None)
    client = TestClient(app)
    response = client.post(
        f"/api/change-orders/{order['id']}/transition",
        headers={"Authorization": "Bearer operator-token"},
        json={"status": "final_review", "assigned_final_approver_id": final_approver["user_id"]},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "只有管理员角色的用户才能处理初审"


def test_initial_review_control_sheet_requires_real_assignments_and_verification_text():
    from api.change_orders.helpers import _validate_control_sheet_completeness

    payload = {
        "control_sheet": {
            "change_time": {"start": "2026-10-26 01:00", "end": "2026-10-26 02:00"},
            "implementer": {"id": "", "username": ""},
            "co_reviewer": {"id": "reviewer-1", "username": "reviewer"},
            "device_ips": ["192.0.2.10"],
            "pre_check": "show interface brief",
            "execution": "",
            "post_verify": "show interface brief",
            "business_verify": "service owner confirms connectivity",
            "rollback_plan": "undo interface description",
        },
    }

    with pytest.raises(HTTPException) as exc_info:
        _validate_control_sheet_completeness(None, None, payload, "initial_review")

    assert exc_info.value.status_code == 400
    assert "实施人" in exc_info.value.detail
    assert "人工实施步骤" in exc_info.value.detail

    complete_payload = {
        "control_sheet": {
            **payload["control_sheet"],
            "implementer": {"id": "implementer-1", "username": "engineer"},
            "execution": "Apply the approved change manually on the target device.",
        },
    }
    assert _validate_control_sheet_completeness(None, None, complete_payload, "initial_review") is None


@pytest.mark.parametrize(
    ("assignment", "message"),
    [
        (
            {
                "control_sheet": {
                    "implementer": {"id": "same-user", "username": "engineer"},
                    "co_reviewer": {"id": "same-user", "username": "engineer"},
                },
            },
            "复核人不能与实施人相同",
        ),
        (
            {
                "control_sheet": {
                    "implementer": {"id": "same-user", "username": "engineer"},
                    "business_confirmer": {"id": "same-user", "username": "engineer"},
                },
            },
            "实施人不能同时担任业务确认人",
        ),
        (
            {
                "control_sheet": {"implementer": {"id": "same-user", "username": "engineer"}},
                "assigned_initial_reviewer_id": "same-user",
                "assigned_initial_reviewer_username": "engineer",
            },
            "实施人不能同时担任初审人",
        ),
        (
            {
                "control_sheet": {"implementer": {"id": "same-user", "username": "engineer"}},
                "assigned_final_approver_id": "same-user",
                "assigned_final_approver_username": "engineer",
            },
            "实施人不能同时担任终审人",
        ),
    ],
)
def test_implementer_cannot_be_assigned_to_review_or_business_confirmation(assignment, message):
    from api.change_orders.helpers import _validate_assignment_rules

    with pytest.raises(HTTPException) as exc_info:
        _validate_assignment_rules("requester", assignment)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == message


def test_implementer_and_co_reviewer_username_fallback_is_case_insensitive():
    from api.change_orders.helpers import _validate_assignment_rules

    with pytest.raises(HTTPException) as exc_info:
        _validate_assignment_rules("requester", {
            "control_sheet": {
                "implementer": {"username": "NetworkEngineer"},
                "co_reviewer": {"username": "networkengineer"},
            },
        })

    assert exc_info.value.detail == "复核人不能与实施人相同"


def test_distinct_implementer_and_reviewers_are_allowed():
    from api.change_orders.helpers import _validate_assignment_rules

    _validate_assignment_rules("requester", {
        "control_sheet": {
            "implementer": {"id": "engineer-id", "username": "engineer"},
            "co_reviewer": {"id": "reviewer-id", "username": "reviewer"},
            "business_confirmer": {"id": "owner-id", "username": "service-owner"},
        },
        "assigned_initial_reviewer_id": "initial-id",
        "assigned_initial_reviewer_username": "initial-reviewer",
        "assigned_final_approver_id": "final-id",
        "assigned_final_approver_username": "final-approver",
    })
