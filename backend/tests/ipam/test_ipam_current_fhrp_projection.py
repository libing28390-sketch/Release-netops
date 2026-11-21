from __future__ import annotations

from datetime import datetime, timezone

from database import get_db_connection
from services.ipam_address_space_service import create_address_space
from services.ipam_current_fhrp_observation_service import (
    begin_current_fhrp_collection,
    finish_current_fhrp_collection,
)
from services import ipam_current_fhrp_projection_service as projection


_FORBIDDEN = (
    "ipam_discovery_observations",
    "ipam_discovery_snapshots",
    "ipam_discovery_scope_assertions",
)


class _HistoryReadGuard:
    def __init__(self, connection):
        self._connection = connection
        self.statements: list[str] = []

    def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        lowered = sql.casefold()
        if any(token in lowered for token in _FORBIDDEN):
            raise AssertionError("current FHRP projection queried historical discovery SQL")
        self.statements.append(sql)
        return self._connection.execute(statement, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _seed_device(device_id: str, site_id: str) -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING"
        )
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
                 VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING""",
            (site_id, site_id.upper(), f"Site {site_id}"),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, tenant_id, site_id, status)
                 VALUES (?, ?, 'tenant-default', ?, 'online')""",
            (device_id, device_id, site_id),
        )
        conn.commit()


def _collect_current(device_id: str, *, status: str = "complete") -> None:
    attempted = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with get_db_connection() as conn:
        generation = begin_current_fhrp_collection(
            conn, device_id=device_id, protocol="vrrp",
            attempted_at=attempted, run_id=f"fhrp-{device_id}-{status}",
        )
        conn.commit()
    observations = [{
        "protocol": "vrrp",
        "group_id": 1,
        "address_family": 4,
        "interface_name": "Vlan10",
        "priority": 100,
        "state": "master",
        "master_address": "192.0.2.1",
        "virtual_ip": "192.0.2.254",
        "virtual_mac": None,
    }] if status == "complete" else None
    with get_db_connection() as conn:
        finish_current_fhrp_collection(
            conn, device_id=device_id, protocol="vrrp", generation=generation,
            status=status, attempted_at=attempted, completed_at=attempted,
            observations=observations, run_id=f"fhrp-{device_id}-{status}",
        )
        conn.commit()


def _interface_snapshot(device_id: str, *spaces: dict) -> list[dict]:
    return [
        {
            "device_id": device_id,
            "normalized_interface_name": "vlan10",
            "ip_address": f"192.0.2.{index + 1}",
            "tenant_id": "tenant-default",
            "device_site_id": "fhrp-projection-site",
            "address_space_id": space["id"],
            "address_space_name": space["name"],
            "mapped_vrf_id": space.get("vrf_id") or "",
            "context_source": "cli",
            "context_type": "global" if space.get("kind") == "global" else "vrf",
            "local_context_key": space.get("name", ""),
        }
        for index, space in enumerate(spaces)
    ]


def test_current_fhrp_projection_uses_unique_latest_interface_scope_and_guards_history(
    isolated_db, monkeypatch,
):
    del isolated_db
    device_id = "fhrp-projection-device"
    _seed_device(device_id, "fhrp-projection-site")
    space = create_address_space(
        name="FHRP Projection Global",
        kind="global",
        vrf_id=None,
        security_tenant_id="tenant-default",
    )
    _collect_current(device_id)
    monkeypatch.setattr(
        "services.ipam_service._current_cmdb_interface_ip_observations",
        lambda _conn: _interface_snapshot(device_id, space),
    )

    with get_db_connection() as conn:
        guarded = _HistoryReadGuard(conn)
        rows = projection.list_current_fhrp_observation_projection(guarded)

    assert len(rows) == 1
    assert rows[0]["source_type"] == "fhrp"
    assert rows[0]["protocol"] == "vrrp"
    assert rows[0]["virtual_ip"] == "192.0.2.254"
    assert rows[0]["address_space_id"] == space["id"]
    assert rows[0]["scope_status"] == "resolved"
    assert rows[0]["coverage_complete"] is True
    assert any("ipam_current_fhrp_observations" in sql.casefold() for sql in guarded.statements)
    assert all(not any(token in sql.casefold() for token in _FORBIDDEN) for sql in guarded.statements)


def test_current_fhrp_scope_ambiguity_stays_pending_and_failed_latest_attempt_is_incomplete(
    isolated_db, monkeypatch,
):
    del isolated_db
    device_id = "fhrp-projection-ambiguous-device"
    _seed_device(device_id, "fhrp-projection-site")
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO vrfs (id, vrf_name, tenant_id) VALUES ('fhrp-vrf-a', 'A', 'tenant-default'), ('fhrp-vrf-b', 'B', 'tenant-default')"
        )
        conn.commit()
    first = create_address_space(
        name="FHRP Projection VRF A", kind="vrf", vrf_id="fhrp-vrf-a",
        security_tenant_id="tenant-default",
    )
    second = create_address_space(
        name="FHRP Projection VRF B", kind="vrf", vrf_id="fhrp-vrf-b",
        security_tenant_id="tenant-default",
    )
    _collect_current(device_id)
    _collect_current(device_id, status="failed")
    monkeypatch.setattr(
        "services.ipam_service._current_cmdb_interface_ip_observations",
        lambda _conn: _interface_snapshot(device_id, first, second),
    )

    with get_db_connection() as conn:
        rows = projection.list_current_fhrp_observation_projection(conn, device_id=device_id)

    assert len(rows) == 1
    assert rows[0]["virtual_ip"] == "192.0.2.254"
    assert rows[0]["scope_status"] == "scope_pending"
    assert rows[0]["scope_reason"] == "interface_snapshot_scope_ambiguous"
    assert rows[0]["collection_status"] == "failed"
    assert rows[0]["coverage_complete"] is False
