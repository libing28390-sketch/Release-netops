"""Native PostgreSQL snapshot reconciliation and collection regressions.

Temporary tables copy the migrated table types and primary keys. Dedicated
connections prevent session-local tables from leaking into the application pool.
"""
from datetime import datetime, timezone
import ipaddress
import json

import pytest
import psycopg2

from services.ipam_snapshot_write_service import reconcile_current_snapshot


class DB:
    def __init__(self, conn, raw):
        self.db = conn
        self.statements = []
        # The application adapter translates LIKE predicates to ILIKE. Use
        # the native cursor for this PostgreSQL DDL (LIKE is not a predicate).
        with raw.cursor() as cursor:
            for kind in ("fdb", "endpoint"):
                table = f"ipam_current_{kind}_observations"
                cursor.execute(f"CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL)")
        self.db.commit()

    def execute(self, sql, params):
        self.statements.append((sql, len(params)))
        return self.db.execute(sql, params)


@pytest.fixture
def db_factory(isolated_db):
    from database import core

    opened = []
    def make():
        raw = psycopg2.connect(core._DATABASE_URL)
        conn = core._PgRawConnection(raw)
        opened.append(conn)
        return DB(conn, raw)

    try:
        yield make
    finally:
        for conn in opened:
            conn.close()


def scope(kind="fdb", device="d1", key=""):
    return device, kind, "snmp", "unknown", key


def row(i, g=1, sc=None, port="ge1/0/1", **kw):
    sc = sc or scope()
    r = dict(zip(("source_device_id", "observation_source", "context_source", "context_type", "local_context_key"), sc))
    r.update(local_context_name="x", mac_address=f"{i:012x}", interface_name=port.upper(),
             normalized_interface_name=port, vlan_key=7, generation=g,
             observed_at=f"2026-11-28T00:00:{g:02d}+00:00", run_id=str(g), metadata_json="{}")
    if sc[1] == "fdb":
        r["entry_type"] = "dynamic"
    else:
        r["ip_address"] = f"192.0.2.{i}" if sc[1] == "arp" else f"2001:db8::{i:x}"
    r.update(kw)
    return r


def read(db, kind="fdb"):
    table = "fdb" if kind == "fdb" else "endpoint"
    rows = [dict(r) for r in db.db.execute(
        f"SELECT * FROM ipam_current_{table}_observations "
        "ORDER BY source_device_id, local_context_key, mac_address, normalized_interface_name"
    ).fetchall()]
    for record in rows:
        if "ip_address" in record:
            record["ip_address"] = str(ipaddress.ip_interface(record["ip_address"]).ip)
        record["observed_at"] = record["observed_at"].astimezone(timezone.utc).isoformat()
        record["metadata_json"] = json.dumps(record["metadata_json"], sort_keys=True, separators=(",", ":"))
    return rows


@pytest.mark.parametrize("kind", ["arp", "ndp", "fdb"])
def test_reconcile(kind, db_factory):
    db = db_factory()
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
def test_batches(n, db_factory):
    db = db_factory()
    reconcile_current_snapshot(db, scope=scope(), generation=1, rows=[row(i) for i in range(n)])
    assert len(read(db)) == n
    assert len(db.statements) == (n + 499) // 500 + 1
    assert max(p for _, p in db.statements) <= 7500


@pytest.mark.parametrize("kind", ["scope", "generation", "duplicate"])
def test_reject_before_write(kind, db_factory):
    db = db_factory()
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


def test_rollback_on_second_batch(db_factory):
    db = db_factory()
    reconcile_current_snapshot(db, scope=scope(), generation=1, rows=[row(9)])
    db.db.commit()
    old, original = read(db), db.execute
    n = 0

    def fail(sql, params):
        nonlocal n
        n += 1
        if n == 2:
            return original("SELECT 1 / 0", ())
        return original(sql, params)

    db.execute = fail
    with pytest.raises(psycopg2.errors.DivisionByZero):
        reconcile_current_snapshot(db, scope=scope(), generation=2, rows=[row(i, 2) for i in range(501)])
    db.db.rollback()
    assert read(db) == old


