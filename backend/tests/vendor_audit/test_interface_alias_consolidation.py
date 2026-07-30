import sqlite3

from database.migrations.m0036_consolidate_interface_aliases import upgrade
from services.cmdb_service import list_cmdb_interfaces


def _interface_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE interfaces (
            id TEXT PRIMARY KEY, device_id TEXT, interface_name TEXT,
            name_raw TEXT, name_display TEXT, description TEXT, admin_status TEXT,
            oper_status TEXT, mac_address TEXT, speed REAL, bandwidth REAL,
            mtu INTEGER, interface_type TEXT, switchport_mode TEXT,
            access_vlan INTEGER, native_vlan INTEGER, allowed_vlans TEXT,
            primary_ip TEXT, ip_address TEXT, ip_prefix_length INTEGER,
            is_l3 INTEGER, ip_enabled INTEGER, vrf_id TEXT,
            parent_interface_id TEXT, lag_id TEXT, last_change TEXT, last_flapped TEXT, last_seen TEXT
        );
        CREATE TABLE devices (id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT, status TEXT);
        CREATE TABLE vrfs (id TEXT PRIMARY KEY, vrf_name TEXT);
        CREATE TABLE ip_addresses (id TEXT PRIMARY KEY, device_id TEXT, interface_id TEXT, interface_name TEXT, ip_address TEXT, address TEXT, updated_at TEXT);
        CREATE TABLE ip_inventory (ip TEXT, mask TEXT, device_id TEXT, interface TEXT, type TEXT, last_seen TEXT);
        CREATE TABLE topology_links (id TEXT PRIMARY KEY, source_interface_id TEXT, target_interface_id TEXT);
        CREATE TABLE interface_status_history (id TEXT PRIMARY KEY, interface_id TEXT);
        """
    )


def test_migration_merges_alias_rows_and_repoints_references() -> None:
    conn = sqlite3.connect(":memory:")
    _interface_schema(conn)
    conn.execute(
        "INSERT INTO interfaces VALUES ("
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("short", "dev-1", "GE1/0/1", "GE1/0/1", "GE1/0/1", "", "up", "up", "", 0, 0, 1500, "physical", "routed", None, None, "", "10.0.0.1", "10.0.0.1", 24, 1, 1, None, None, None, None, None, None),
    )
    conn.execute(
        "INSERT INTO interfaces VALUES ("
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("long", "dev-1", "GigabitEthernet1/0/1", "GigabitEthernet1/0/1", "GigabitEthernet1/0/1", "old", "unknown", "unknown", "", 0, 0, 1500, "physical", "routed", None, None, "", "", "", None, 0, 0, None, None, None, None, None, None),
    )
    conn.execute("INSERT INTO ip_addresses VALUES ('ip-1', 'dev-1', 'long', 'GigabitEthernet1/0/1', '10.0.0.1', '', '')")
    conn.execute("INSERT INTO topology_links VALUES ('link-1', 'long', NULL)")
    conn.execute("INSERT INTO interface_status_history VALUES ('history-1', 'long')")

    upgrade(conn.cursor(), False)

    rows = conn.execute("SELECT id, interface_name FROM interfaces WHERE device_id = 'dev-1'").fetchall()
    assert rows == [("short", "GE1/0/1")]
    assert conn.execute("SELECT interface_id FROM ip_addresses WHERE id = 'ip-1'").fetchone()[0] == "short"
    assert conn.execute("SELECT source_interface_id FROM topology_links WHERE id = 'link-1'").fetchone()[0] == "short"
    assert conn.execute("SELECT interface_id FROM interface_status_history WHERE id = 'history-1'").fetchone()[0] == "short"


def test_short_loop_aliases_share_one_identity() -> None:
    conn = sqlite3.connect(":memory:")
    _interface_schema(conn)
    for interface_id, name in (("short", "Loop0"), ("long", "LoopBack0")):
        conn.execute(
            "INSERT INTO interfaces VALUES ("
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (interface_id, "dev-1", name, name, name, "", "up" if interface_id == "short" else "unknown", "up" if interface_id == "short" else "unknown", "", 0, 0, 1500, "physical", "routed", None, None, "", "10.0.0.1", "10.0.0.1", 32, 1, 1, None, None, None, None, None, None),
        )

    upgrade(conn.cursor(), False)

    assert conn.execute("SELECT COUNT(*) FROM interfaces WHERE device_id = 'dev-1'").fetchone()[0] == 1


def test_cmdb_listing_does_not_append_inventory_alias_as_second_row() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _interface_schema(conn)
    conn.execute("INSERT INTO devices VALUES ('dev-1', 'S6850-3', '10.254.0.3', 'h3c_comware', 'online')")
    conn.execute(
        "INSERT INTO interfaces VALUES ("
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("intf-1", "dev-1", "GE1/0/1", "GE1/0/1", "GE1/0/1", "", "up", "up", "", 0, 0, 1500, "physical", "routed", None, None, "", "10.254.35.1", "10.254.35.1", 24, 1, 1, None, None, None, None, None, None),
    )
    conn.execute("INSERT INTO ip_inventory VALUES ('10.254.35.1', '255.255.255.0', 'dev-1', 'GigabitEthernet1/0/1', 'physical', '2026-07-26T11:10:29+08:00')")

    items = list_cmdb_interfaces(conn, has_ip=True)

    assert len(items) == 1
    assert items[0]["interface_name"] == "GE1/0/1"
    assert items[0]["interface_ip"] == "10.254.35.1"

    paged = list_cmdb_interfaces(conn, has_ip=True, page=1, page_size=1)
    assert paged["total"] == 1
    assert paged["page"] == 1
    assert paged["page_size"] == 1
    assert len(paged["items"]) == 1
    assert paged["summary"]["with_ip"] == 1
