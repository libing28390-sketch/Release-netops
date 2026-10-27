from __future__ import annotations

import pytest

from database import get_db_connection
from database.migrations.m0299_cmdb_cli_fact_isolation import upgrade
from services import cmdb_cli_collection_service
from services.cmdb_snapshot_service import begin_snapshot_attempt


_OBSERVED_AT_1 = "2026-10-27T10:00:00+00:00"
_OBSERVED_AT_2 = "2026-10-27T10:01:00+00:00"


def test_m0299_upgrade_creates_postgresql_observation_tables_idempotently(isolated_db):
    conn = get_db_connection()
    try:
        migration = conn.execute(
            "SELECT name FROM schema_migrations WHERE version = 299"
        ).fetchone()
        assert migration["name"] == "cmdb_cli_fact_isolation"
        assert conn.execute(
            "SELECT to_regclass('cmdb_device_interface_observations') AS present"
        ).fetchone()["present"]
        assert conn.execute(
            "SELECT to_regclass('cmdb_device_vlan_port_observations') AS present"
        ).fetchone()["present"]

        # Simulate the observed state: version 298 is tracked while its
        # prerequisite tables are missing, and a prior 299 attempt may have
        # left one of its tables behind. Verify safe repair and rerun.
        conn.execute("SAVEPOINT m0299_upgrade_test")
        conn.execute("DROP TABLE cmdb_device_vlan_port_observations")
        conn.execute("DROP TABLE cmdb_device_interface_observations")
        conn.execute("DROP TABLE cmdb_device_vlan_observations")
        conn.execute("DROP TABLE cmdb_collection_snapshots")
        conn.execute("DROP TABLE cmdb_read_versions")
        upgrade(conn.cursor(), use_pg=True)
        upgrade(conn.cursor(), use_pg=True)
        for table in (
            "cmdb_read_versions",
            "cmdb_collection_snapshots",
            "cmdb_device_vlan_observations",
        ):
            assert conn.execute(
                f"SELECT to_regclass('{table}') AS present"
            ).fetchone()["present"]
        upgrade(conn.cursor(), use_pg=True)
        assert conn.execute(
            "SELECT to_regclass('cmdb_device_interface_observations') AS present"
        ).fetchone()["present"]
        assert conn.execute(
            "SELECT to_regclass('cmdb_device_vlan_port_observations') AS present"
        ).fetchone()["present"]
        conn.execute("ROLLBACK TO SAVEPOINT m0299_upgrade_test")
        conn.execute("RELEASE SAVEPOINT m0299_upgrade_test")
        conn.commit()
    finally:
        conn.close()


