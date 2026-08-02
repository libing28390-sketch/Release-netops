from __future__ import annotations

from datetime import datetime, timedelta, timezone

from database.migrations.m0064_wan_link_monitoring import upgrade
from services.wan_link_service import _calculate_rates, _deduplicate_interface_options, _match_interface


def test_wan_migration_is_idempotent_on_sqlite() -> None:
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE interfaces (id TEXT, device_id TEXT, interface_name TEXT)")
        upgrade(conn, use_pg=False)
        upgrade(conn, use_pg=False)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(interfaces)")}
    finally:
        conn.close()

    assert {"wan_links", "wan_link_samples_1m", "wan_link_current_status", "wan_alert_rules", "wan_alert_events"}.issubset(tables)
    assert "if_index" in columns


def test_interface_selection_prefers_ifindex_over_name() -> None:
    link = {"if_index": 12, "interface_name": "GigabitEthernet1/0/1"}
    items = [
        {"if_index": 12, "name": "Port-Channel1"},
        {"if_index": 13, "name": "GigabitEthernet1/0/1"},
    ]
    assert _match_interface(link, items)["name"] == "Port-Channel1"


def test_interface_options_deduplicate_vendor_aliases() -> None:
    rows = [
        {"id": "short", "device_id": "device-1", "interface_name": "Et0/0"},
        {"id": "long", "device_id": "device-1", "interface_name": "Ethernet0/0"},
        {"id": "other-device", "device_id": "device-2", "interface_name": "Ethernet0/0"},
    ]

    result = _deduplicate_interface_options(rows)

    assert [row["id"] for row in result] == ["short", "other-device"]


def test_counter_delta_uses_actual_interval_and_contracted_bandwidth() -> None:
    sampled_at = datetime.now(timezone.utc).replace(microsecond=0)
    link = {"contracted_download_bps": 200_000_000, "contracted_upload_bps": 100_000_000, "collection_interval_sec": 60}
    current = {"in_octets": 1_500_000_000, "out_octets": 750_000_000, "speed_mbps": 1000}
    previous = {"in_octets": 0, "out_octets": 0, "sampled_at": (sampled_at - timedelta(seconds=60)).isoformat(), "collection_status": "success"}

    rates, flags = _calculate_rates(link, current, previous, sampled_at)

    assert flags == {}
    assert rates["download_bps"] == 200_000_000
    assert rates["upload_bps"] == 100_000_000
    assert rates["download_util_pct"] == 100
    assert rates["upload_util_pct"] == 100


def test_counter_reset_never_becomes_zero_rate() -> None:
    sampled_at = datetime.now(timezone.utc).replace(microsecond=0)
    link = {"contracted_download_bps": 1_000_000_000, "contracted_upload_bps": 1_000_000_000, "collection_interval_sec": 60}
    current = {"in_octets": 10, "out_octets": 10, "speed_mbps": 1000}
    previous = {"in_octets": 1000, "out_octets": 1000, "sampled_at": (sampled_at - timedelta(seconds=60)).isoformat(), "collection_status": "success"}

    rates, flags = _calculate_rates(link, current, previous, sampled_at)

    assert rates["download_bps"] is None
    assert rates["upload_bps"] is None
    assert flags["download_counter_reset"] is True
    assert flags["upload_counter_reset"] is True


def test_rate_above_reported_interface_speed_is_retained_with_quality_flag() -> None:
    sampled_at = datetime.now(timezone.utc).replace(microsecond=0)
    link = {"contracted_download_bps": 10_000_000, "contracted_upload_bps": 10_000_000, "collection_interval_sec": 60}
    current = {"in_octets": 150_000_000, "out_octets": 150_000_000, "speed_mbps": 10}
    previous = {"in_octets": 0, "out_octets": 0, "sampled_at": (sampled_at - timedelta(seconds=60)).isoformat(), "collection_status": "success"}

    rates, flags = _calculate_rates(link, current, previous, sampled_at)

    assert rates["download_bps"] == 20_000_000
    assert rates["upload_bps"] == 20_000_000
    assert rates["download_util_pct"] == 200
    assert rates["upload_util_pct"] == 200
    assert flags["download_over_interface_speed"] is True
    assert flags["upload_over_interface_speed"] is True


def test_wan_link_upsert_persists_contract_bandwidth_and_default_rules(isolated_db) -> None:
    from database import get_db_connection
    from services.wan_link_service import upsert_wan_link

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, site, snmp_community, snmp_port) VALUES (?, ?, ?, ?, ?, ?)",
            ("device-1", "edge-1", "192.0.2.1", "HQ", "public", 161),
        )
        conn.execute(
            "INSERT INTO interfaces (id, device_id, interface_name, if_index, speed, oper_status) VALUES (?, ?, ?, ?, ?, ?)",
            ("interface-1", "device-1", "GigabitEthernet1/0/1", 12, 1_000_000_000, "up"),
        )
        conn.commit()
    finally:
        conn.close()

    item = upsert_wan_link({
        "link_name": "HQ primary", "device_id": "device-1", "interface_id": "interface-1",
        "contracted_download_mbps": 200, "contracted_upload_mbps": 100, "provider": "Test ISP",
    })

    assert item["contracted_download_bps"] == 200_000_000
    assert item["contracted_upload_bps"] == 100_000_000
    conn = get_db_connection()
    try:
        rule_count = conn.execute("SELECT COUNT(*) FROM wan_alert_rules WHERE link_id = ?", (item["id"],)).fetchone()[0]
    finally:
        conn.close()
    assert rule_count == 4


def test_wan_link_options_match_devices_by_site_id(isolated_db) -> None:
    from database import get_db_connection
    from services.wan_link_service import list_wan_link_options, upsert_wan_link

    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO sites (id, site_code, site_name) VALUES (?, ?, ?)", ("site-hq", "HQ", "HQ"))
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, site, site_id, platform) VALUES (?, ?, ?, ?, ?, ?)",
            ("device-hq", "edge-hq", "192.0.2.10", "site-hq", "site-hq", "cisco_ios"),
        )
        conn.execute("UPDATE devices SET role = ?, device_category = ? WHERE id = ?", ("core", "switch", "device-hq"))
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, site, site_id, platform, role, device_category) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("device-access", "access-hq", "192.0.2.11", "site-hq", "site-hq", "cisco_ios", "access", "switch"),
        )
        conn.execute(
            "INSERT INTO interfaces (id, device_id, interface_name, if_index, speed, oper_status) VALUES (?, ?, ?, ?, ?, ?)",
            ("interface-hq", "device-hq", "GigabitEthernet0/0", 7, 1_000_000_000, "up"),
        )
        conn.commit()
    finally:
        conn.close()

    options = list_wan_link_options(site_id="site-hq")

    assert [device["id"] for device in options["devices"]] == ["device-hq"]
    assert options["devices"][0]["site_id"] == "site-hq"
    assert options["devices"][0]["site_name"] == "HQ"
    assert [item["id"] for item in options["interfaces"]] == ["interface-hq"]
    access_options = list_wan_link_options(device_id="device-access")
    assert access_options["devices"] == []
    assert access_options["interfaces"] == []

    link = upsert_wan_link({
        "link_name": "HQ primary",
        "site_id": "site-hq",
        "site_name": "HQ",
        "device_id": "device-hq",
        "interface_id": "interface-hq",
        "contracted_download_mbps": 200,
        "contracted_upload_mbps": 100,
        "provider": "中国电信",
    })
    assert link["site_id"] == "site-hq"
    assert link["site_name"] == "HQ"
