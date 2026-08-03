from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.platform_registry import (
    PlatformActionRequest,
    PlatformActionUpdateRequest,
    PlatformBatchBindingRequest,
    PlatformProfileCreateRequest,
    PlatformReleaseCreateRequest,
    PlatformRollbackRequest,
    _require_registry_enabled,
)
from core.rbac import authorize_resource, permission_catalog, RECOMMENDED_ROLE_PROFILES
from services.platform_registry_service import preview_platform_migration


def test_registry_write_and_execution_gate_is_closed_by_default(monkeypatch):
    monkeypatch.delenv("PLATFORM_REGISTRY_ENABLED", raising=False)
    with pytest.raises(HTTPException) as error:
        _require_registry_enabled()
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "PLATFORM_REGISTRY_DISABLED"


def test_registry_write_and_execution_gate_can_be_enabled(monkeypatch):
    monkeypatch.setenv("PLATFORM_REGISTRY_ENABLED", "1")
    _require_registry_enabled()


def test_platform_write_request_models_reject_unknown_fields_and_bound_values():
    profile = PlatformProfileCreateRequest(
        platform_code="tenant_edge",
        connection_driver="netmiko",
        parser_platform="tenant_edge",
    )
    assert profile.model_dump()["platform_code"] == "tenant_edge"
    assert PlatformReleaseCreateRequest().safety_policy == {"read_only": True}
    assert PlatformRollbackRequest(release_id="release-1").release_id == "release-1"
    assert PlatformActionUpdateRequest(command="show version").command == "show version"

    with pytest.raises(ValidationError):
        PlatformProfileCreateRequest(
            platform_code="tenant_edge",
            connection_driver="netmiko",
            parser_platform="tenant_edge",
            unexpected="reject-me",
        )
    with pytest.raises(ValidationError):
        PlatformActionRequest(device_id="device-1", action_code="bad-action", parameters={})


def test_platform_binding_request_models_normalize_and_reject_duplicate_batches():
    request = PlatformBatchBindingRequest(
        device_ids=[" device-1 ", "device-2"],
        platform_profile_id="profile-1",
    )
    assert request.device_ids == ["device-1", "device-2"]

    with pytest.raises(ValidationError):
        PlatformBatchBindingRequest(
            device_ids=["device-1", " device-1"],
            platform_profile_id="profile-1",
        )


def test_operator_cannot_approve_publish_or_rollback_resources():
    operator = {"id": "operator-1", "username": "operator", "role": "Operator", "tenant_id": "tenant-1"}
    assert authorize_resource(operator, "playbook", "execute", tenant_id="tenant-1")
    assert authorize_resource(operator, "playbook", "submit", tenant_id="tenant-1")
    assert not authorize_resource(operator, "playbook", "approve", tenant_id="tenant-1")
    assert not authorize_resource(operator, "platform", "publish", tenant_id="tenant-1")
    assert not authorize_resource(operator, "platform", "rollback", tenant_id="tenant-1")


def test_permission_catalog_exposes_reviewed_resource_actions_and_roles():
    catalog = permission_catalog()
    assert catalog["platform"] == ["approve", "bind_device", "create", "edit_draft", "publish", "rollback", "submit", "view"]
    assert catalog["sample_output"] == ["delete", "upload", "view"]
    assert "Template Developer" in RECOMMENDED_ROLE_PROFILES
    assert "Release Manager" in RECOMMENDED_ROLE_PROFILES
    assert "Scheduler Administrator" in RECOMMENDED_ROLE_PROFILES


def test_named_profiles_separate_authoring_review_and_schedule_permissions():
    author = {"id": "author-1", "role": "Operator", "role_profile": "Platform Maintainer"}
    reviewer = {"id": "reviewer-1", "role": "Operator", "role_profile": "Release Manager"}
    scheduler = {"id": "scheduler-1", "role": "Operator", "role_profile": "Scheduler Administrator"}
    operator = {"id": "operator-2", "role": "Operator", "role_profile": "Automation Operator"}

    assert authorize_resource(author, "platform", "create")
    assert not authorize_resource(author, "platform", "publish")
    assert authorize_resource(reviewer, "platform", "approve")
    assert authorize_resource(reviewer, "platform", "publish")
    assert authorize_resource(scheduler, "playbook", "schedule")
    assert not authorize_resource(scheduler, "playbook", "execute")
    assert authorize_resource(operator, "playbook", "execute")
    assert not authorize_resource(operator, "playbook", "schedule")


def test_migration_preview_is_read_only_and_reports_legacy_conflicts(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    conn.execute(
        "INSERT INTO devices (id, hostname, platform, tenant_id, platform_source, platform_locked) VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy-preview-device", "legacy-edge", "unknown_vendor_os", "tenant-preview", "LEGACY", 0),
    )
    conn.commit()

    preview = preview_platform_migration({"id": "admin-1", "role": "Administrator"})

    assert preview["read_only"] is True
    assert preview["legacy_compatibility_unchanged"] is True
    assert preview["devices"]["unknown_platform_values"] == 1
    assert any(item["kind"] == "UNKNOWN_PLATFORM" for item in preview["device_conflicts"])
    assert preview["summary"]["conflict_count"] >= 1
    assert conn.execute("SELECT platform_profile_id FROM devices WHERE id = ?", ("legacy-preview-device",)).fetchone()[0] in (None, "")
    conn.close()
