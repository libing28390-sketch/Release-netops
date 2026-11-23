from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import cmdb
from services import interface_collection_service, rack_scope_service


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.closed = False

    def execute(self, _sql, _params=()):
        return _Result(self.row)

    def close(self):
        self.closed = True


def _device_row():
    return {
        "device_id": "dev-outside-site",
        "asset_id": "asset-outside-site",
        "device_group_id": "group-ops",
        "site_tenant_id": "tenant-b",
        "site_id": "site-b",
    }


def test_snmp_refresh_checks_actual_device_scope_before_collection(monkeypatch):
    conn = _Connection(_device_row())
    monkeypatch.setattr(cmdb, "get_db_connection", lambda: conn)
    refresh_calls = []
    monkeypatch.setattr(
        interface_collection_service,
        "refresh_snmp_interface_status",
        lambda device_id: refresh_calls.append(device_id),
    )
    authorized_resources = []

    def deny(user, resource, resource_type, action):
        authorized_resources.append((user, resource, resource_type, action))
        raise HTTPException(status_code=403, detail="scope denied")

    monkeypatch.setattr(rack_scope_service, "enforce_loaded_resource", deny)

    with pytest.raises(HTTPException) as error:
        cmdb.api_refresh_device_interfaces_snmp(
            "dev-outside-site",
            user={"id": "operator-1", "role": "Operator"},
        )

    assert error.value.status_code == 403
    assert conn.closed is True
    assert refresh_calls == []
    assert authorized_resources[0][1]["site_id"] == "site-b"
    assert authorized_resources[0][1]["site_tenant_id"] == "tenant-b"
    assert authorized_resources[0][1]["device_group_id"] == "group-ops"
    assert authorized_resources[0][2:] == ("asset", "update")


def test_snmp_refresh_preserves_the_authorized_manual_workflow(monkeypatch):
    conn = _Connection(_device_row())
    monkeypatch.setattr(cmdb, "get_db_connection", lambda: conn)
    authorized_resources = []
    monkeypatch.setattr(
        rack_scope_service,
        "enforce_loaded_resource",
        lambda user, resource, resource_type, action: authorized_resources.append(
            (user, resource, resource_type, action)
        ),
    )
    refresh_calls = []
    monkeypatch.setattr(
        interface_collection_service,
        "refresh_snmp_interface_status",
        lambda device_id: refresh_calls.append(device_id) or {"hostname": "edge-1"},
    )
    monkeypatch.setattr(cmdb, "log_audit_event", lambda **_kwargs: None)

    result = cmdb.api_refresh_device_interfaces_snmp(
        "dev-outside-site",
        user={"id": "operator-1", "role": "Operator"},
    )

    assert result == {"success": True, "data": {"hostname": "edge-1"}}
    assert conn.closed is True
    assert refresh_calls == ["dev-outside-site"]
    assert authorized_resources[0][2:] == ("asset", "update")


def test_snmp_refresh_device_group_grant_is_checked_against_the_loaded_device(isolated_db, make_user):
    from database import get_db_connection

    user = make_user("cmdb_snmp_group_scope", role="Operator", tenant_id="tenant-default")
    conn = get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices (id, hostname, site_id, tenant_id, device_group_id)
               VALUES (?, ?, ?, ?, ?)""",
            ("group-device-a", "edge-a", "site-b", "tenant-default", "group-a"),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, site_id, tenant_id, device_group_id)
               VALUES (?, ?, ?, ?, ?)""",
            ("group-device-b", "edge-b", "site-b", "tenant-default", "group-b"),
        )
        conn.execute(
            """INSERT INTO user_resource_scopes
                   (id, user_id, resource_type, scope_type, scope_id, actions_json, created_at)
               VALUES (?, ?, 'asset', 'device_group', 'group-a', ?, ?)""",
            (
                "scope-cmdb-group-a",
                user["user_id"],
                json.dumps(["update"]),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

        cmdb._enforce_cmdb_device_scope(conn, user, "group-device-a", "update")
        with pytest.raises(HTTPException) as error:
            cmdb._enforce_cmdb_device_scope(conn, user, "group-device-b", "update")
    finally:
        conn.close()

    assert error.value.status_code == 403
