from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from main import app

import database
from api import collection_plans as collection_plans_api
from api import scheduled_jobs as scheduled_jobs_api


@pytest.fixture()
def nsot_preview_data(isolated_db):
    connection = database.get_db_connection()
    try:
        profile = connection.execute(
            """SELECT id, platform_code, current_release_id
                 FROM platform_profiles
                WHERE source = 'SYSTEM' AND platform_code = 'h3c_comware'
                ORDER BY id LIMIT 1"""
        ).fetchone()
        if not profile:
            pytest.skip("The isolated baseline has no H3C system platform profile")

        device_id = "nsot-preview-h3c-v7"
        connection.execute(
            """INSERT INTO devices (
                   id, hostname, ip_address, vendor, platform, version, status,
                   role, tenant_id, site, site_id, platform_profile_id,
                   collection_policy_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id,
                "NSOT-PREVIEW-H3C",
                "192.0.2.77",
                "H3C",
                "h3c_comware",
                "7.1.070",
                "online",
                "switch",
                "tenant-default",
                "",
                "",
                profile["id"],
                json.dumps({"template": "layer2_switch", "collectors": {}}, ensure_ascii=False),
            ),
        )
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        job_id = "nsot-preview-job"
        connection.execute(
            """INSERT INTO scheduled_jobs (
                   id, name, job_type, action_type, cron_expr, device_scope,
                   device_filter, commands, script_id, enabled, status,
                   created_by, created_at, updated_at, tenant_id
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                "NSOT preview test",
                "cron",
                "nsot",
                "0 2 * * *",
                "all",
                "",
                "",
                "",
                1,
                "approved",
                "test",
                now,
                now,
                "tenant-default",
            ),
        )
        connection.commit()
        return {
            "device_id": device_id,
            "job_id": job_id,
            "platform_profile_id": str(profile["id"]),
            "user": {"id": "nsot-preview-admin", "username": "admin", "role": "Administrator"},
        }
    finally:
        connection.close()


def test_internal_operation_catalog_keeps_template_operations(nsot_preview_data):
    context = nsot_preview_data
    operation_catalog = collection_plans_api.get_nsot_collection_operation_catalog(
        platform_profile_id=context["platform_profile_id"],
        role="switch",
        user=context["user"],
    )
    catalog_data = operation_catalog["data"]

    assert catalog_data["selected_profile"]["id"] == context["platform_profile_id"]
    assert {item["id"] for item in catalog_data["templates"]} >= {
        "role_default",
        "layer2_switch",
        "layer3_gateway",
    }
    collector_keys = {item["collector_key"] for item in catalog_data["operations"]}
    assert "mac_table" in collector_keys
    assert "vlan" in collector_keys
    # The profile catalog exposes dynamic routing operations; the device's
    # layer2_switch plan below must still keep them out of its active preview.
    assert {"eigrp", "rip"} <= collector_keys
    assert all(isinstance(item.get("action_bound"), bool) for item in catalog_data["operations"])
    assert all(
        "action_code" in command
        for operation in catalog_data["operations"]
        for command in operation["commands"]
    )
    catalog_by_key = {item["collector_key"]: item for item in catalog_data["operations"]}
    assert catalog_by_key["endpoint_location"]["status"] == "projection"
    assert catalog_by_key["prefix_projection"]["status"] == "projection"



def test_operation_catalog_requires_asset_view_scope(isolated_db):
    with pytest.raises(HTTPException) as denied:
        collection_plans_api.get_nsot_collection_operation_catalog(
            platform_profile_id=None,
            role="switch",
            user={
                "id": "tenantless-operator",
                "username": "operator",
                "role": "Operator",
                "scope_mode": "restricted",
            },
        )
    assert denied.value.status_code == 403


@pytest.mark.parametrize("action_type", ["nsot", "backup"])
def test_retired_nsot_preview_is_not_registered_for_existing_jobs(nsot_preview_data, action_type):
    context = nsot_preview_data
    connection = database.get_db_connection()
    try:
        connection.execute("UPDATE scheduled_jobs SET action_type = ? WHERE id = ?", (action_type, context["job_id"]))
        connection.commit()
    finally:
        connection.close()

    assert "/scheduled-jobs/{job_id}/nsot-preview" not in {
        route.path for route in scheduled_jobs_api.router.routes
    }
    response = TestClient(app).get(f"/api/scheduled-jobs/{context['job_id']}/nsot-preview")
    assert response.status_code == 404, response.text
    with database.get_db_connection() as connection:
        row = connection.execute(
            "SELECT action_type,enabled,status FROM scheduled_jobs WHERE id = ?", (context["job_id"],),
        ).fetchone()
        assert row["action_type"] == action_type
        assert row["enabled"] == 1
        assert row["status"] == "approved"


def test_retired_nsot_preview_does_not_expose_missing_job(isolated_db):
    assert "/scheduled-jobs/{job_id}/nsot-preview" not in {
        route.path for route in scheduled_jobs_api.router.routes
    }
    response = TestClient(app).get("/api/scheduled-jobs/no-such-job/nsot-preview")
    assert response.status_code == 404, response.text
