from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from database import get_db_connection
from services.topology_hostname_service import refresh_topology_hostname
from services.topology_lldp_snapshot_service import begin_lldp_snapshot_attempt, lldp_snapshot_versions


def _device(isolated_db, *, asset_hostname: str | None = None, device_hostname: str = "10.0.0.10"):
    del isolated_db
    device_id = f"hostname-device-{uuid.uuid4().hex}"
    asset_id = f"hostname-asset-{uuid.uuid4().hex}" if asset_hostname is not None else ""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    try:
        if asset_id:
            conn.execute(
                """INSERT INTO physical_assets
                   (id, asset_type, hostname, management_ip, created_at, updated_at)
                   VALUES (?, 'network_device', ?, '10.0.0.10', ?, ?)""",
                (asset_id, asset_hostname, now, now),
            )
        conn.execute(
            """INSERT INTO devices
               (id, asset_id, hostname, sys_name, ip_address, platform, status, tenant_id)
               VALUES (?, ?, ?, '', '10.0.0.10', 'h3c_comware', 'online', 'tenant-hostname-test')""",
            (device_id, asset_id, device_hostname),
        )
        run_id = f"hostname-run-{uuid.uuid4().hex}"
        conn.execute(
            "INSERT INTO topology_discovery_runs (id, started_at) VALUES (?, ?)",
            (run_id, now),
        )
        conn.execute(
            "INSERT INTO topology_discovery_run_devices (id, run_id, device_id) VALUES (?, ?, ?)",
            (f"{run_id}-{device_id}", run_id, device_id),
        )
        conn.commit()
    finally:
        conn.close()
    device = {
        "id": device_id,
        "asset_id": asset_id,
        "hostname": device_hostname,
        "ip_address": "10.0.0.10",
        "platform": "h3c_comware",
    }
    marker = begin_lldp_snapshot_attempt(device, lldp_snapshot_versions(device))
    return device, run_id, marker["generation"]


def _credentials(*, port: int = 1161, version: str = "2c"):
    return {
        "snmp": {
            "server": "10.0.0.10",
            "community": "snmp-test-only",
            "port": port,
            "version": version,
        },
    }


def _read_identity(device_id: str):
    conn = get_db_connection()
    try:
        return conn.execute(
            """SELECT d.hostname, d.sys_name, d.asset_id, p.hostname
                 FROM devices d LEFT JOIN physical_assets p ON p.id = d.asset_id
                WHERE d.id = ?""",
            (device_id,),
        ).fetchone()
    finally:
        conn.close()


def test_refresh_hostname_syncs_asset_and_device_from_snmp_sysname(isolated_db):
    device, run_id, generation = _device(isolated_db, asset_hostname="10.0.0.10")
    with patch(
        "services.snmp_service._snmp_get",
        new=AsyncMock(return_value="core-sw-01.example.net\n"),
    ) as mock_get, patch("services.topology_hostname_service.invalidate_read_cache") as invalidate, patch(
        "services.topology_hostname_service.schedule_monitoring_target_sync_if_hostname_changed",
        return_value=True,
    ) as schedule:
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "success"}},
            )
        )

    assert result == {
        "status": "synced",
        "hostname": "core-sw-01",
        "sys_name": "core-sw-01.example.net\n",
        "changed": True,
    }
    mock_get.assert_awaited_once_with(
        "10.0.0.10",
        "snmp-test-only",
        "1.3.6.1.2.1.1.5.0",
        port=1161,
        timeout=3,
        version="2c",
    )
    assert tuple(_read_identity(device["id"]))[:2] == ("core-sw-01", "core-sw-01.example.net\n")
    invalidate.assert_called_once_with()
    schedule.assert_called_once()


def test_refresh_hostname_syncs_device_without_linked_asset(isolated_db):
    device, run_id, generation = _device(isolated_db, asset_hostname=None)
    with patch("services.snmp_service._snmp_get", new=AsyncMock(return_value="edge-01")):
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(port=161, version="v1"),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "no_neighbors"}},
            )
        )

    assert result["status"] == "synced"
    assert result["hostname"] == "edge-01"
    row = _read_identity(device["id"])
    assert tuple(row)[:3] == ("edge-01", "edge-01", "")


