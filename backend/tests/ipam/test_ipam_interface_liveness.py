"""Device interface addresses are judged alive by interface state, not ARP.

Loopback, point-to-point and management addresses rarely appear in ARP
tables, so IPAM reads the newer of the SNMP ``interfaces`` row and the latest
successful CLI interface snapshot for the owning interface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from database import get_db_connection
from services import interface_collection_service, ipam_service


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).replace(microsecond=0).isoformat()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _StateConnection:
    def __init__(self, snmp_rows, cli_rows, *, cli_error: Exception | None = None):
        self.snmp_rows = snmp_rows
        self.cli_rows = cli_rows
        self.cli_error = cli_error
        self.rolled_back = False
        self.statements: list[str] = []

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.statements.append(text)
        if "cmdb_device_interface_observations" in text:
            if self.cli_error is not None:
                raise self.cli_error
            return _Result(self.cli_rows)
        if "FROM interfaces" in text:
            return _Result(self.snmp_rows)
        raise AssertionError(f"unexpected query: {text}")

    def rollback(self):
        self.rolled_back = True


def _row(device_id, name, admin, oper, observed_at):
    return {
        "device_id": device_id,
        "interface_name": name,
        "admin_status": admin,
        "oper_status": oper,
        "observed_at": observed_at,
    }


def test_state_sources_keep_the_newer_observation_per_interface() -> None:
    connection = _StateConnection(
        snmp_rows=[
            _row("dev-1", "Vlan10", "up", "down", _iso(timedelta(minutes=5))),
            _row("dev-1", "FGE1/0/53", "up", "up", _iso(timedelta(days=3))),
        ],
        cli_rows=[
            _row("dev-1", "Vlan-interface10", "up", "up", _iso(timedelta(days=11))),
            _row("dev-1", "FortyGigE1/0/53", "up", "down", _iso(timedelta(hours=1))),
        ],
    )

    states = ipam_service._interface_state_sources(connection)

    interface_query = next(statement for statement in connection.statements if "FROM interfaces" in statement)
    assert "status_observed_at" in interface_query
    assert "last_seen" not in interface_query
    vlan = states[("dev-1", "vlan10")]
    assert (vlan["oper_status"], vlan["source"]) == ("down", "snmp")
    port = states[("dev-1", "fo1/0/53")]
    assert (port["oper_status"], port["source"]) == ("down", "cli_snapshot")


def test_state_sources_fall_back_to_snmp_when_snapshot_tables_are_unavailable() -> None:
    connection = _StateConnection(
        snmp_rows=[_row("dev-1", "Loop0", "up", "up", _iso(timedelta(minutes=1)))],
        cli_rows=[],
        cli_error=RuntimeError("relation does not exist"),
    )

    states = ipam_service._interface_state_sources(connection)

    assert states[("dev-1", "lo0")]["source"] == "snmp"
    assert connection.rolled_back is True


def _patch_states(monkeypatch, states: dict) -> None:
    monkeypatch.setattr(ipam_service, "_interface_state_sources", lambda _conn: states)


def _state(admin: str, oper: str, age: timedelta, source: str = "snmp") -> dict:
    observed = datetime.now(timezone.utc) - age
    return {
        "admin_status": admin,
        "oper_status": oper,
        "observed_at": observed.isoformat(),
        "source": source,
        "_parsed": observed,
    }


@pytest.mark.parametrize(
    ("admin", "oper", "age", "expected_state", "expected_freshness", "alive"),
    [
        ("up", "up", timedelta(minutes=10), "up", "recent", True),
        ("up", "up", timedelta(days=3), "up", "historical", False),
        ("up", "down", timedelta(minutes=10), "down", "recent", False),
        ("down", "down", timedelta(minutes=10), "admin_down", "recent", False),
        ("up", "unknown", timedelta(minutes=10), "unknown", "recent", False),
    ],
)
def test_interface_liveness_classifies_state_and_freshness(
    monkeypatch, admin, oper, age, expected_state, expected_freshness, alive,
) -> None:
    monkeypatch.delenv("IPAM_INTERFACE_FRESH_MINUTES", raising=False)
    _patch_states(monkeypatch, {("dev-1", "lo0"): _state(admin, oper, age)})

    liveness = ipam_service._interface_liveness(object(), {"device_id": "dev-1", "interface_name": "LoopBack0"})

    assert liveness["state"] == expected_state
    assert liveness["freshness"] == expected_freshness
    assert liveness["alive"] is alive
    assert liveness["window_minutes"] == 1440


def test_interface_liveness_without_state_or_interface(monkeypatch) -> None:
    _patch_states(monkeypatch, {})

    missing = ipam_service._interface_liveness(object(), {"device_id": "dev-1", "interface_name": "Vlan99"})
    assert missing["state"] == "unknown"
    assert missing["alive"] is False
    assert ipam_service._interface_liveness(object(), {"device_id": "dev-1", "interface_name": ""}) is None
    assert ipam_service._interface_liveness(object(), {"device_id": "", "interface_name": "Vlan99"}) is None


@pytest.mark.parametrize(("value", "expected"), [("5000", 5000), ("1", 5), ("999999", 43200), ("abc", 1440)])
def test_interface_freshness_window_is_configurable_and_bounded(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("IPAM_INTERFACE_FRESH_MINUTES", value)
    assert ipam_service._interface_fresh_minutes() == expected


def test_freshness_window_override_turns_older_up_state_current(monkeypatch) -> None:
    monkeypatch.setenv("IPAM_INTERFACE_FRESH_MINUTES", "5000")
    _patch_states(monkeypatch, {("dev-1", "vlan10"): _state("up", "up", timedelta(days=3))})

    liveness = ipam_service._interface_liveness(object(), {"device_id": "dev-1", "interface_name": "Vlan10"})

    assert liveness["freshness"] == "recent"
    assert liveness["alive"] is True


@pytest.mark.parametrize(
    "name", ["MGE0/0/0", "M-GigabitEthernet0/0/0", "MEth0/0/0", "Management0", "mgmt0", "me0", "fxp0"],
)
def test_management_interface_names_are_recognised(name: str) -> None:
    assert ipam_service._is_management_interface_name(name) is True


@pytest.mark.parametrize("name", ["GE1/0/1", "Loop0", "Vlan10", "MGE", "Mgmt-vrf", ""])
def test_non_management_interface_names_are_not_matched(name: str) -> None:
    assert ipam_service._is_management_interface_name(name) is False


def test_management_port_on_point_to_point_mask_is_management_not_transit() -> None:
    assert ipam_service._classify_interface_address_kind("MGE0/0/0", 31, 4) == "physical"
    assert ipam_service._classify_interface_address_kind("FGE1/0/53", 30, 4) == "transit"

    item = {
        "address": "10.1.1.1",
        "interface_name": "MGE0/0/0",
        "subnet_prefix": "10.1.1.0/31",
        "device_type": "interface",
        "stored_purpose": "",
        "network_type": "",
    }
    ipam_service._derive_interface_address_classification(item)

    assert item["purpose"] == "management"
    assert item["device_type"] == "physical"
    assert item["classification_inferred"] is True


def _seed_interface_device(device_id: str, site_id: str) -> dict:
    device = {"id": device_id, "hostname": device_id}
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
               VALUES (?, ?, ?, 'tenant-default') ON CONFLICT (id) DO NOTHING""",
            (site_id, site_id.upper(), site_id),
        )
        conn.execute(
            """INSERT INTO devices
                   (id, hostname, ip_address, platform, vendor, status, tenant_id, site_id, site)
               VALUES (?, ?, '192.0.2.90', 'h3c_comware', 'h3c', 'online', 'tenant-default', ?, ?)""",
            (device_id, device_id, site_id, site_id),
        )
        conn.commit()
    return device


