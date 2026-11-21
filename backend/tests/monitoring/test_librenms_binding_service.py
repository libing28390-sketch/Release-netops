from __future__ import annotations

import asyncio
from typing import Any

import database
from services import librenms_binding_service as binding_service


def _insert_target(
    conn,
    device_id: str,
    asset_id: str,
    ip: str,
    *,
    asset_ip: str | None = None,
    tenant_id: str = "tenant-1",
) -> None:
    conn.execute(
        """INSERT INTO physical_assets
           (id, asset_type, hostname, management_ip, created_at, updated_at)
           VALUES (?, 'network_device', ?, ?, '2026-01-01', '2026-01-01')""",
        (asset_id, device_id, asset_ip or ip),
    )
    conn.execute(
        """INSERT INTO devices (id, hostname, ip_address, asset_id, tenant_id)
           VALUES (?, ?, ?, ?, ?)""",
        (device_id, device_id, ip, asset_id, tenant_id),
    )


def _insert_instance(conn) -> None:
    conn.execute(
        """INSERT INTO credentials (id, credential_type, encrypted_password)
           VALUES ('lnms-api-token', 'api_token', 'encrypted-test-token')"""
    )
    conn.execute(
        """INSERT INTO librenms_instances
           (id, display_name, base_url, token_credential_id, enabled, health_state)
           VALUES ('instance-1', 'LibreNMS', 'https://librenms.example', 'lnms-api-token', TRUE, 'healthy')"""
    )


def _fake_client(monkeypatch, *, devices: list[dict[str, Any]], addresses: list[dict[str, Any]]):
    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, base_url: str, token: str) -> None:
            assert base_url == "https://librenms.example"
            assert token == "unit-test-token"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_devices(self, *, device_type: str, query: str, max_rows: int):
            calls.append((device_type, query))
            assert query == "192.0.2.10"
            assert max_rows == 200
            return devices

        async def get_device_ip_addresses(self, native_device_id: str):
            calls.append(("ip", native_device_id))
            return addresses

    monkeypatch.setattr(binding_service, "decrypt_credential", lambda _value: "unit-test-token")
    monkeypatch.setattr(binding_service, "LibreNMSRuntimeClient", FakeClient)
    return calls


def test_auto_binding_uses_unique_exact_management_ip_and_writes_audit(isolated_db, monkeypatch):
    conn = database.get_db_connection()
    try:
        _insert_target(conn, "device-1", "asset-1", "192.0.2.10")
        _insert_instance(conn)
        conn.commit()
    finally:
        conn.close()
    calls = _fake_client(
        monkeypatch,
        devices=[{"device_id": 17, "hostname": "edge-01", "poller_group": "default"}],
        addresses=[{"ipv4_address": "192.0.2.10"}],
    )

    result = asyncio.run(binding_service.auto_bind_device_by_management_ip({
        "id": "device-1", "asset_id": "asset-1", "ip_address": "192.0.2.10",
    }))

    assert result["status"] == "bound"
    assert result["binding"]["librenms_device_id"] == "17"
    assert result["binding"]["sync_status"] == "pending"
    assert calls == [("ipv4", "192.0.2.10"), ("ip", "17")]
    conn = database.get_db_connection()
    try:
        saved = conn.execute(
            "SELECT tenant_id, asset_id, desired_state, sync_status FROM librenms_device_bindings WHERE device_id = ?",
            ("device-1",),
        ).fetchone()
        audit = conn.execute(
            "SELECT event_type, details_json FROM audit_events WHERE event_type = 'librenms.binding.auto'"
        ).fetchone()
    finally:
        conn.close()
    assert dict(saved) == {
        "tenant_id": "tenant-1", "asset_id": "asset-1", "desired_state": "enabled", "sync_status": "pending",
    }
    assert audit["event_type"] == "librenms.binding.auto"
    assert "unique_management_ip" in audit["details_json"]


def test_instance_matching_finds_ip_hostname_before_port_discovery(monkeypatch):
    calls: list[str] = []

    class FakeClient:
        def __init__(self, _base_url: str, _token: str) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_devices(self, *, device_type: str, query: str, max_rows: int):
            calls.append(device_type)
            assert query == "192.0.2.10"
            assert max_rows == 200
            if device_type == "hostname":
                return [{"device_id": 17, "hostname": "192.0.2.10", "poller_group": "default"}]
            return []

        async def get_device_ip_addresses(self, _native_device_id: str):
            raise AssertionError("hostname identity should be sufficient before port discovery")

    monkeypatch.setattr(binding_service, "decrypt_credential", lambda _value: "unit-test-token")
    monkeypatch.setattr(binding_service, "LibreNMSRuntimeClient", FakeClient)

    matches = asyncio.run(binding_service._instance_matches(
        {
            "id": "instance-1",
            "base_url": "https://librenms.example",
            "encrypted_password": "encrypted-test-token",
        },
        "192.0.2.10",
        "ipv4",
    ))

    assert calls == ["ipv4", "hostname"]
    assert len(matches) == 1
    assert matches[0]["native_device_id"] == "17"
    assert matches[0]["native_hostname"] == "192.0.2.10"