def _insert_device_and_shared_facts(conn) -> dict[str, dict]:
    device_id = "cmdb-fact-isolation-device"
    conn.execute(
        "INSERT INTO devices (id, hostname, ip_address, status, platform, vendor) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (device_id, device_id, "192.0.2.19", "online", "h3c_comware", "h3c"),
    )
    conn.execute(
        """INSERT INTO physical_assets (id, asset_type, site_id, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("cmdb-fact-isolation-asset", "network_device", "asset-site", _OBSERVED_AT_1, _OBSERVED_AT_1),
    )
    conn.execute(
        "UPDATE devices SET asset_id = ?, site_id = ?, site = ? WHERE id = ?",
        ("cmdb-fact-isolation-asset", "device-site", "device-site-label", device_id),
    )
    conn.execute(
        """INSERT INTO interfaces (
               id, device_id, interface_name, description, admin_status, oper_status,
               interface_type, primary_ip, ip_address, ip_prefix_length, is_l3, ip_enabled
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "shared-interface-row", device_id, "GE0/0/1", "monitoring-owned",
            "down", "down", "physical", "192.0.2.10", "192.0.2.10", 24, False, 1,
        ),
    )
    conn.execute(
        "INSERT INTO vlans (id, vlan_id, name, site_id, status) VALUES (?, ?, ?, ?, ?)",
        ("shared-vlan-row", 219, "monitoring-owned-vlan", None, "active"),
    )
    conn.execute(
        """INSERT INTO ip_inventory (ip, mask, device_id, interface, type, last_seen)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("192.0.2.10", "255.255.255.0", device_id, "GE0/0/1", "interface", _OBSERVED_AT_1),
    )
    conn.commit()
    return {
        "interfaces": dict(conn.execute(
            "SELECT * FROM interfaces WHERE id = ?", ("shared-interface-row",),
        ).fetchone()),
        "vlans": dict(conn.execute(
            "SELECT * FROM vlans WHERE id = ?", ("shared-vlan-row",),
        ).fetchone()),
        "ip_inventory": dict(conn.execute(
            "SELECT * FROM ip_inventory WHERE ip = ?", ("192.0.2.10",),
        ).fetchone()),
    }


def _shared_facts(conn) -> dict[str, dict]:
    return {
        "interfaces": dict(conn.execute(
            "SELECT * FROM interfaces WHERE id = ?", ("shared-interface-row",),
        ).fetchone()),
        "vlans": dict(conn.execute(
            "SELECT * FROM vlans WHERE id = ?", ("shared-vlan-row",),
        ).fetchone()),
        "ip_inventory": dict(conn.execute(
            "SELECT * FROM ip_inventory WHERE ip = ?", ("192.0.2.10",),
        ).fetchone()),
    }


def _interface_rows(interface_name: str, *, ip: str = "", prefix_length: int | None = None) -> list[dict]:
    return [{
        "interface_name": interface_name,
        "description": f"CMDB {interface_name}",
        "admin_status": "up",
        "oper_status": "up",
        "interface_ip": ip,
        "prefix_length": prefix_length,
    }]


def _vlan_records(vlan_id: int, ports: str) -> list[dict]:
    return [{
        "VLAN_ID": str(vlan_id),
        "VLAN_NAME": f"CMDB-VLAN-{vlan_id}",
        "STATUS": "active",
        "PORTS": ports,
    }]


def _read_observations(conn) -> tuple[list[tuple], list[tuple]]:
    interfaces = [tuple(row) for row in conn.execute(
        """SELECT normalized_interface_name, interface_name, ip_address,
                  ip_prefix_length, interface_type, generation, run_id
           FROM cmdb_device_interface_observations
           WHERE device_id = ? ORDER BY normalized_interface_name""",
        ("cmdb-fact-isolation-device",),
    ).fetchall()]
    ports = [tuple(row) for row in conn.execute(
        """SELECT vlan_id, normalized_interface_name, interface_name, port_mode,
                  tagging, generation, run_id
           FROM cmdb_device_vlan_port_observations
           WHERE device_id = ? ORDER BY vlan_id, normalized_interface_name""",
        ("cmdb-fact-isolation-device",),
    ).fetchall()]
    return interfaces, ports


def test_cmdb_cli_observations_replace_by_generation_without_touching_shared_facts(
    isolated_db, monkeypatch,
):
    conn = get_db_connection()
    try:
        shared_before = _insert_device_and_shared_facts(conn)
    finally:
        conn.close()

    device = {"id": "cmdb-fact-isolation-device"}
    interface_v1 = begin_snapshot_attempt(device["id"], "interface_inventory")
    vlan_v1 = begin_snapshot_attempt(device["id"], "vlan_inventory")
    cmdb_cli_collection_service._persist_interface_snapshot(
        device,
        _interface_rows("GE0/0/2", ip="198.51.100.2", prefix_length=24),
        interface_v1,
        observed_at=_OBSERVED_AT_1,
        metadata={"parser": "fixture"},
    )
    cmdb_cli_collection_service._persist_vlan_snapshot(
        device["id"],
        _vlan_records(219, "UT:GE0/0/2(U)"),
        vlan_v1,
        observed_at=_OBSERVED_AT_1,
        metadata={"template": "fixture"},
    )

    interface_v2 = begin_snapshot_attempt(device["id"], "interface_inventory")
    vlan_v2 = begin_snapshot_attempt(device["id"], "vlan_inventory")

    # A failure after replacement begins must roll back both the new facts and
    # the completion marker, leaving generation 1 as the last good snapshot.
    from services import cmdb_snapshot_service

    def fail_completion(*_args, **_kwargs):
        raise RuntimeError("fixture completion failure")

    with monkeypatch.context() as patch:
        patch.setattr(cmdb_snapshot_service, "complete_snapshot", fail_completion)
        with pytest.raises(RuntimeError, match="fixture completion failure"):
            cmdb_cli_collection_service._persist_interface_snapshot(
                device,
                _interface_rows("GE0/0/3", ip="198.51.100.3", prefix_length=24),
                interface_v2,
                observed_at=_OBSERVED_AT_2,
                metadata={"parser": "fixture"},
            )
        with pytest.raises(RuntimeError, match="fixture completion failure"):
            cmdb_cli_collection_service._persist_vlan_snapshot(
                device["id"],
                _vlan_records(220, "TG:GE0/0/3(U)"),
                vlan_v2,
                observed_at=_OBSERVED_AT_2,
                metadata={"template": "fixture"},
            )

    conn = get_db_connection()
    try:
        interface_rows, port_rows = _read_observations(conn)
        assert interface_rows[0][0:6] == (
            "gi0/0/2", "GE0/0/2", "198.51.100.2", 24, "physical", interface_v1["generation"],
        )
        assert port_rows[0][0:6] == (
            219, "gi0/0/2", "GE0/0/2", "unknown", "untagged", vlan_v1["generation"],
        )
        assert _shared_facts(conn) == shared_before
    finally:
        conn.close()

    cmdb_cli_collection_service._persist_interface_snapshot(
        device,
        _interface_rows("GE0/0/3"),
        interface_v2,
        observed_at=_OBSERVED_AT_2,
        metadata={"parser": "fixture"},
    )
    cmdb_cli_collection_service._persist_vlan_snapshot(
        device["id"],
        _vlan_records(220, "TG:GE0/0/3(U) Vlan-interface220"),
        vlan_v2,
        observed_at=_OBSERVED_AT_2,
        metadata={"template": "fixture"},
    )

    with pytest.raises(RuntimeError, match="superseded"):
        cmdb_cli_collection_service._persist_interface_snapshot(
            device,
            _interface_rows("GE0/0/2", ip="198.51.100.2", prefix_length=24),
            interface_v1,
            observed_at=_OBSERVED_AT_1,
            metadata={"parser": "stale"},
        )
    with pytest.raises(RuntimeError, match="superseded"):
        cmdb_cli_collection_service._persist_vlan_snapshot(
            device["id"],
            _vlan_records(219, "UT:GE0/0/2(U)"),
            vlan_v1,
            observed_at=_OBSERVED_AT_1,
            metadata={"template": "stale"},
        )

    conn = get_db_connection()
    try:
        interface_rows, port_rows = _read_observations(conn)
        assert interface_rows == [(
            "gi0/0/3", "GE0/0/3", "", None, "physical", interface_v2["generation"],
            interface_v2["run_id"],
        )]
        assert port_rows == [(
            220, "gi0/0/3", "GE0/0/3", "unknown", "tagged", vlan_v2["generation"],
            vlan_v2["run_id"],
        )]
        vlan_rows = [tuple(row) for row in conn.execute(
            "SELECT vlan_id, site_id FROM cmdb_device_vlan_observations WHERE device_id = ?",
            (device["id"],),
        ).fetchall()]
        assert vlan_rows == [(220, "asset-site")]
        assert _shared_facts(conn) == shared_before
    finally:
        conn.close()
