"""Test bulk reconciliation without contacting a device or production DB.

SQLite executes the real generated DML after stripping PostgreSQL-only casts.
The separate isolated_db cases exercise the production collection services.
"""
from datetime import datetime, timezone
import re
import sqlite3

import pytest

from services.ipam_snapshot_write_service import reconcile_current_snapshot


class DB:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.statements = []
        for kind in ("fdb", "endpoint"):
            cols = ("source_device_id TEXT, observation_source TEXT, context_source TEXT, context_type TEXT, "
                    "local_context_key TEXT, local_context_name TEXT, "
                    + ("ip_address TEXT, " if kind == "endpoint" else "")
                    + "mac_address TEXT, interface_name TEXT, normalized_interface_name TEXT, vlan_key INT, "
                    + ("entry_type TEXT, " if kind == "fdb" else "")
                    + "generation INT, observed_at TEXT, run_id TEXT, metadata_json TEXT")
            key = ("source_device_id, observation_source, context_source, context_type, local_context_key, "
                   + ("ip_address, " if kind == "endpoint" else "")
                   + "mac_address, normalized_interface_name, vlan_key")
            self.db.execute(f"CREATE TABLE ipam_current_{kind}_observations ({cols}, PRIMARY KEY ({key}))")

    def execute(self, sql, params):
        self.statements.append((sql, len(params)))
        return self.db.execute(re.sub(r"::(?:inet|jsonb|timestamptz)", "", sql), params)


def scope(kind="fdb", device="d1", key=""):
    return device, kind, "snmp", "unknown", key


def row(i, g=1, sc=None, port="ge1/0/1", **kw):
    sc = sc or scope()
    r = dict(zip(("source_device_id", "observation_source", "context_source", "context_type", "local_context_key"), sc))
    r.update(local_context_name="x", mac_address=f"{i:012x}", interface_name=port.upper(),
             normalized_interface_name=port, vlan_key=7, generation=g,
             observed_at=f"2026-11-28T00:00:0{g}+00:00", run_id=str(g), metadata_json="{}")
    if sc[1] == "fdb":
        r["entry_type"] = "dynamic"
    else:
        r["ip_address"] = f"192.0.2.{i}" if sc[1] == "arp" else f"2001:db8::{i:x}"
    r.update(kw)
    return r


def read(db, kind="fdb"):
    table = "fdb" if kind == "fdb" else "endpoint"
    db.db.row_factory = sqlite3.Row
    return [dict(r) for r in db.db.execute(
        f"SELECT * FROM ipam_current_{table}_observations "
        "ORDER BY source_device_id, local_context_key, mac_address, normalized_interface_name"
    )]


@pytest.mark.parametrize("kind", ["arp", "ndp", "fdb"])
def test_reconcile(kind):
    db = DB()
    sc, other, alt = scope(kind), scope(kind, "d2"), scope(kind, key="other")
    for s in (sc, other, alt):
        reconcile_current_snapshot(db, scope=s, generation=1, rows=[row(i, sc=s) for i in (1, 2, 3)])
    db.db.commit()
    new = [row(1, 2, sc, metadata_json='{"changed":true}'),
           row(2, 2, sc, port="ge1/0/2"), row(4, 2, sc)]
    reconcile_current_snapshot(db, scope=sc, generation=2, rows=new)
    db.db.commit()
    got = read(db, kind)
    assert [r for r in got if r["source_device_id"] == "d1" and r["local_context_key"] == ""] == new
    assert len(got) == 9
    assert all(r["generation"] == 1 for r in got if r["source_device_id"] != "d1" or r["local_context_key"])
    reconcile_current_snapshot(db, scope=sc, generation=3, rows=[])
    db.db.commit()
    assert len(read(db, kind)) == 6


@pytest.mark.parametrize("n", [0, 1, 499, 500, 501, 1000, 1001])
def test_batches(n):
    db = DB()
    reconcile_current_snapshot(db, scope=scope(), generation=1, rows=[row(i) for i in range(n)])
    assert len(read(db)) == n
    assert len(db.statements) == (n + 499) // 500 + 1
    assert max(p for _, p in db.statements) <= 7500


