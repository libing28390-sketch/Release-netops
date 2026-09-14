from __future__ import annotations

from fastapi import Request

import database
from api import collection_plans as collection_plans_api
from services.collection_plan_service import collection_templates


def _request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_builtin_nsot_templates_can_be_updated_and_deleted_without_resurrection(
    isolated_db, monkeypatch
):
    monkeypatch.setattr(collection_plans_api, "log_audit_event", lambda **_event: None)
    user = {"username": "operator", "role": "Operator"}
    original_ids = {template["id"] for template in collection_templates()}

    updated = collection_plans_api.update_nsot_collection_template(
        "basic",
        collection_plans_api.NSOTCollectionTemplateRequest(
            name_zh="基础监控（已调整）",
            name_en="Basic monitoring (updated)",
            description_zh="Updated description",
            description_en="Updated description",
            collector_keys=["interface_status"],
        ),
        _request("PUT", "/collection-plans/templates/basic"),
        user=user,
    )

    assert updated["data"]["builtin"] is True
    assert updated["data"]["editable"] is True
    assert updated["data"]["deletable"] is True
    assert updated["data"]["name_zh"] == "基础监控（已调整）"
    assert updated["data"]["collector_keys"] == ["interface_status"]

    for template_id in original_ids:
        collection_plans_api.delete_nsot_collection_template(
            template_id,
            _request("DELETE", f"/collection-plans/templates/{template_id}"),
            user=user,
        )

    connection = database.get_db_connection()
    try:
        assert collection_templates(connection) == []
    finally:
        connection.close()
    assert collection_plans_api.list_nsot_collection_templates()["data"] == []
