"""Scale simulation for the cross-device fact path (no network or production DB).

SQLite is only a test double for the interface/topology queries and indexed
FDB projection. This is not a PostgreSQL performance or full locator test.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

from services import ipam_discovery_service as discovery
from services.ip_locator_endpoint_evidence import _current_cross_device_fdb_path


def _dict_row(cursor, row):
    return dict(zip((column[0] for column in cursor.description), row))


def test_three_tier_300_devices_100k_fdb_100_parallel(tmp_path, monkeypatch):
    db = str(tmp_path / "fabric.db")
    stamp = datetime.now(timezone.utc).isoformat()
    allowed = {f"d{i}" for i in range(300)}
    conn = sqlite3.connect(db)
    try:
        conn.executescript("""
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
        for i in range(1, 10):
            agg = f"d{i}"
            p, q = f"GE1/0/{i}", "GE1/0/1"
            interfaces.extend([port("d0", p, "trunk"), port(agg, q, "trunk")])
            links.append(link("d0", agg, p, q))
        for i in range(10, 300):
            agg, access = f"d{1 + (i - 10) % 9}", f"d{i}"
            p, q = f"GE1/0/{2 + (i - 10) // 9}", "GE1/0/1"
            interfaces.extend([port(agg, p, "trunk"), port(access, q, "trunk"),
                               port(access, "GE1/0/2", "access")])
            links.append(link(agg, access, p, q))
        conn.executemany("INSERT INTO interfaces VALUES (?,?,?,?,?,?,?,?,?,?,?)", interfaces)
        conn.executemany("INSERT INTO topology_links VALUES (?,?,?,?,?,?,?,?,?)", links)

        def row(device, mac, name, classification):
            return (device, mac, "7", name, classification, "tenant-default",
                    "site", "space", "resolved", "dynamic", 1, "recent", "valid", stamp)

        records, targets = [], []
        for h in range(33334):
            i = 10 + h % 290
            a, p = 1 + (i - 10) % 9, 2 + (i - 10) // 9
            mac = "02:" + ":".join(f"{(h >> shift) & 255:02x}" for shift in (32, 24, 16, 8, 0))
            records.extend([
                row("d0", mac, f"GE1/0/{a}", "trunk_tagged_interface"),
                row(f"d{a}", mac, f"GE1/0/{p}", "trunk_tagged_interface"),
                row(f"d{i}", mac, "GE1/0/2", "access_edge"),
            ])
            targets.append((mac, f"d{i}"))
        conn.executemany("INSERT INTO fdb VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", records)
        conn.commit()
        assert len(records) == 100002
        assert len(links) == 299
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
        reader = sqlite3.connect(db)
        reader.row_factory = _dict_row
        statements = []
        reader.set_trace_callback(statements.append)
        try:
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
            assert len(statements) == 9
        finally:
            reader.close()

    with ThreadPoolExecutor(max_workers=100) as pool:
        list(pool.map(locate, [targets[i * 331] for i in range(100)]))
