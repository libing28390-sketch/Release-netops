"""Read-only targeted SNMP contract; no real devices are contacted."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from services import ip_locator_fact_access as facts
from services import snmp_service as snmp


@pytest.mark.parametrize("mode", ["ok", "mac_move", "type_change", "if_rebind"])
def test_targeted_arp_uses_only_exact_instances(monkeypatch, mode):
    calls = []
    suffix = "7.172.16.5.10"

    async def get(_client, oid):
        calls.append(oid)
        repeat = calls.count(oid) > 1
        return {
            snmp.IF_NAME + ".7": b"Vlan-interface8" if repeat and mode == "if_rebind" else b"Vlan-interface7",
            snmp.IP_NET_TO_MEDIA_TYPE + "." + suffix: 4 if repeat and mode == "type_change" else 3,
            snmp.IP_NET_TO_MEDIA_PHYS_ADDRESS + "." + suffix: bytes.fromhex(
                "8e4757600708" if repeat and mode == "mac_move" else "8e4757600706"),
        }[oid]

    monkeypatch.setattr(facts, "_get", get)
    record = asyncio.run(facts._read_arp(object(), "172.16.5.10", 7, "Vlan-interface7", 7))
    if mode != "ok":
        assert record is None
        return
    assert record["mac"] == "8e4757600706"
    assert record["vlan"] == "7"
    assert len(calls) == 6
    assert asyncio.run(facts._read_arp(object(), "172.16.5.10", 7, "Vlan-interface8", 8)) is None


@pytest.mark.parametrize("mode", ["ok", "shared_fid", "moved", "invalid", "missing_vlan",
                                  "bridge_rebind", "port_down", "if_rebind"])
def test_targeted_fdb_requires_unique_vlan_fid_and_stable_learned_port(monkeypatch, mode):
    calls = []
    vlan = 7
    mac = "8e4757600706"
    root = snmp.DOT1Q_VLAN_FDB_ID
    suffix = ".".join(["100", *(str(v) for v in bytes.fromhex(mac))])

    class Client:
        async def bulkwalk(self, oids, bulk_size):
            assert [str(oid) for oid in oids] == [root]
            if mode != "missing_vlan":
                yield SimpleNamespace(oid=root + ".0.7", value=100)
            yield SimpleNamespace(oid=root + ".0.8", value=100 if mode == "shared_fid" else 200)

    async def get(_client, oid):
        calls.append(oid)
        if oid == snmp.DOT1Q_TP_FDB_PORT + "." + suffix:
            return 5 if mode == "moved" and calls.count(oid) > 1 else 4
        return {
            snmp.DOT1Q_TP_FDB_STATUS + "." + suffix: 2 if mode == "invalid" else 3,
            snmp.DOT1D_BASE_PORT_IF_INDEX + ".4": 21 if mode == "bridge_rebind" and calls.count(oid) > 1 else 20,
            snmp.IF_OPER_STATUS + ".20": 2 if mode == "port_down" and calls.count(oid) > 1 else 1,
            snmp.IF_NAME + ".20": b"GigabitEthernet1/0/3" if mode == "if_rebind" and calls.count(oid) > 1 else b"GigabitEthernet1/0/2",
        }[oid]

    monkeypatch.setattr(facts, "_get", get)
    record = asyncio.run(facts._read_fdb(Client(), "2c", mac, vlan))
    if mode != "ok":
        assert record is None
        if mode in {"shared_fid", "missing_vlan"}:
            assert calls == []
    else:
        assert record == {"mac": mac, "port": "GigabitEthernet1/0/2", "vlan": "7",
                          "type": "dynamic", "if_index": 20, "fdb_id": 100}
        assert calls.count(snmp.DOT1Q_TP_FDB_PORT + "." + suffix) == 2


@pytest.mark.parametrize("enabled, allowed, cancelled", [
    (False, {"d1"}, False),
    (True, {"d2"}, False),
    (True, {"d1"}, True),
])
def test_targeted_reader_never_probes_disabled_unauthorized_or_cancelled_devices(
    monkeypatch, enabled, allowed, cancelled,
):
    monkeypatch.setattr(facts, "_scope_profile", lambda *_: pytest.fail("no SNMP profile lookup expected"))
    reader = facts.TargetedFactReader(
        tenant_id="tenant-default", vrf="default", allowed_ids=allowed,
        deadline=time.monotonic() + 10, enabled=enabled, cancel_check=lambda: cancelled,
    )
    assert reader.read("mac", {"id": "d1"}, mac="8e4757600706", vlan="7") is None


def test_targeted_reader_context_failure_is_not_negative_evidence(monkeypatch):
    monkeypatch.setattr(facts, "_scope_profile", lambda *_: None)
    reader = facts.TargetedFactReader(
        tenant_id="tenant-default", vrf="default", allowed_ids={"d1"},
        deadline=time.monotonic() + 10, enabled=True,
    )
    assert reader.read("mac", {"id": "d1"}, mac="8e4757600706", vlan="7") is None
