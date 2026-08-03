from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.platform_registry import _require_registry_enabled
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