def test_qbridge_and_unknown_status_refresh_do_not_advance_certified_state_timestamp(isolated_db):
    del isolated_db
    device_id, site_id = f"liveness-{uuid.uuid4().hex[:8]}", f"liveness-site-{uuid.uuid4().hex[:8]}"
    device = _seed_interface_device(device_id, site_id)
    interface_collection_service._upsert_snmp_interfaces(device, [{
        "name": "GigabitEthernet1/0/1", "admin_status": "up", "status": "up", "if_index": 11,
    }])

    with get_db_connection() as conn:
        before = conn.execute(
            "SELECT admin_status, oper_status, certified_admin_status, certified_oper_status, "
            "last_seen, status_observed_at, status_observation_source "
            "FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        certified_at = before["status_observed_at"]
        assert before["status_observation_source"] == "snmp"
        assert (before["certified_admin_status"], before["certified_oper_status"]) == ("up", "up")

    interface_collection_service._upsert_snmp_interfaces(device, [{
        "name": "GigabitEthernet1/0/1", "admin_status": "unknown", "status": "unknown",
    }])
    with get_db_connection() as conn:
        after_unknown = conn.execute(
            "SELECT status_observed_at, status_observation_source, certified_admin_status, certified_oper_status "
            "FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        assert after_unknown["status_observed_at"] == certified_at
        assert after_unknown["status_observation_source"] == "snmp"
        assert (after_unknown["certified_admin_status"], after_unknown["certified_oper_status"]) == ("up", "up")

        cli_at = (datetime.now(timezone.utc) + timedelta(seconds=10)).replace(microsecond=0).isoformat()
        conn.execute(
            """INSERT INTO cmdb_collection_snapshots
                   (device_id, domain, attempt_generation, successful_generation,
                    attempt_status, observed_at, transport, record_count)
               VALUES (?, 'interface_inventory', 1, 1, 'success', ?, 'ssh', 1)""",
            (device_id, cli_at),
        )
        conn.execute(
            """INSERT INTO cmdb_device_interface_observations
                   (device_id, normalized_interface_name, interface_name,
                    admin_status, oper_status, interface_type, generation, observed_at)
               VALUES (?, 'gi1/0/1', 'GigabitEthernet1/0/1', 'up', 'down',
                       'physical', 1, ?)""",
            (device_id, cli_at),
        )
        conn.commit()

    interface_collection_service._upsert_qbridge_vlan_data(device_id, {
        "vlans": [{"vlan_id": 10, "vlan_name": "USERS"}],
        "interfaces": [{
            "interface": "GigabitEthernet1/0/1", "if_index": 11, "pvid": 10,
            "tagged_vlans": [], "untagged_vlans": [10],
        }],
    })

    with get_db_connection() as conn:
        after_vlan = conn.execute(
            "SELECT last_seen, status_observed_at, status_observation_source, "
            "certified_admin_status, certified_oper_status "
            "FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        assert after_vlan["status_observed_at"] == certified_at
        assert after_vlan["status_observation_source"] == "snmp"
        assert (after_vlan["certified_admin_status"], after_vlan["certified_oper_status"]) == ("up", "up")
        states = ipam_service._interface_state_sources(conn)
    state = states[(device_id, "gi1/0/1")]
    assert (state["oper_status"], state["source"], state["observed_at"]) == (
        "down", "cli_snapshot", cli_at,
    )


def test_partial_interface_status_invalidates_certified_pair(isolated_db):
    del isolated_db
    device_id, site_id = f"partial-liveness-{uuid.uuid4().hex[:8]}", f"partial-site-{uuid.uuid4().hex[:8]}"
    device = _seed_interface_device(device_id, site_id)
    interface_collection_service._upsert_snmp_interfaces(device, [{
        "name": "GigabitEthernet1/0/2", "admin_status": "up", "status": "up", "if_index": 12,
    }])
    interface_collection_service._upsert_snmp_interfaces(device, [{
        "name": "GigabitEthernet1/0/2", "oper_status": "down",
    }])

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT admin_status, oper_status, status_observed_at, status_observation_source, "
            "certified_admin_status, certified_oper_status "
            "FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        assert row["admin_status"] == "up"
        assert row["oper_status"] == "down"
        assert row["status_observed_at"] is None
        assert row["status_observation_source"] == ""
        assert row["certified_admin_status"] is None
        assert row["certified_oper_status"] is None
        assert (device_id, "gi1/0/2") not in ipam_service._interface_state_sources(conn)


def test_interface_status_writer_persists_cli_source_with_certified_pair(isolated_db):
    del isolated_db
    device_id, site_id = f"cli-liveness-{uuid.uuid4().hex[:8]}", f"cli-site-{uuid.uuid4().hex[:8]}"
    device = _seed_interface_device(device_id, site_id)
    interface_collection_service._upsert_interfaces(
        device,
        [{
            "interface_name": "Vlan-interface10", "interface_ip": "192.0.2.10",
            "prefix_length": 24, "admin_status": "up", "oper_status": "down",
        }],
        status_source="cli_snapshot",
    )

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT status_observed_at, status_observation_source, "
            "certified_admin_status, certified_oper_status FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchone()
    assert row["status_observed_at"]
    assert row["status_observation_source"] == "cli_snapshot"
    assert (row["certified_admin_status"], row["certified_oper_status"]) == ("up", "down")


def test_legacy_raw_status_writer_cannot_change_certified_liveness(isolated_db):
    del isolated_db
    device_id, site_id = f"raw-liveness-{uuid.uuid4().hex[:8]}", f"raw-site-{uuid.uuid4().hex[:8]}"
    device = _seed_interface_device(device_id, site_id)
    interface_collection_service._upsert_snmp_interfaces(device, [{
        "name": "GigabitEthernet1/0/3", "admin_status": "up", "status": "up", "if_index": 13,
    }])
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE interfaces SET admin_status = 'down', oper_status = 'down' WHERE device_id = ?",
            (device_id,),
        )
        conn.commit()
        state = ipam_service._interface_state_sources(conn)[(device_id, "gi1/0/3")]
        liveness = ipam_service._interface_liveness(
            conn, {"device_id": device_id, "interface_name": "GigabitEthernet1/0/3"},
        )

    assert (state["admin_status"], state["oper_status"], state["source"]) == ("up", "up", "snmp")
    assert liveness["state"] == "up"
    assert liveness["alive"] is True


def test_interface_status_migration_is_idempotent_and_does_not_backfill_last_seen(isolated_db):
    del isolated_db
    from database.migrations.m0334_interface_status_observation import upgrade as upgrade_observation
    from database.migrations.m0335_interface_status_certified_pair import upgrade as upgrade_certified_pair

    device_id, site_id = f"migration-liveness-{uuid.uuid4().hex[:8]}", f"migration-site-{uuid.uuid4().hex[:8]}"
    _seed_interface_device(device_id, site_id)
    with get_db_connection() as conn:
        conn.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS status_observation_source")
        conn.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS status_observed_at")
        conn.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS certified_oper_status")
        conn.execute("ALTER TABLE interfaces DROP COLUMN IF EXISTS certified_admin_status")
        conn.execute(
            """INSERT INTO interfaces (id, device_id, interface_name, admin_status, oper_status, last_seen)
               VALUES (?, ?, 'Loopback0', 'up', 'up', ?)""",
            (f"interface-{device_id}", device_id, _iso(timedelta(seconds=5))),
        )
        conn.commit()
        upgrade_observation(conn.cursor(), use_pg=True)
        upgrade_observation(conn.cursor(), use_pg=True)
        upgrade_certified_pair(conn.cursor(), use_pg=True)
        upgrade_certified_pair(conn.cursor(), use_pg=True)
        conn.commit()
        row = conn.execute(
            "SELECT status_observed_at, status_observation_source, "
            "certified_admin_status, certified_oper_status FROM interfaces WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        assert row["status_observed_at"] is None
        assert row["status_observation_source"] == ""
        assert row["certified_admin_status"] is None
        assert row["certified_oper_status"] is None
