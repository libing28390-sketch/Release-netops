from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _actor(user: dict) -> dict:
    return {
        "id": user["user_id"],
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "tenant_id": user.get("tenant_id") or "tenant-default",
    }


def _client(monkeypatch, actors: dict[str, dict]) -> TestClient:
    from api import users as users_api
    from main import app

    monkeypatch.setattr(users_api, "validate_session_token", lambda token: actors.get(token))
    return TestClient(app)


def test_emergency_review_is_restricted_to_designated_independent_reviewer(
    isolated_db, make_user, monkeypatch,
):
    from services.change_order_service import create_change_order, get_change_order

    database = isolated_db["module"]
    requester = make_user("m5-emergency-requester", tenant_id="tenant-default")
    implementer = make_user("m5-emergency-implementer", tenant_id="tenant-default")
    reviewer = make_user("m5-emergency-reviewer", role="Administrator", tenant_id="tenant-default")
    other_admin = make_user("m5-emergency-other-admin", role="Administrator", tenant_id="tenant-default")
    due = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    conn = database.get_db_connection()
    try:
        order = create_change_order(
            conn,
            title="Emergency edge recovery",
            description="M5 post-review test",
            order_type="emergency",
            status="implementing",
            requester_id=requester["user_id"],
            requester_username=requester["username"],
            tenant_id="tenant-default",
            emergency_reason="Core service interruption requires immediate recovery",
            emergency_review_owner_id=reviewer["user_id"],
            emergency_review_due_at=due,
            control_sheet={
                "implementer": {
                    "id": implementer["user_id"],
                    "username": implementer["username"],
                },
            },
            commit=False,
        )
        conn.execute(
            "UPDATE change_orders SET actual_start = ?, status = 'implementing' WHERE id = ?",
            (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), order["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    client = _client(monkeypatch, {
        "reviewer-token": _actor(reviewer),
        "other-token": _actor(other_admin),
    })
    premature = client.post(
        f"/api/change-orders/{order['id']}/emergency-review",
        headers={"Authorization": "Bearer reviewer-token"},
        json={"outcome": "accepted", "note": "reviewed before execution ended"},
    )
    assert premature.status_code == 409

    conn = database.get_db_connection()
    try:
        conn.execute(
            "UPDATE change_orders SET status = 'completed', actual_end = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), order["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    denied = client.post(
        f"/api/change-orders/{order['id']}/emergency-review",
        headers={"Authorization": "Bearer other-token"},
        json={"outcome": "accepted", "note": "reviewed"},
    )
    assert denied.status_code == 403

    accepted = client.post(
        f"/api/change-orders/{order['id']}/emergency-review",
        headers={"Authorization": "Bearer reviewer-token"},
        json={"outcome": "accepted", "note": "Restoration verified against service health checks."},
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()["order"]
    assert body["status"] == "completed"
    assert body["emergency_review_status"] == "accepted"
    assert body["emergency_reviewed_by_id"] == reviewer["user_id"]
    assert body["emergency_review_note"]
    assert body["result_detail"]["emergency_post_review"]["outcome"] == "accepted"

    repeated = client.post(
        f"/api/change-orders/{order['id']}/emergency-review",
        headers={"Authorization": "Bearer reviewer-token"},
        json={"outcome": "follow_up_required", "note": "duplicate"},
    )
    assert repeated.status_code == 409

    read_conn = database.get_db_connection()
    try:
        saved = get_change_order(read_conn, order["id"])
    finally:
        read_conn.close()
    assert saved["emergency_review_status"] == "accepted"


def test_emergency_approval_snapshot_binds_reason_reviewer_and_deadline():
    from api.change_orders.helpers import approval_snapshot_hash

    order = {
        "title": "Emergency change",
        "requester_id": "requester-1",
        "order_type": "emergency",
        "emergency_reason": "Restore core traffic",
        "emergency_review_owner_id": "reviewer-1",
        "emergency_review_due_at": "2030-01-01T00:00:00Z",
        "target_devices": [{"id": "device-1"}],
        "commands": ["show version"],
    }
    base = approval_snapshot_hash(order)
    for field, value in (
        ("emergency_reason", "Different outage reason"),
        ("emergency_review_owner_id", "reviewer-2"),
        ("emergency_review_due_at", "2030-01-02T00:00:00Z"),
    ):
        changed = {**order, field: value}
        assert approval_snapshot_hash(changed) != base
