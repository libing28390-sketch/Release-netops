"""Native PostgreSQL scale test of the cross-device path with synthetic facts.

The indexed FDB projection is synthetic; this is not a full locator API or
production query-plan benchmark. Each test owns a disposable database.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import time

import psycopg2
from psycopg2.extras import execute_values

import pytest

from services import ipam_discovery_service as discovery
from services.ip_locator_endpoint_evidence import _current_cross_device_fdb_path


class CountedReader:
    def __init__(self, conn):
        self.conn = conn
        self.statements = 0

    def execute(self, sql, params=None):
        self.statements += 1
        return self.conn.execute(sql, params)


@pytest.mark.parametrize("devices, aggregations, hosts", [
    (300, 9, 33334),
    pytest.param(1000, 39, 333334, marks=pytest.mark.skipif(
        os.getenv("IP_LOCATOR_SCALE_LARGE") != "1", reason="opt-in million-row scale test",
    )),
])
def test_three_tier_fdb_100_parallel(isolated_db, monkeypatch, devices, aggregations, hosts):
    from database import core

    dsn = core._DATABASE_URL
    stamp = datetime.now(timezone.utc).isoformat()
    first_access = aggregations + 1
    access_count = devices - first_access
    allowed = {f"d{i}" for i in range(devices)}
    raw = psycopg2.connect(dsn)
    conn = core._PgRawConnection(raw)
    try:
        conn.execute("CREATE SCHEMA locator_scale")
        conn.execute("SET search_path TO locator_scale")
        conn.execute("""
            CREATE TABLE interfaces (
                id TEXT, device_id TEXT, interface_name TEXT, interface_type TEXT,
                switchport_mode TEXT, access_vlan INT, native_vlan INT,
                allowed_vlans TEXT, admin_status TEXT, oper_status TEXT, last_seen TEXT
            );
            CREATE INDEX ifdev ON interfaces(device_id);
            CREATE TABLE topology_links (
                id TEXT, source_device_id TEXT, target_device_id TEXT,
                source_port TEXT, target_port TEXT, status TEXT, link_kind TEXT,
                discovery_source TEXT, last_seen TEXT
            );
            CREATE INDEX lsrc ON topology_links(source_device_id);
            CREATE INDEX ltgt ON topology_links(target_device_id);
            CREATE TABLE fdb (
                source_device_id TEXT, mac TEXT, vlan TEXT, switch_port TEXT,
                path_classification TEXT, tenant_id TEXT, site_id TEXT,
                address_space_id TEXT, scope_status TEXT, entry_type TEXT,
                coverage_complete INT, evidence_status TEXT,
                timestamp_status TEXT, observed_at TEXT
            );
            CREATE INDEX fdbdevmac ON fdb(source_device_id, mac);
        """)

        def port(device, name, mode):
            return (device + ":" + name, device, name, "physical", mode,
                    7, 1, "7", "up", "up", stamp)

        def link(a, b, p, q):
            return (a + ":" + b, a, b, p, q, "up", "physical", "lldp", stamp)

        interfaces, links = [], []
        for i in range(1, first_access):
            agg = f"d{i}"
            p, q = f"GE1/0/{i}", "GE1/0/1"
            interfaces.extend([port("d0", p, "trunk"), port(agg, q, "trunk")])
            links.append(link("d0", agg, p, q))
        for i in range(first_access, devices):
            agg, access = f"d{1 + (i - first_access) % aggregations}", f"d{i}"
            p, q = f"GE1/0/{2 + (i - first_access) // aggregations}", "GE1/0/1"
            interfaces.extend([port(agg, p, "trunk"), port(access, q, "trunk"),
                               port(access, "GE1/0/2", "access")])
            links.append(link(agg, access, p, q))
        with raw.cursor() as cur:
            execute_values(cur, "INSERT INTO interfaces VALUES %s", interfaces, page_size=1000)
            execute_values(cur, "INSERT INTO topology_links VALUES %s", links, page_size=1000)

        def row(device, mac, name, classification):
            return (device, mac, "7", name, classification, "tenant-default",
                    "site", "space", "resolved", "dynamic", 1, "recent", "valid", stamp)

        def target(h):
            i = first_access + h % access_count
            mac = "02:" + ":".join(f"{(h >> shift) & 255:02x}" for shift in (32, 24, 16, 8, 0))
            return mac, i

        def records():
            for h in range(hosts):
                mac, i = target(h)
                a = 1 + (i - first_access) % aggregations
                p = 2 + (i - first_access) // aggregations
                yield row("d0", mac, f"GE1/0/{a}", "trunk_tagged_interface")
                yield row(f"d{a}", mac, f"GE1/0/{p}", "trunk_tagged_interface")
                yield row(f"d{i}", mac, "GE1/0/2", "access_edge")

        with raw.cursor() as cur:
            execute_values(cur, "INSERT INTO fdb VALUES %s", records(), page_size=2000)
        conn.execute("ANALYZE interfaces")
        conn.execute("ANALYZE topology_links")
        conn.execute("ANALYZE fdb")
        # Refresh the simulated observation clock after loading the data.
        stamp = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE interfaces SET last_seen = ?", (stamp,))
        conn.execute("UPDATE topology_links SET last_seen = ?", (stamp,))
        conn.execute("UPDATE fdb SET observed_at = ?", (stamp,))
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM fdb").fetchone()[0] == hosts * 3
        assert len(links) == devices - 1
    finally:
        conn.close()

    def projection(conn, *, device_id, target_mac):
        return conn.execute(
            "SELECT * FROM fdb WHERE source_device_id=? AND mac=?",
            (device_id, target_mac),
        ).fetchall()

    monkeypatch.setattr(discovery, "_current_fdb_endpoint_projection", projection)

    def locate(pair):
        mac, expected = pair
        connection = core._PgRawConnection(psycopg2.connect(dsn))
        try:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            connection.execute("SET LOCAL search_path TO locator_scale")
            reader = CountedReader(connection)
            root = projection(reader, device_id="d0", target_mac=mac)[0]
            arp = dict(root, source_device_id="d0", source_vrf_context_status="global")
            path = _current_cross_device_fdb_path(
                reader, arp=arp, first_fdb=root, allowed=allowed,
                tenant="tenant-default", mac=mac, vlan="7",
            )
            assert path and path[-1]["source_device_id"] == expected
            assert path[-1]["switch_port"] == "GE1/0/2"
            assert len(path) == 3
            # Counts only SQL in the simulated path and the root FDB read.
            assert reader.statements == 9
        finally:
            connection.close()

    # 100 submitted requests, bounded workers to avoid exhausting PG max_connections.
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        targets = [(mac, f"d{device}") for mac, device in (
            target(i * (hosts // 100)) for i in range(100)
        )]
        list(pool.map(locate, targets))
    print(f"native PG path: devices={devices}, FDB={hosts * 3}, requests=100, "
          f"workers=16, batch={time.perf_counter() - started:.3f}s")
