"""SNMP IF-MIB interface names must map onto the same rows as CLI names.

Regression (2026-11-23): the interface-name allow-list only knew short H3C
spellings (``FGE``/``XGE``), so IF-MIB long names such as ``FortyGigE1/0/53``
and the management port ``M-GigabitEthernet0/0/0`` were silently dropped and
their status/MAC never refreshed via SNMP.
"""

from __future__ import annotations

import pytest

from core.interface_utils import interface_nominal_speed_mbps, normalize_interface_name
from services import interface_collection_service as ics
from services.interface_collection_service import (
    _looks_like_interface_name,
    _skipped_interface_names,
)


@pytest.mark.parametrize(
    "name",
    [
        "FortyGigE1/0/53",
        "Ten-GigabitEthernet1/0/49",
        "HundredGigE1/0/1",
        "Twenty-FiveGigE1/0/1",
        "M-GigabitEthernet0/0/0",
        "MGE0/0/0",
        "Route-Aggregation34",
        "RAGG34",
        "Bridge-Aggregation1",
    ],
)
def test_h3c_ifmib_long_names_are_recognised_as_interfaces(name: str) -> None:
    assert _looks_like_interface_name(name) is True


@pytest.mark.parametrize(
    ("snmp_name", "cli_name", "expected_key"),
    [
        ("FortyGigE1/0/53", "FGE1/0/53", "fo1/0/53"),
        ("Ten-GigabitEthernet1/0/49", "XGE1/0/49", "te1/0/49"),
        ("M-GigabitEthernet0/0/0", "MGE0/0/0", "mge0/0/0"),
        ("Route-Aggregation34", "RAGG34", "ragg34"),
        ("Vlan-interface10", "Vlan10", "vlan10"),
        ("LoopBack0", "Loop0", "lo0"),
    ],
)
def test_snmp_and_cli_spellings_share_one_interface_key(snmp_name: str, cli_name: str, expected_key: str) -> None:
    assert normalize_interface_name(snmp_name) == expected_key
    assert normalize_interface_name(cli_name) == expected_key


def test_management_port_alias_leaves_other_families_and_speeds_untouched() -> None:
    assert interface_nominal_speed_mbps("M-GigabitEthernet0/0/0") == 0
    assert interface_nominal_speed_mbps("MGE0/0/0") == 0
    assert normalize_interface_name("GigabitEthernet1/0/1") == "gi1/0/1"
    assert interface_nominal_speed_mbps("GigabitEthernet1/0/1") == 1_000
    assert interface_nominal_speed_mbps("FortyGigE1/0/53") == 40_000
    assert normalize_interface_name("MEth0/0/0") == "mgmt0/0/0"


def test_pim_register_tunnel_is_skipped_and_reported_once() -> None:
    assert _looks_like_interface_name("Register-Tunnel0") is False
    assert _looks_like_interface_name("The") is False

    skipped = _skipped_interface_names([
        {"name": "Register-Tunnel0"},
        {"name": "GE1/0/1"},
        {"name": "Register-Tunnel0"},
        {"name": ""},
        "not-a-dict",
        {"name": "FortyGigE1/0/53"},
    ])

    assert skipped == ["Register-Tunnel0"]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, existing_rows):
        self.existing_rows = existing_rows
        self.statements: list[tuple[str, tuple]] = []
        self.committed = False
        self.closed = False

    def execute(self, sql, params=()):
        self.statements.append((" ".join(str(sql).split()), tuple(params)))
        if str(sql).lstrip().upper().startswith("SELECT"):
            return _Result(self.existing_rows)
        return _Result([])

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_snmp_long_names_update_existing_cli_rows_without_creating_duplicates(monkeypatch) -> None:
    connection = _FakeConnection([
        {"id": "row-fge", "interface_name": "FGE1/0/53", "admin_status": "up",
         "oper_status": "up", "speed": None, "description": ""},
        {"id": "row-mge", "interface_name": "MGE0/0/0", "admin_status": "down",
         "oper_status": "down", "speed": None, "description": ""},
    ])
    monkeypatch.setattr(ics, "get_db_connection", lambda: connection)

    updated = ics._upsert_snmp_interfaces(
        {"id": "dev-1", "hostname": "S6850_1"},
        [
            {"name": "FortyGigE1/0/53", "status": "up", "admin_status": "up",
             "mac_address": "8E:44:25:4F:01:3A", "if_index": 53},
            {"name": "M-GigabitEthernet0/0/0", "status": "down", "admin_status": "up",
             "mac_address": "8e:44:25:4f:01:01", "if_index": 1},
            {"name": "Register-Tunnel0", "status": "up", "admin_status": "up", "if_index": 99},
        ],
    )

    writes = [(sql, params) for sql, params in connection.statements if not sql.upper().startswith("SELECT")]
    assert updated == 2
    assert all(sql.upper().startswith("UPDATE INTERFACES") for sql, _ in writes)
    assert sorted(params[-1] for _, params in writes) == ["row-fge", "row-mge"]
    fge_params = next(params for _, params in writes if params[-1] == "row-fge")
    assert "8e:44:25:4f:01:3a" in fge_params
    assert connection.committed is True
    assert connection.closed is True


def test_snmp_status_refresh_returns_and_logs_skipped_interface_names(monkeypatch) -> None:
    from services import snmp_collection_policy_service

    interfaces = [
        {"name": "M-GigabitEthernet0/0/0", "status": "up", "mac_address": "8e:44:25:4f:01:01"},
        {"name": "Register-Tunnel0", "status": "up", "mac_address": ""},
    ]
    upserted: list[list[dict]] = []
    logged: list[tuple] = []
    monkeypatch.setattr(ics, "_load_device", lambda device_id: {"id": device_id, "hostname": "S6850_1"})
    monkeypatch.setattr(snmp_collection_policy_service, "is_snmp_collection_enabled", lambda _device: True)
    monkeypatch.setattr(
        ics,
        "_collect_snmp_interface_domains",
        lambda *_args, **_kwargs: {
            "configured": True,
            "complete": {"interface_status": True, "interface_mac": True},
            "errors": {},
            "interfaces": interfaces,
        },
    )
    monkeypatch.setattr(ics, "_upsert_snmp_interfaces", lambda _device, items: upserted.append(items) or 1)
    monkeypatch.setattr(ics.logger, "info", lambda *args, **_kwargs: logged.append(args))

    result = ics.refresh_snmp_interface_status("dev-1")

    assert result["skipped_interfaces"] == ["Register-Tunnel0"]
    assert result["interface_count"] == 2
    assert result["updated_count"] == 1
    assert upserted == [interfaces]
    assert any("Register-Tunnel0" in " ".join(str(part) for part in args) for args in logged)