def test_preflight_rejects_local_native_binding_conflict_before_remote_update(isolated_db):
    conn = database.get_db_connection()
    try:
        _insert_target(conn, "device-1", "asset-1", "192.0.2.10")
        _insert_target(conn, "device-2", "asset-2", "192.0.2.20")
        _insert_instance(conn)
        conn.execute(
            """INSERT INTO librenms_device_bindings
               (id, tenant_id, asset_id, device_id, instance_id, librenms_device_id)
               VALUES ('binding-existing', 'tenant-1', 'asset-2', 'device-2', 'instance-1', '17')"""
        )
        conn.commit()
    finally:
        conn.close()

    result = binding_service.preflight_auto_binding(
        {"id": "device-1"},
        {"instance_id": "instance-1", "native_device_id": "17"},
    )

    assert result == {"status": "conflict"}


def test_preflight_allows_existing_binding_to_same_native_device(isolated_db):
    conn = database.get_db_connection()
    try:
        _insert_target(conn, "device-1", "asset-1", "192.0.2.10")
        _insert_instance(conn)
        conn.execute(
            """INSERT INTO librenms_device_bindings
               (id, tenant_id, asset_id, device_id, instance_id, librenms_device_id)
               VALUES ('binding-existing', 'tenant-1', 'asset-1', 'device-1', 'instance-1', '17')"""
        )
        conn.commit()
    finally:
        conn.close()

    result = binding_service.preflight_auto_binding(
        {"id": "device-1"},
        {"instance_id": "instance-1", "native_device_id": "17"},
    )

    assert result == {"status": "ready"}


def test_auto_binding_skips_duplicate_local_management_ip_without_calling_librenms(isolated_db, monkeypatch):
    conn = database.get_db_connection()
    try:
        _insert_target(conn, "device-1", "asset-1", "192.0.2.10")
        _insert_target(conn, "device-2", "asset-2", "192.0.2.10", asset_ip="192.0.2.11")
        _insert_instance(conn)
        conn.commit()
    finally:
        conn.close()
    calls = _fake_client(monkeypatch, devices=[], addresses=[])

    result = asyncio.run(binding_service.auto_bind_device_by_management_ip({
        "id": "device-1", "asset_id": "asset-1", "ip_address": "192.0.2.10",
    }))

    assert result["status"] == "ambiguous"
    assert "CMDB" in result["message"]
    assert calls == []
    conn = database.get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM librenms_device_bindings").fetchone()[0] == 0
    finally:
        conn.close()


def test_auto_binding_reports_device_not_yet_discovered_without_creating_relation(isolated_db, monkeypatch):
    conn = database.get_db_connection()
    try:
        _insert_target(conn, "device-1", "asset-1", "192.0.2.10")
        _insert_instance(conn)
        conn.commit()
    finally:
        conn.close()
    _fake_client(monkeypatch, devices=[], addresses=[])

    result = asyncio.run(binding_service.auto_bind_device_by_management_ip({
        "id": "device-1", "asset_id": "asset-1", "ip_address": "192.0.2.10",
    }))

    assert result["status"] == "not_discovered"
    assert "自动发现或添加" in result["message"]
    conn = database.get_db_connection()
    try:
        assert conn.execute("SELECT COUNT(*) FROM librenms_device_bindings").fetchone()[0] == 0
    finally:
        conn.close()


def test_auto_binding_does_not_claim_native_device_already_bound_elsewhere(isolated_db, monkeypatch):
    conn = database.get_db_connection()
    try:
        _insert_target(conn, "device-1", "asset-1", "192.0.2.10")
        _insert_target(conn, "device-2", "asset-2", "192.0.2.20")
        _insert_instance(conn)
        conn.execute(
            """INSERT INTO librenms_device_bindings
               (id, tenant_id, asset_id, device_id, instance_id, librenms_device_id)
               VALUES ('binding-existing', 'tenant-1', 'asset-2', 'device-2', 'instance-1', '17')"""
        )
        conn.commit()
    finally:
        conn.close()
    _fake_client(
        monkeypatch,
        devices=[{"device_id": 17, "hostname": "edge-01"}],
        addresses=[{"ipv4_address": "192.0.2.10"}],
    )

    result = asyncio.run(binding_service.auto_bind_device_by_management_ip({
        "id": "device-1", "asset_id": "asset-1", "ip_address": "192.0.2.10",
    }))

    assert result["status"] == "conflict"
    assert "另一台 CMDB 设备" in result["message"]
    conn = database.get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM librenms_device_bindings WHERE device_id = 'device-1'"
        ).fetchone()[0] == 0
    finally:
        conn.close()