def test_multiple_ports_same_mac_preserved(db_factory):
    db = db_factory()
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

@pytest.mark.parametrize("kind", ["arp", "ndp", "fdb"])
def test_matches_full_replace_across_20_generations(kind, db_factory):
    import random
    rng = random.Random(42)
    db, ref = db_factory(), db_factory()
    sc, alt = scope(kind), scope(kind, key="other")
    table = "ipam_current_fdb_observations" if kind == "fdb" else "ipam_current_endpoint_observations"
    for g in range(1, 21):
        for s in (sc, alt):
            records = [
                row(i, g, s, port=f"ge1/0/{rng.randint(1, 4)}", metadata_json='{"updated":true}')
                for i in rng.sample(range(1, 101), rng.randint(0, 100))
            ]
            reconcile_current_snapshot(db, scope=s, generation=g, rows=records)
            ref.db.execute(
                f"DELETE FROM {table} WHERE source_device_id=? AND observation_source=? "
                "AND context_source=? AND context_type=? AND local_context_key=?", s,
            )
            for r in records:
                ref.db.execute(
                    f"INSERT INTO {table} ({','.join(r)}) VALUES ({','.join('?' for _ in r)})",
                    tuple(r.values()),
                )
        db.db.commit()
        ref.db.commit()
        assert read(db, kind) == read(ref, kind)

def test_native_postgresql_fdb_50k_refresh(isolated_db):
    """Opt-in benchmark on the real PostgreSQL driver and migrated schema."""
    import os
    import time
    from database import get_db_connection
    from services.ipam_current_fdb_observation_service import (
        begin_current_fdb_collection, finish_current_fdb_collection,
    )

    if os.getenv("IP_LOCATOR_SCALE_LARGE") != "1":
        pytest.skip("opt-in PostgreSQL 50k row test")

    device = "native-pg-bulk-test"
    with get_db_connection() as conn:
        conn.execute("INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING")
        conn.execute("INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, 'tenant-default')", (device, device))
        conn.commit()

    class CountedConnection:
        def __init__(self, conn):
            self.conn = conn
            self.snapshot_statements = 0

        def execute(self, sql, params=None):
            if sql.lstrip().upper().startswith(("INSERT INTO IPAM_CURRENT_FDB_OBSERVATIONS",
                                                "DELETE FROM IPAM_CURRENT_FDB_OBSERVATIONS")):
                self.snapshot_statements += 1
            return self.conn.execute(sql, params)

    def publish(moved):
        stamp = datetime.now(timezone.utc).isoformat()
        records = [
            {"mac": f"02{i:010x}", "interface": "GE1/0/2" if moved and i < 500 else "GE1/0/1",
             "vlan": 7, "type": "dynamic"}
            for i in range(50000)
        ]
        with get_db_connection() as conn:
            generation = begin_current_fdb_collection(
                conn, device_id=device, context_source="snmp", attempted_at=stamp,
            )
            conn.commit()
            counted = CountedConnection(conn)
            started = time.perf_counter()
            count = finish_current_fdb_collection(
                counted, device_id=device, context_source="snmp", generation=generation,
                status="scope_unknown", attempted_at=stamp, completed_at=stamp, observations=records,
            )
            conn.commit()
            elapsed = time.perf_counter() - started
            assert count == 50000
            assert counted.snapshot_statements == 101
            return generation, elapsed

    first, first_time = publish(False)
    second, second_time = publish(True)
    assert second == first + 1
    with get_db_connection() as conn:
        result = conn.execute(
            """SELECT COUNT(*) AS total,
                      COUNT(*) FILTER (WHERE generation=?) AS fresh,
                      COUNT(*) FILTER (WHERE interface_name='GE1/0/2') AS moved
                 FROM ipam_current_fdb_observations WHERE source_device_id=?""",
            (second, device),
        ).fetchone()
        assert tuple(result) == (50000, 50000, 500)
    print(f"native PostgreSQL 50000 FDB: initial={first_time:.3f}s refresh={second_time:.3f}s "
          "snapshot SQL calls=101; includes finish and commit")
