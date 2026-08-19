from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json


def test_network_monitoring_server_filter_is_safe_for_postgresql_placeholders() -> None:
    """A literal ``%server%`` must not become a PostgreSQL ``%s`` bind."""
    from database.core import _adapt_pg_sql

    adapted = _adapt_pg_sql(
        "LOWER(COALESCE(d.platform, '')) NOT LIKE '%' || 'server' || '%'"
    )

    assert "%s" not in adapted
    assert "server" in adapted

def test_network_monitoring_list_is_server_paginated_and_server_devices_are_excluded(isolated_db) -> None:
    from api.monitoring import list_monitoring_network_devices
    from database import get_db_connection

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO sites (id, site_code, site_name, status) VALUES (?, ?, ?, ?)",
            ("site-hq", "HQ", "华北数据中心", "active"),
        )
        for index in range(65):
            conn.execute(
                """
                INSERT INTO devices (id, hostname, ip_address, platform, status,
                                     compliance, role, site, site_id, device_category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"network-{index:03d}",
                    f"edge-{index:03d}",
                    f"192.0.2.{index + 1}",
                    "h3c_comware",
                    "online" if index % 2 == 0 else "offline",
                    "unknown",
                    "core",
                    "site-hq",
                    "site-hq",
                    "network_device",
                ),
            )
        conn.execute(
            """
            INSERT INTO devices (id, hostname, ip_address, platform, status,
                                 compliance, role, site, site_id, device_category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("server-001", "linux-server", "192.0.2.200", "linux", "online", "unknown", "server", "site-hq", "site-hq", "server"),
        )
        conn.execute(
            """
            INSERT INTO physical_assets (id, asset_type, hostname, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("asset-server", "server", "asset-backed-server", "2026-08-18T00:00:00+00:00", "2026-08-18T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO devices (id, hostname, ip_address, platform, status,
                                 compliance, role, site, site_id, device_category, asset_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("asset-server-device", "asset-backed-server", "192.0.2.201", "h3c_comware", "online", "unknown", "core", "site-hq", "site-hq", "network_device", "asset-server"),
        )
        conn.commit()
    finally:
        conn.close()

    first_page = list_monitoring_network_devices(q="", site_id="all", page=1, page_size=30, status="all")
    second_page = list_monitoring_network_devices(q="", site_id="all", page=2, page_size=30, status="all")
    search_page = list_monitoring_network_devices(q="edge-064", site_id="all", page=1, page_size=30, status="all")

    assert first_page["total"] == 65
    assert len(first_page["items"]) == 30
    assert len(second_page["items"]) == 30
    assert all(item["device_category"] != "server" for item in first_page["items"] + second_page["items"])
    assert all(item["id"] != "asset-server-device" for item in first_page["items"] + second_page["items"])
    assert first_page["site_options"] == [{"id": "site-hq", "name": "华北数据中心", "device_count": 65}]
    assert search_page["total"] == 1
    assert search_page["items"][0]["hostname"] == "edge-064"


def test_network_monitoring_realtime_returns_only_up_interfaces(isolated_db) -> None:
    from api.monitoring import monitoring_device_realtime
    from database import get_db_connection

    sampled_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    invalid_sampled_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, platform, status) VALUES (?, ?, ?, ?, ?)",
            ("realtime-device", "edge-realtime", "192.0.2.250", "h3c_comware", "online"),
        )
        conn.executemany(
            """
            INSERT INTO interface_telemetry_raw
                (ts, device_id, interface_name, status, speed_mbps,
                 in_bps, out_bps, bw_in_pct, bw_out_pct,
                 in_pkts, out_pkts, in_errors, out_errors, in_discards, out_discards)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (sampled_at, "realtime-device", "GigabitEthernet1/0/1", "up", 1000, 10, 20, 1, 2, 1, 1, 0, 0, 0, 0),
                (sampled_at, "realtime-device", "GigabitEthernet1/0/2", "down", 1000, 999, 999, 99, 99, 9, 9, 4, 5, 6, 7),
                # These rows may exist from the pre-physical-interface
                # collector.  The realtime API must not leak them back into
                # the monitoring table after the collector is corrected.
                (sampled_at, "realtime-device", "InLoopBack0", "up", 1000, 100, 100, 10, 10, 10, 10, 0, 0, 0, 0),
                (sampled_at, "realtime-device", "Register-Tunnel0", "up", 1000, 200, 200, 20, 20, 20, 20, 0, 0, 0, 0),
                # A legacy NULL sample may remain in the database.  It should
                # not cause the API to invent a value or a user-facing
                # "unavailable" status.
                (invalid_sampled_at, "realtime-device", "GigabitEthernet1/0/2", "up", 1000, None, None, None, None, None, None, None, None, None, None),
            ],
        )
        conn.execute(
            """
            INSERT INTO snmp_interface_counter_samples
                (device_id, profile_id, config_hash, values_json, sampled_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "realtime-device",
                "builtin-if-mib",
                "test-hash",
                json.dumps({"2": {"name": "GigabitEthernet1/0/2", "in_octets": 123, "out_octets": 456, "counter_width": 64}}),
                sampled_at,
                sampled_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    payload = monitoring_device_realtime("realtime-device", window_minutes=15, limit=100)

    assert [item["interface_name"] for item in payload["latest_interfaces"]] == ["GigabitEthernet1/0/1", "GigabitEthernet1/0/2"]
    assert all("LoopBack" not in item["interface_name"] and "Tunnel" not in item["interface_name"] for item in payload["latest_interfaces"])
    assert payload["summary"]["in_bps"] == 10
    assert payload["summary"]["out_bps"] == 20
    assert payload["summary"]["errors"] == 0
    assert "counter_unavailable" not in payload["summary"]
    invalid = payload["latest_interfaces"][1]
    assert invalid["counter_quality"] == "raw"
    assert invalid["in_octets"] == 123
    assert invalid["out_octets"] == 456