@pytest.mark.parametrize("kind", ["scope", "generation", "duplicate"])
def test_reject_before_write(kind):
    db = DB()
    rows = [row(i) for i in range(501)]
    if kind == "scope":
        rows[-1]["source_device_id"] = "d2"
    elif kind == "generation":
        rows[-1]["generation"] = 2
    else:
        rows[-1] = rows[0].copy()
    with pytest.raises(ValueError):
        reconcile_current_snapshot(db, scope=scope(), generation=1, rows=rows)
    assert not db.statements


def test_rollback_on_second_batch():
    db = DB()
    reconcile_current_snapshot(db, scope=scope(), generation=1, rows=[row(9)])
    db.db.commit()
    old, original = read(db), db.execute
    n = 0

    def fail(sql, params):
        nonlocal n
        n += 1
        if n == 2:
            raise RuntimeError("failed batch")
        return original(sql, params)

    db.execute = fail
    with pytest.raises(RuntimeError):
        reconcile_current_snapshot(db, scope=scope(), generation=2, rows=[row(i, 2) for i in range(501)])
    db.db.rollback()
    assert read(db) == old


def test_multiple_ports_same_mac_preserved():
    db = DB()
    reconcile_current_snapshot(db, scope=scope(), generation=1,
                               rows=[row(1), row(1, port="ge1/0/2")])
    assert len(read(db)) == 2


@pytest.mark.parametrize("kind", ["arp", "ndp", "fdb"])
def test_production_collection_multibatch_and_failed_attempt(isolated_db, kind):
    from database import get_db_connection
    from services import ipam_current_endpoint_observation_service as endpoint
    from services import ipam_current_fdb_observation_service as fdb

    device = "bulk-write-test-device"
    stamp = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute("INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, 'tenant-default')", (device, device))
        conn.commit()

    kwargs = dict(device_id=device, context_source="snmp", context_type="unknown",
                  local_context_key="", attempted_at=stamp)
    if kind == "fdb":
        begin, finish = fdb.begin_current_fdb_collection, fdb.finish_current_fdb_collection
        table = "ipam_current_fdb_observations"
    else:
        begin, finish = endpoint.begin_current_endpoint_collection, endpoint.finish_current_endpoint_collection
        table = "ipam_current_endpoint_observations"
        kwargs["observation_source"] = kind

    def observation(i, port="GE1/0/1"):
        value = dict(mac=f"{i:012x}", interface=port, vlan=7, context_source="snmp",
                     context_type="unknown", local_context_key="")
        if kind == "arp":
            value["ip"] = f"198.18.{i // 256}.{i % 256}"
        elif kind == "ndp":
            value["ip"] = f"2001:db8::{i:x}"
        else:
            value["type"] = "dynamic"
        return value

    def publish(status, observations):
        with get_db_connection() as conn:
            generation = begin(conn, **kwargs)
            conn.commit()
            count = finish(conn, **kwargs, completed_at=stamp, generation=generation,
                           status=status, observations=observations)
            conn.commit()
            return generation, count

    first, count = publish("scope_unknown", [observation(i) for i in range(1, 1002)])
    assert count == 1001
    second, count = publish("scope_unknown", [observation(i, "GE1/0/2" if i == 2 else "GE1/0/1")
                                             for i in range(2, 1003)])
    assert second == first + 1 and count == 1001
    third, count = publish("failed", [])
    assert third == second + 1 and count == 1001
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT generation, mac_address, interface_name FROM {table} WHERE source_device_id = ?",
            (device,),
        ).fetchall()
        assert len(rows) == 1001
        assert {r["generation"] for r in rows} == {second}
        assert {r["mac_address"] for r in rows} == {f"{i:012x}" for i in range(2, 1003)}
        assert [r["interface_name"] for r in rows if r["mac_address"] == f"{2:012x}"] == ["GE1/0/2"]
    _, count = publish("scope_unknown", [])
    assert count == 0
    with get_db_connection() as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE source_device_id = ?", (device,)).fetchone()[0] == 0