def test_refresh_hostname_refuses_to_overwrite_real_name_conflict(isolated_db):
    device, run_id, generation = _device(isolated_db, asset_hostname="asset-real", device_hostname="device-real")
    with patch("services.snmp_service._snmp_get", new=AsyncMock(return_value="device-new")) as mock_get, patch(
        "services.topology_hostname_service.invalidate_read_cache"
    ) as invalidate:
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "success"}},
            )
        )

    assert result["status"] == "conflict"
    assert result["changed"] is False
    assert tuple(_read_identity(device["id"]))[:2] == ("device-real", "")
    mock_get.assert_awaited_once()
    invalidate.assert_not_called()


@pytest.mark.parametrize("current_ip", ["10.0.0.11", ""])
def test_refresh_hostname_fences_device_management_ip_change(isolated_db, current_ip):
    device, run_id, generation = _device(isolated_db, asset_hostname="10.0.0.10")
    conn = get_db_connection()
    try:
        conn.execute("UPDATE devices SET ip_address = ? WHERE id = ?", (current_ip, device["id"]))
        conn.commit()
    finally:
        conn.close()

    with patch("services.snmp_service._snmp_get", new=AsyncMock(return_value="core-sw-01")):
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "success"}},
            )
        )

    assert result["status"] == "superseded"
    assert tuple(_read_identity(device["id"]))[:2] == ("10.0.0.10", "")


def test_refresh_hostname_drops_old_generation_without_snmp_or_write(isolated_db):
    device, run_id, old_generation = _device(isolated_db, asset_hostname="10.0.0.10")
    current = begin_lldp_snapshot_attempt(device, lldp_snapshot_versions(device))
    with patch("services.snmp_service._snmp_get", new=AsyncMock(return_value="new-name")) as mock_get:
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=old_generation,
                protocol_results={"snmp": {"status": "success"}},
            )
        )

    assert current["generation"] != old_generation
    assert result["status"] == "superseded"
    mock_get.assert_not_awaited()
    assert tuple(_read_identity(device["id"]))[:2] == ("10.0.0.10", "")


@pytest.mark.parametrize("raw_sys_name", ["", "10.0.0.10"])
def test_refresh_hostname_rejects_empty_or_ip_sysname_without_write(isolated_db, raw_sys_name):
    device, run_id, generation = _device(isolated_db, asset_hostname="10.0.0.10")
    with patch("services.snmp_service._snmp_get", new=AsyncMock(return_value=raw_sys_name)):
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "success"}},
            )
        )

    assert result["status"] == "unavailable"
    assert result["changed"] is False
    assert tuple(_read_identity(device["id"]))[:2] == ("10.0.0.10", "")


def test_refresh_hostname_isolates_snmp_exception_and_never_opens_cli(isolated_db):
    device, run_id, generation = _device(isolated_db, asset_hostname="10.0.0.10")
    with patch(
        "services.snmp_service._snmp_get",
        new=AsyncMock(side_effect=RuntimeError("timeout")),
    ) as mock_get, patch("services.topology_service._collect_neighbors_with_netmiko") as mock_cli:
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "success"}},
            )
        )

    assert result["status"] == "unavailable"
    mock_get.assert_awaited_once()
    mock_cli.assert_not_called()


def test_refresh_hostname_does_not_probe_snmp_when_protocol_failed(isolated_db):
    device, run_id, generation = _device(isolated_db, asset_hostname="10.0.0.10")
    with patch("services.snmp_service._snmp_get", new=AsyncMock()) as mock_get, patch(
        "services.topology_service._collect_neighbors_with_netmiko"
    ) as mock_cli:
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "failed"}},
            )
        )

    assert result["status"] == "not_attempted"
    mock_get.assert_not_awaited()
    mock_cli.assert_not_called()


def test_refresh_hostname_verifies_existing_clean_name_without_side_effects(isolated_db):
    device, run_id, generation = _device(isolated_db, asset_hostname="core-sw-01", device_hostname="core-sw-01")
    with patch("services.snmp_service._snmp_get", new=AsyncMock(return_value="core-sw-01.example.net")), patch(
        "services.topology_hostname_service.invalidate_read_cache"
    ) as invalidate, patch(
        "services.topology_hostname_service.schedule_monitoring_target_sync_if_hostname_changed"
    ) as schedule:
        result = asyncio.run(
            refresh_topology_hostname(
                device,
                _credentials(),
                run_id=run_id,
                snapshot_generation=generation,
                protocol_results={"snmp": {"status": "success"}},
            )
        )

    assert result["status"] == "verified"
    assert result["changed"] is False
    invalidate.assert_not_called()
    schedule.assert_not_called()
