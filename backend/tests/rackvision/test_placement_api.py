"""HTTP contract tests for the canonical RackVision placement endpoints."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx

from api import users
from main import app
from services import rack_service


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, **kwargs)

    return asyncio.run(run())


def _operator_user(monkeypatch) -> dict:
    user = {
        "user_id": "rackvision-operator",
        "id": "rackvision-operator",
        "username": "rackvision-operator",
        "role": "Operator",
        "tenant_id": "tenant-default",
    }
    monkeypatch.setattr(users, "validate_session_token", lambda token: user)
    return user


def _fixture_rack(isolated_db) -> tuple[str, str, str]:
    conn = isolated_db["module"].get_db_connection()
    try:
        rack = rack_service.create_rack(
            conn,
            name=_id("api-rack"),
            site_id="site-default",
            total_u=42,
            rack_code=_id("api-code"),
        )
        device_type = rack_service.create_device_type(
            conn,
            model=_id("api-switch"),
            vendor="RackVision",
            u_height=2,
            device_role="switch",
            default_mount_kind="u_mount",
        )
        return rack["id"], device_type["id"], rack["name"]
    finally:
        conn.close()


def test_canonical_placement_http_lifecycle_and_stable_errors(isolated_db, monkeypatch):
    _operator_user(monkeypatch)
    rack_id, device_type_id, _ = _fixture_rack(isolated_db)
    headers = {
        "Authorization": "Bearer operator-token",
        "X-Request-ID": "rackvision-placement-test",
    }

    create = _request(
        "POST",
        f"/api/racks/{rack_id}/placements",
        headers=headers,
        json={
            "name": "API lifecycle device",
            "device_type_id": device_type_id,
            "start_u": 10,
            "position": "front",
        },
    )
    assert create.status_code == 201, create.text
    created_payload = create.json()
    assert created_payload["success"] is True
    placement_id = created_payload["data"]["id"]
    assert created_payload["data"]["mount_kind"] == "u_mount"
    assert created_payload["data"]["height_u"] == 2

    validate = _request(
        "POST",
        f"/api/racks/{rack_id}/validate-placement",
        headers=headers,
        json={
            "device_type_id": device_type_id,
            "start_u": 11,
            "position": "front",
        },
    )
    assert validate.status_code == 200, validate.text
    validate_payload = validate.json()
    assert validate_payload["success"] is False
    assert validate_payload["data"]["valid"] is False
    assert validate_payload["error"]["code"] == "RACK_U_CONFLICT"

    conflict = _request(
        "POST",
        f"/api/racks/{rack_id}/placements",
        headers=headers,
        json={
            "name": "API conflicting device",
            "device_type_id": device_type_id,
            "start_u": 11,
            "position": "front",
        },
    )
    assert conflict.status_code == 409, conflict.text
    conflict_payload = conflict.json()
    assert conflict_payload["success"] is False
    assert conflict_payload["error"]["code"] == "RACK_U_CONFLICT"
    assert conflict_payload["error"]["request_id"] == "rackvision-placement-test"
    assert conflict.headers["X-Request-ID"] == "rackvision-placement-test"

    move = _request(
        "PATCH",
        f"/api/rack-placements/{placement_id}",
        headers=headers,
        json={"start_u": 20},
    )
    assert move.status_code == 200, move.text
    assert move.json()["data"]["start_u"] == 20

    delete = _request(
        "DELETE",
        f"/api/rack-placements/{placement_id}",
        headers=headers,
    )
    assert delete.status_code == 200, delete.text
    assert delete.json()["success"] is True


def test_placement_api_rejects_scope_mismatch_and_unknown_rack(isolated_db, monkeypatch):
    _operator_user(monkeypatch)
    rack_id, device_type_id, _ = _fixture_rack(isolated_db)
    headers = {"Authorization": "Bearer operator-token"}

    mismatch = _request(
        "POST",
        f"/api/racks/{rack_id}/placements",
        headers=headers,
        json={
            "rack_id": "different-rack",
            "name": "wrong scope",
            "device_type_id": device_type_id,
            "start_u": 1,
        },
    )
    assert mismatch.status_code == 409, mismatch.text
    mismatch_payload = mismatch.json()
    assert mismatch_payload["success"] is False
    assert mismatch_payload["error"]["code"] == "RACK_SCOPE_MISMATCH"

    missing = _request(
        "GET",
        "/api/racks/rack-does-not-exist/devices",
        headers=headers,
    )
    assert missing.status_code == 404, missing.text
    missing_payload = missing.json()
    assert missing_payload["success"] is False
    assert missing_payload["error"]["code"] == "RACK_NOT_FOUND"


def test_canonical_placement_rejects_unknown_asset_reference(isolated_db, monkeypatch):
    _operator_user(monkeypatch)
    rack_id, device_type_id, _ = _fixture_rack(isolated_db)
    response = _request(
        "POST",
        f"/api/racks/{rack_id}/placements",
        headers={"Authorization": "Bearer operator-token"},
        json={
            "name": "unknown-asset-placement",
            "device_type_id": device_type_id,
            "start_u": 3,
            "asset_id": _id("missing-asset"),
        },
    )
    assert response.status_code == 404, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "ASSET_NOT_FOUND"


def test_legacy_rack_name_resolution_rejects_ambiguous_name(isolated_db, monkeypatch):
    _operator_user(monkeypatch)
    conn = isolated_db["module"].get_db_connection()
    try:
        sites = (
            ("ambiguous-site-a", "AMB_A", "Ambiguous Site A"),
            ("ambiguous-site-b", "AMB_B", "Ambiguous Site B"),
        )
        for site_id, site_code, site_name in sites:
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                (site_id, site_code, site_name, "tenant-default"),
            )
        conn.commit()
        for index, (site_id, _site_code, _site_name) in enumerate(sites):
            rack_service.create_rack(
                conn,
                name="ambiguous-rack-name",
                site_id=site_id,
                rack_code=_id(f"ambiguous-{index}"),
            )
    finally:
        conn.close()

    response = _request(
        "GET",
        "/api/racks/validate-u",
        params={"rack": "ambiguous-rack-name", "start_u": 10, "u_height": 1},
        headers={"Authorization": "Bearer operator-token"},
    )
    assert response.status_code == 409, response.text
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "RACK_NOT_UNIQUE"


def test_rack_list_and_detail_are_tenant_and_site_scoped(isolated_db, make_user, monkeypatch):
    conn = isolated_db["module"].get_db_connection()
    try:
        for tenant_id, name in (("tenant-rack-a", "Rack Tenant A"), ("tenant-rack-b", "Rack Tenant B")):
            conn.execute(
                "INSERT INTO tenants (id, name, description) VALUES (?, ?, ?)",
                (tenant_id, name, name),
            )
        sites = (
            ("site-rack-a", "RACK_A", "Rack Site A", "tenant-rack-a"),
            ("site-rack-a2", "RACK_A2", "Rack Site A2", "tenant-rack-a"),
            ("site-rack-b", "RACK_B", "Rack Site B", "tenant-rack-b"),
        )
        for site in sites:
            conn.execute(
                """INSERT INTO sites (id, site_code, site_name, status, tenant_id)
                   VALUES (?, ?, ?, 'active', ?)""",
                site,
            )
        conn.commit()

        racks = {
            site_id: rack_service.create_rack(
                conn,
                name=f"Rack for {site_id}",
                site_id=site_id,
                rack_code=_id(f"code-{site_id}"),
            )
            for site_id, _, _, _ in sites
        }
        user = make_user("rack-scope-viewer", role="Viewer")
        conn.execute(
            "UPDATE users SET tenant_id = ? WHERE id = ?",
            ("tenant-rack-a", user["user_id"]),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes (
                   id, user_id, resource_type, scope_type, scope_id,
                   actions_json, created_at
               ) VALUES (?, ?, 'rack', 'site', ?, ?, CURRENT_TIMESTAMP)""",
            (
                _id("scope"),
                user["user_id"],
                "site-rack-a",
                json.dumps(["view"]),
            ),
        )
        conn.commit()
        user_payload = {
            "user_id": user["user_id"],
            "id": user["user_id"],
            "username": "rack-scope-viewer",
            "role": "Viewer",
            "tenant_id": "tenant-rack-a",
        }
        monkeypatch.setattr(users, "validate_session_token", lambda token: user_payload)
    finally:
        conn.close()

    headers = {"Authorization": "Bearer scoped-viewer-token"}
    listed = _request("GET", "/api/racks", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["data"]] == [racks["site-rack-a"]["id"]]

    summary = _request("GET", "/api/racks/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert [item["id"] for item in summary.json()["data"]["items"]] == [racks["site-rack-a"]["id"]]

    visible = _request("GET", f"/api/racks/{racks['site-rack-a']['id']}", headers=headers)
    assert visible.status_code == 200, visible.text

    cross_tenant = _request("GET", f"/api/racks/{racks['site-rack-b']['id']}", headers=headers)
    assert cross_tenant.status_code == 403, cross_tenant.text
    assert cross_tenant.json()["success"] is False
    assert cross_tenant.json()["error"]["code"] == "RESOURCE_SCOPE_DENIED"

    same_tenant_but_unscoped = _request("GET", f"/api/racks/{racks['site-rack-a2']['id']}", headers=headers)
    assert same_tenant_but_unscoped.status_code == 403, same_tenant_but_unscoped.text
