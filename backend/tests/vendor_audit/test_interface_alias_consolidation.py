from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations.m0036_consolidate_interface_aliases import upgrade
import services.cmdb_service as cmdb_service
from services.cmdb_service import list_cmdb_interfaces


def _interface_schema(conn: postgresql_test_driver.Connection) -> None:
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
            parent_interface_id TEXT, lag_id TEXT, last_change TEXT, last_flapped TEXT, last_seen TEXT,
            interface_role TEXT NOT NULL DEFAULT 'unclassified',
            utilization_warn_pct NUMERIC(5,2) NOT NULL DEFAULT 60,
            utilization_high_pct NUMERIC(5,2) NOT NULL DEFAULT 75,
            utilization_critical_pct NUMERIC(5,2) NOT NULL DEFAULT 90
        );
        CREATE TABLE devices (id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT, status TEXT);
        CREATE TABLE vrfs (id TEXT PRIMARY KEY, vrf_name TEXT);
        CREATE TABLE ip_addresses (id TEXT PRIMARY KEY, device_id TEXT, interface_id TEXT, interface_name TEXT, ip_address TEXT, address TEXT, updated_at TEXT);
        CREATE TABLE ip_inventory (ip TEXT, mask TEXT, device_id TEXT, interface TEXT, type TEXT, last_seen TEXT);
        CREATE TABLE topology_links (id TEXT PRIMARY KEY, source_interface_id TEXT, target_interface_id TEXT);
        CREATE TABLE interface_status_history (id TEXT PRIMARY KEY, interface_id TEXT);
        """
    )


def _insert_interface(
    conn: postgresql_test_driver.Connection,
    interface_id: str,
    device_id: str,
    interface_name: str,
    *,
    primary_ip: str = "",
    ip_address: str = "",
    ip_enabled: int = 1,
    admin_status: str = "up",
    oper_status: str = "up",
    description: str = "",
) -> None:
    conn.execute(
        """INSERT INTO interfaces (
               id, device_id, interface_name, description, admin_status, oper_status,
               mac_address, speed, bandwidth, interface_type, switchport_mode,
               access_vlan, native_vlan, allowed_vlans, primary_ip, ip_address,
               ip_enabled, interface_role
           ) VALUES (?, ?, ?, ?, ?, ?, '', 0, 0, 'physical', 'routed', NULL, NULL, '', ?, ?, ?, 'unclassified')""",
        (interface_id, device_id, interface_name, description, admin_status, oper_status,
         primary_ip, ip_address, ip_enabled),
    )


def test_cmdb_unique_interface_candidates_page_and_summarize_in_sql(monkeypatch) -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    _interface_schema(conn)
    conn.execute("INSERT INTO devices VALUES ('dev-1', 'switch-a', '192.0.2.1', 'h3c_comware', 'online')")
    for index in range(1, 6):
        _insert_interface(
            conn,
            f"intf-{index}",
            "dev-1",
            f"GE1/0/{index}",
            primary_ip="198.51.100.1" if index == 1 else "",
            oper_status="up" if index in {1, 2, 4} else "down",
        )
    conn.execute("INSERT INTO topology_links VALUES ('link-1', 'intf-2', NULL)")
    calls = 0
    executed_sql: list[str] = []
    shared_normalizer = cmdb_service._normalize_interface_name_cached
    shared_execute = conn.execute

    def count_normalizations(value: str | None) -> str:
        nonlocal calls
        calls += 1
        return shared_normalizer(value)

    def record_sql(statement: str, params=None):
        executed_sql.append(statement)
        return shared_execute(statement, params)

    monkeypatch.setattr(cmdb_service, "_normalize_interface_name_cached", count_normalizations)
    monkeypatch.setattr(conn, "execute", record_sql)

    result = list_cmdb_interfaces(conn, page=2, page_size=2)
    with_ip = list_cmdb_interfaces(conn, has_ip=True, page=1, page_size=2)
    out_of_range = list_cmdb_interfaces(conn, page=9, page_size=2)

    assert result["total"] == 5
    assert [item["id"] for item in result["items"]] == ["intf-3", "intf-4"]
    assert result["summary"] == {"total": 5, "with_ip": 1, "oper_up": 3, "with_links": 1}
    assert result["device_options"] == [{"value": "dev-1", "label": "switch-a"}]
    assert with_ip["total"] == 1
    assert [item["id"] for item in with_ip["items"]] == ["intf-1"]
    assert with_ip["summary"] == {"total": 1, "with_ip": 1, "oper_up": 1, "with_links": 0}
    assert out_of_range["total"] == 5
    assert out_of_range["items"] == []
    assert out_of_range["summary"] == result["summary"]
    assert calls >= result["total"]
    page_sql = [
        statement for statement in executed_sql
        if "LIMIT ? OFFSET ?" in statement
        and "FROM interfaces i LEFT JOIN devices d ON d.id = i.device_id" in statement
    ]
    assert len(page_sql) == 3


def test_migration_merges_alias_rows_and_repoints_references() -> None:
    conn = postgresql_test_driver.connect()
    _interface_schema(conn)
    conn.execute(
        "INSERT INTO interfaces ("
        "id, device_id, interface_name, name_raw, name_display, description, "
        "admin_status, oper_status, mac_address, speed, bandwidth, mtu, "
        "interface_type, switchport_mode, access_vlan, native_vlan, allowed_vlans, "
        "primary_ip, ip_address, ip_prefix_length, is_l3, ip_enabled, vrf_id, "
        "parent_interface_id, lag_id, last_change, last_flapped, last_seen) VALUES ("
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("short", "dev-1", "GE1/0/1", "GE1/0/1", "GE1/0/1", "", "up", "up", "", 0, 0, 1500, "physical", "routed", None, None, "", "10.0.0.1", "10.0.0.1", 24, 1, 1, None, None, None, None, None, None),
    )
    conn.execute(
        "INSERT INTO interfaces ("
        "id, device_id, interface_name, name_raw, name_display, description, "
        "admin_status, oper_status, mac_address, speed, bandwidth, mtu, "
        "interface_type, switchport_mode, access_vlan, native_vlan, allowed_vlans, "
        "primary_ip, ip_address, ip_prefix_length, is_l3, ip_enabled, vrf_id, "
        "parent_interface_id, lag_id, last_change, last_flapped, last_seen) VALUES ("
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("long", "dev-1", "GigabitEthernet1/0/1", "GigabitEthernet1/0/1", "GigabitEthernet1/0/1", "old", "unknown", "unknown", "", 0, 0, 1500, "physical", "routed", None, None, "", "", "", None, 0, 0, None, None, None, None, None, None),
    )
    conn.execute("INSERT INTO ip_addresses VALUES ('ip-1', 'dev-1', 'long', 'GigabitEthernet1/0/1', '10.0.0.1', '', '')")
    conn.execute("INSERT INTO topology_links VALUES ('link-1', 'long', NULL)")
    conn.execute("INSERT INTO interface_status_history VALUES ('history-1', 'long')")

    upgrade(conn.cursor(), True)

    rows = conn.execute("SELECT id, interface_name FROM interfaces WHERE device_id = 'dev-1'").fetchall()
    assert [tuple(row) for row in rows] == [("short", "GE1/0/1")]
    assert conn.execute("SELECT interface_id FROM ip_addresses WHERE id = 'ip-1'").fetchone()[0] == "short"
    assert conn.execute("SELECT source_interface_id FROM topology_links WHERE id = 'link-1'").fetchone()[0] == "short"
    assert conn.execute("SELECT interface_id FROM interface_status_history WHERE id = 'history-1'").fetchone()[0] == "short"


def test_short_loop_aliases_share_one_identity() -> None:
    conn = postgresql_test_driver.connect()
    _interface_schema(conn)
    for interface_id, name in (("short", "Loop0"), ("long", "LoopBack0")):
        conn.execute(
            "INSERT INTO interfaces ("
            "id, device_id, interface_name, name_raw, name_display, description, "
            "admin_status, oper_status, mac_address, speed, bandwidth, mtu, "
            "interface_type, switchport_mode, access_vlan, native_vlan, allowed_vlans, "
            "primary_ip, ip_address, ip_prefix_length, is_l3, ip_enabled, vrf_id, "
            "parent_interface_id, lag_id, last_change, last_flapped, last_seen) VALUES ("
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (interface_id, "dev-1", name, name, name, "", "up" if interface_id == "short" else "unknown", "up" if interface_id == "short" else "unknown", "", 0, 0, 1500, "physical", "routed", None, None, "", "10.0.0.1", "10.0.0.1", 32, 1, 1, None, None, None, None, None, None),
        )

    upgrade(conn.cursor(), True)

    assert conn.execute("SELECT COUNT(*) FROM interfaces WHERE device_id = 'dev-1'").fetchone()[0] == 1


def test_cmdb_listing_does_not_append_inventory_alias_as_second_row() -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    _interface_schema(conn)
    conn.execute("INSERT INTO devices VALUES ('dev-1', 'S6850-3', '10.254.0.3', 'h3c_comware', 'online')")
    conn.execute(
        "INSERT INTO interfaces ("
        "id, device_id, interface_name, name_raw, name_display, description, "
        "admin_status, oper_status, mac_address, speed, bandwidth, mtu, "
        "interface_type, switchport_mode, access_vlan, native_vlan, allowed_vlans, "
        "primary_ip, ip_address, ip_prefix_length, is_l3, ip_enabled, vrf_id, "
        "parent_interface_id, lag_id, last_change, last_flapped, last_seen) VALUES ("
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("intf-1", "dev-1", "GE1/0/1", "GE1/0/1", "GE1/0/1", "", "up", "up", "", 0, 0, 1500, "physical", "routed", None, None, "", "10.254.35.1", "10.254.35.1", 24, 1, 1, None, None, None, None, None, None),
    )
    conn.execute("INSERT INTO ip_inventory VALUES ('10.254.35.1', '255.255.255.0', 'dev-1', 'GigabitEthernet1/0/1', 'physical', '2026-07-26T11:10:29+08:00')")
    conn.execute("INSERT INTO ip_inventory VALUES ('192.0.2.10', '255.255.255.0', 'missing-device', 'GE1/0/2', 'physical', '2026-07-26T11:10:29+08:00')")
    conn.execute("INSERT INTO ip_inventory VALUES ('192.0.2.11', '255.255.255.0', NULL, 'GE1/0/3', 'physical', '2026-07-26T11:10:29+08:00')")

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
    assert conn.execute("SELECT COUNT(*) FROM ip_inventory").fetchone()[0] == 3


def test_cmdb_pagination_deduplicates_aliases_before_slicing_and_keeps_total_stable() -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    _interface_schema(conn)
    conn.execute("INSERT INTO devices VALUES ('dev-1', 'switch-a', '192.0.2.1', 'h3c_comware', 'online')")
    _insert_interface(conn, "short", "dev-1", "GE1/0/1", admin_status="unknown", oper_status="unknown")
    _insert_interface(
        conn, "long", "dev-1", "GigabitEthernet1/0/1",
        primary_ip="192.0.2.11", ip_address="192.0.2.11",
    )
    _insert_interface(conn, "other", "dev-1", "GE1/0/2")
    conn.execute("INSERT INTO topology_links VALUES ('link-1', 'short', NULL)")

    first = list_cmdb_interfaces(conn, page=1, page_size=1)
    second = list_cmdb_interfaces(conn, page=2, page_size=1)
    second_again = list_cmdb_interfaces(conn, page=2, page_size=1)
    with_ip = list_cmdb_interfaces(conn, has_ip=True, page=1, page_size=1)
    without_ip = list_cmdb_interfaces(conn, has_ip=False, page=1, page_size=5)
    legacy = list_cmdb_interfaces(conn)

    assert first["total"] == second["total"] == second_again["total"] == 2
    assert first["total_pages"] == second["total_pages"] == 2
    assert [item["id"] for item in first["items"]] == ["long"]
    assert [item["id"] for item in second["items"]] == ["other"]
    assert [item["id"] for item in second_again["items"]] == ["other"]
    assert with_ip["total"] == 1
    assert [item["id"] for item in with_ip["items"]] == ["long"]
    assert without_ip["total"] == 2
    assert [item["id"] for item in without_ip["items"]] == ["short", "other"]
    assert [item["id"] for item in legacy] == ["long", "other"]
    assert first["summary"] == second["summary"] == {
        "total": 2,
        "with_ip": 1,
        "oper_up": 2,
        "with_links": 1,
    }


def test_cmdb_paged_ip_inventory_fallback_obeys_scope_search_and_is_read_only() -> None:
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    _interface_schema(conn)
    conn.execute("ALTER TABLE devices ADD COLUMN tenant_id TEXT")
    conn.execute("ALTER TABLE devices ADD COLUMN site_id TEXT")
    conn.execute(
        "INSERT INTO devices (id, hostname, ip_address, platform, status, tenant_id, site_id) "
        "VALUES ('dev-1', 'switch-a', '192.0.2.1', 'h3c_comware', 'online', 'tenant-a', 'site-a')"
    )
    conn.execute(
        "INSERT INTO devices (id, hostname, ip_address, platform, status, tenant_id, site_id) "
        "VALUES ('dev-2', 'switch-b', '192.0.2.2', 'h3c_comware', 'online', 'tenant-b', 'site-b')"
    )
    _insert_interface(conn, "fallback-skeleton", "dev-1", "GE1/0/2", oper_status="up")
    _insert_interface(conn, "disabled-skeleton", "dev-1", "GE1/0/3", ip_enabled=0)
    conn.execute(
        "INSERT INTO ip_inventory VALUES "
        "('198.51.100.44', '255.255.255.0', 'dev-1', 'GigabitEthernet1/0/2', 'physical', '2026-10-27T08:00:00Z')"
    )
    conn.execute(
        "INSERT INTO ip_inventory VALUES "
        "('198.51.100.45', '255.255.255.0', 'dev-1', 'GE1/0/3', 'physical', '2026-10-27T08:00:00Z')"
    )
    conn.execute(
        "INSERT INTO ip_inventory VALUES "
        "('198.51.100.99', '255.255.255.0', 'dev-2', 'GE1/0/9', 'physical', '2026-10-27T08:00:00Z')"
    )
    conn.execute(
        "INSERT INTO ip_inventory VALUES "
        "('203.0.113.10', '255.255.255.0', 'missing-device', 'GE1/0/10', 'physical', '2026-10-27T08:00:00Z')"
    )
    conn.execute(
        "INSERT INTO ip_inventory VALUES "
        "('203.0.113.11', '255.255.255.0', NULL, 'GE1/0/11', 'physical', '2026-10-27T08:00:00Z')"
    )
    inventory_count_before = conn.execute("SELECT COUNT(*) FROM ip_inventory").fetchone()[0]

    fallback = list_cmdb_interfaces(
        conn,
        has_ip=True,
        device_id="dev-1",
        search="198.51.100.44",
        page=1,
        page_size=1,
        tenant_id="tenant-a",
        site_ids=("site-a",),
    )
    scoped_inventory = list_cmdb_interfaces(
        conn,
        has_ip=True,
        device_id="dev-1",
        page=1,
        page_size=5,
        tenant_id="tenant-a",
        site_ids=("site-a",),
    )
    out_of_scope = list_cmdb_interfaces(
        conn,
        has_ip=True,
        search="198.51.100.99",
        page=1,
        page_size=1,
        tenant_id="tenant-a",
        site_ids=("site-a",),
    )
    no_ip = list_cmdb_interfaces(
        conn,
        has_ip=False,
        device_id="dev-1",
        search="GE1/0/2",
        page=1,
        page_size=5,
        tenant_id="tenant-a",
        site_ids=("site-a",),
    )

    assert fallback["total"] == 1
    assert fallback["summary"]["with_ip"] == 1
    assert fallback["summary"]["oper_up"] == 0
    assert fallback["items"][0]["interface_name"] == "GigabitEthernet1/0/2"
    assert fallback["items"][0]["interface_ip"] == "198.51.100.44"
    assert fallback["items"][0]["interface_ip_source"] == "ip_inventory"
    assert scoped_inventory["total"] == 1
    assert out_of_scope["total"] == 0
    assert no_ip["total"] == 1
    assert no_ip["items"][0]["id"] == "fallback-skeleton"
    assert conn.execute("SELECT COUNT(*) FROM ip_inventory").fetchone()[0] == inventory_count_before
