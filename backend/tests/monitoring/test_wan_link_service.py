from __future__ import annotations

from backend.tests import pg_catalog_assertions as pg_catalog

import asyncio
from datetime import datetime, timedelta, timezone

from database.migrations.m0064_wan_link_monitoring import upgrade
from database.migrations.m0065_wan_p0_hardening import upgrade as upgrade_p0
from database.migrations.m0162_wan_alert_ack_uniqueness import upgrade as upgrade_ack_uniqueness
from database.migrations.m0163_wan_error_discard_rates import upgrade as upgrade_rates
from services.wan_link_service import _apply_contract_utilization, _calculate_rates, _deduplicate_interface_options, _match_interface, _sample_value
from services.wan_p1_service import _valid_sample


def test_wan_migration_is_idempotent_on_postgresql() -> None:
    from backend.tests.pg_test_utils import postgresql_test_driver
    conn = postgresql_test_driver.connect()
    try:
        conn.execute("CREATE TABLE interfaces (id TEXT, device_id TEXT, interface_name TEXT)")
        upgrade(conn, use_pg=True)
        upgrade(conn, use_pg=True)
        tables = pg_catalog.table_names(conn)
        columns = pg_catalog.table_columns(conn, "interfaces")
    finally:
        conn.close()

    assert {"wan_links", "wan_link_samples_1m", "wan_link_current_status", "wan_alert_rules", "wan_alert_events"}.issubset(tables)
    assert "if_index" in columns


def test_acknowledged_alert_remains_unique_on_postgresql() -> None:
    from backend.tests.pg_test_utils import postgresql_test_driver
    conn = postgresql_test_driver.connect()
    try:
        conn.row_factory = postgresql_test_driver.Row
        conn.execute("CREATE TABLE interfaces (id TEXT, device_id TEXT, interface_name TEXT)")
        upgrade(conn, use_pg=True)
        upgrade_p0(conn, use_pg=True)
        upgrade_ack_uniqueness(conn, use_pg=True)
        conn.execute("INSERT INTO wan_alert_events (id, event_key, link_id, metric, severity, status, title, message, started_at, last_seen_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("e-1", "k-1", "link-1", "interface_down", "critical", "acknowledged", "down", "", "2026-08-23T00:00:00+00:00", "2026-08-23T00:00:00+00:00", "2026-08-23T00:00:00+00:00"))
        conn.commit()
        try:
            conn.execute("INSERT INTO wan_alert_events (id, event_key, link_id, metric, severity, status, title, message, started_at, last_seen_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("e-2", "k-2", "link-1", "interface_down", "critical", "firing", "down", "", "2026-08-23T00:01:00+00:00", "2026-08-23T00:01:00+00:00", "2026-08-23T00:01:00+00:00"))
            assert False, "acknowledged events must remain active-unique"
        except postgresql_test_driver.IntegrityError:
            conn.rollback()
        conn.execute("UPDATE wan_alert_events SET status = 'resolved' WHERE id = 'e-1'")
        conn.execute("INSERT INTO wan_alert_events (id, event_key, link_id, metric, severity, status, title, message, started_at, last_seen_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("e-2", "k-2", "link-1", "interface_down", "critical", "firing", "down", "", "2026-08-23T00:01:00+00:00", "2026-08-23T00:01:00+00:00", "2026-08-23T00:01:00+00:00"))
    finally:
        conn.close()


def test_error_discard_rate_migration_is_idempotent() -> None:
    from backend.tests.pg_test_utils import postgresql_test_driver
    conn = postgresql_test_driver.connect()
    try:
        conn.execute("CREATE TABLE interfaces (id TEXT, device_id TEXT, interface_name TEXT)")
        upgrade(conn, use_pg=True)
        upgrade_rates(conn, use_pg=True)
        upgrade_rates(conn, use_pg=True)
        columns = pg_catalog.table_columns(conn, "wan_link_samples_1m")
    finally:
        conn.close()
    assert {"in_error_rate", "out_error_rate", "in_discard_rate", "out_discard_rate"}.issubset(columns)


def test_delete_wan_link_cleans_orphaned_link_and_indirect_dependents(isolated_db) -> None:
    from database import get_db_connection
    from services.wan_link_service import delete_wan_link

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    link_id = "orphaned-wan-link"
    alert_event_id = "wan-alert-event"
    correlation_event_id = "wan-correlation-event"

    conn = get_db_connection()
    try:
        # Deliberately do not create the device/interface rows: this mirrors a
        # link left behind after its bound device was deleted.
        conn.execute(
            """
            INSERT INTO wan_links (
                id, link_name, device_id, interface_id, interface_name, if_index,
                contracted_download_bps, contracted_upload_bps, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (link_id, "Orphaned link", "deleted-device", "deleted-interface", "Et0/0", 1, 10_000_000, 10_000_000, now, now),
        )
        conn.execute(
            "INSERT INTO wan_alert_rules (id, link_id, metric, severity, duration_sec, recovery_duration_sec, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("wan-rule", link_id, "interface_down", "critical", 60, 60, now, now),
        )
        conn.execute(
            "INSERT INTO wan_alert_events (id, event_key, link_id, metric, severity, title, started_at, last_seen_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (alert_event_id, "wan-alert-key", link_id, "interface_down", "critical", "Interface down", now, now, now),
        )
        conn.execute(
            "INSERT INTO wan_alert_event_audit (id, event_id, action, created_at) VALUES (?, ?, ?, ?)",
            ("wan-alert-audit", alert_event_id, "acknowledge", now),
        )
        conn.execute(
            "INSERT INTO wan_correlation_events (id, correlation_group, root_cause_code, title, starts_at, last_seen_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (correlation_event_id, f"link:{link_id}", "egress_device_fault", "Egress device fault", now, now, now, now),
        )
        conn.execute(
            "INSERT INTO wan_correlation_evidence (id, event_id, source_type, observed_at, created_at) VALUES (?, ?, ?, ?, ?)",
            ("wan-evidence", correlation_event_id, "wan_current_status", now, now),
        )
        conn.execute(
            "INSERT INTO wan_probe_bindings (id, link_id, target_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("wan-binding", link_id, "target-1", now, now),
        )
        conn.execute(
            "INSERT INTO wan_link_group_members (group_id, link_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("wan-group", link_id, now, now),
        )
        conn.execute(
            "INSERT INTO wan_maintenance_windows (id, link_id, name, starts_at, ends_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("wan-maintenance", link_id, "Maintenance", now, now, now, now),
        )
        conn.execute(
            "INSERT INTO wan_baselines (id, link_id, weekday, hour, calculated_at) VALUES (?, ?, ?, ?, ?)",
            ("wan-baseline", link_id, 1, 1, now),
        )
        conn.execute(
            "INSERT INTO wan_capacity_recommendations (id, link_id, recommendation, period_start, period_end, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("wan-capacity", link_id, "Keep current bandwidth", now, now, now, now),
        )
        conn.execute(
            "INSERT INTO wan_link_current_status (link_id, updated_at) VALUES (?, ?)",
            (link_id, now),
        )
        conn.execute(
            "INSERT INTO wan_link_samples_1m (id, link_id, sampled_at, collection_status, created_at) VALUES (?, ?, ?, ?, ?)",
            ("wan-sample", link_id, now, "success", now),
        )
        conn.commit()
    finally:
        conn.close()

    assert delete_wan_link(link_id) is True

    conn = get_db_connection()
    try:
        assert conn.execute("SELECT 1 FROM wan_links WHERE id = ?", (link_id,)).fetchone() is None
        for table, column, value in (
            ("wan_alert_events", "link_id", link_id),
            ("wan_alert_rules", "link_id", link_id),
            ("wan_alert_event_audit", "event_id", alert_event_id),
            ("wan_correlation_events", "id", correlation_event_id),
            ("wan_correlation_evidence", "event_id", correlation_event_id),
            ("wan_probe_bindings", "link_id", link_id),
            ("wan_link_group_members", "link_id", link_id),
            ("wan_maintenance_windows", "link_id", link_id),
            ("wan_baselines", "link_id", link_id),
            ("wan_capacity_recommendations", "link_id", link_id),
            ("wan_link_current_status", "link_id", link_id),
            ("wan_link_samples_1m", "link_id", link_id),
        ):
            assert conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,)).fetchone() is None
    finally:
        conn.close()


def test_device_wan_links_are_removed_before_device_deletion(isolated_db) -> None:
    from database import get_db_connection
    from services.wan_link_service import delete_wan_links_for_device

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO wan_links (
                id, link_name, device_id, interface_id, interface_name, if_index,
                contracted_download_bps, contracted_upload_bps, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("device-wan-link", "Device link", "device-to-delete", "interface-1", "Et0/0", 1, 1_000_000, 1_000_000, now, now),
        )
        conn.execute(
            """
            INSERT INTO wan_links (
                id, link_name, device_id, interface_id, interface_name, if_index,
                contracted_download_bps, contracted_upload_bps, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("other-device-wan-link", "Other device link", "device-to-keep", "interface-2", "Et0/1", 2, 1_000_000, 1_000_000, now, now),
        )
        conn.commit()
        assert delete_wan_links_for_device(conn, "device-to-delete") == 1
        assert conn.execute("SELECT 1 FROM wan_links WHERE id = ?", ("device-wan-link",)).fetchone() is None
        assert conn.execute("SELECT 1 FROM wan_links WHERE id = ?", ("other-device-wan-link",)).fetchone() is not None
        conn.commit()
    finally:
        conn.close()


def test_interface_down_and_rollup_reject_unknown_or_directional_invalid_samples() -> None:
    assert _sample_value({"oper_status": "unknown", "collection_status": "success"}, "interface_down") is False
    assert _sample_value({"oper_status": "down", "collection_status": "partial"}, "interface_down") is False
    assert _sample_value({"oper_status": "down", "collection_status": "success"}, "interface_down") is True
    assert _valid_sample({"collection_status": "success", "quality_flags": '{"download_counter_reset": true}'}) is False
    assert _valid_sample({"collection_status": "success", "quality_flags": '{"download_counter_wrap": true}'}) is True


def test_snmp_detailed_collection_exposes_partial_walk(monkeypatch) -> None:
    import services.snmp_service as snmp_service

    async def fake_collect(*_args, **_kwargs):
        return [
            {"name": "GigabitEthernet0/0", "status": "up", "counter_width": 64, "in_octets": 100, "out_octets": 200},
            {"name": "GigabitEthernet0/1", "status": "unknown", "counter_width": None, "in_octets": None, "out_octets": None},
        ]

    monkeypatch.setattr(snmp_service, "collect_interface_data", fake_collect)
    detail = asyncio.run(snmp_service.collect_interface_data_detailed("192.0.2.1", "public"))
    assert detail["status"] == "partial"
    assert detail["error_code"] == "partial_data"
    assert detail["complete_items"] == 1


def test_interface_selection_prefers_ifindex_over_name() -> None:
    link = {"if_index": 12, "interface_name": "GigabitEthernet1/0/1"}
    items = [
        {"if_index": 12, "name": "Port-Channel1"},
        {"if_index": 13, "name": "GigabitEthernet1/0/1"},
    ]
    assert _match_interface(link, items)["name"] == "Port-Channel1"


def test_interface_options_deduplicate_vendor_aliases() -> None:
    rows = [
        {"id": "unverified-short", "device_id": "device-1", "interface_name": "Et0/0", "if_index": None},
        {"id": "verified-long", "device_id": "device-1", "interface_name": "Ethernet0/0", "if_index": 7},
        {"id": "other-device", "device_id": "device-2", "interface_name": "Ethernet0/0", "if_index": 8},
        {"id": "invalid-index", "device_id": "device-2", "interface_name": "Ethernet0/1", "if_index": 0},
    ]

    result = _deduplicate_interface_options(rows)

    assert [row["id"] for row in result] == ["verified-long", "other-device"]


def test_counter_delta_uses_actual_interval_and_contracted_bandwidth() -> None:
    sampled_at = datetime.now(timezone.utc).replace(microsecond=0)
    link = {"contracted_download_bps": 200_000_000, "contracted_upload_bps": 100_000_000, "collection_interval_sec": 60, "measurement_scope": "dedicated"}
    current = {"in_octets": 1_500_000_000, "out_octets": 750_000_000, "speed_mbps": 1000}
    previous = {"in_octets": 0, "out_octets": 0, "sampled_at": (sampled_at - timedelta(seconds=60)).isoformat(), "collection_status": "success", "quality_flags": '{"measurement_scope":"dedicated"}'}

    rates, flags = _calculate_rates(link, current, previous, sampled_at)

    assert flags == {}
    assert rates["download_bps"] == 200_000_000
    assert rates["upload_bps"] == 100_000_000
    assert rates["download_util_pct"] == 100
    assert rates["upload_util_pct"] == 100


def test_counter_reset_never_becomes_zero_rate() -> None:
    sampled_at = datetime.now(timezone.utc).replace(microsecond=0)
    link = {"contracted_download_bps": 1_000_000_000, "contracted_upload_bps": 1_000_000_000, "collection_interval_sec": 60, "measurement_scope": "dedicated"}
    current = {"in_octets": 10, "out_octets": 10, "speed_mbps": 1000}
    previous = {"in_octets": 1000, "out_octets": 1000, "sampled_at": (sampled_at - timedelta(seconds=60)).isoformat(), "collection_status": "success", "quality_flags": '{"measurement_scope":"dedicated"}'}

    rates, flags = _calculate_rates(link, current, previous, sampled_at)

    assert rates["download_bps"] is None
    assert rates["upload_bps"] is None
    assert flags["download_counter_reset"] is True
    assert flags["upload_counter_reset"] is True


def test_rate_above_reported_interface_speed_is_retained_with_quality_flag() -> None:
    sampled_at = datetime.now(timezone.utc).replace(microsecond=0)
    link = {"contracted_download_bps": 10_000_000, "contracted_upload_bps": 10_000_000, "collection_interval_sec": 60, "measurement_scope": "dedicated"}
    current = {"in_octets": 150_000_000, "out_octets": 150_000_000, "speed_mbps": 10}
    previous = {"in_octets": 0, "out_octets": 0, "sampled_at": (sampled_at - timedelta(seconds=60)).isoformat(), "collection_status": "success", "quality_flags": '{"measurement_scope":"dedicated"}'}

    rates, flags = _calculate_rates(link, current, previous, sampled_at)

    assert rates["download_bps"] == 20_000_000
    assert rates["upload_bps"] == 20_000_000
    assert rates["download_util_pct"] == 200
    assert rates["upload_util_pct"] == 200
    assert flags["download_over_interface_speed"] is True
    assert flags["upload_over_interface_speed"] is True


def test_shared_interface_keeps_aggregate_rates_but_disables_line_utilization() -> None:
    sampled_at = datetime.now(timezone.utc).replace(microsecond=0)
    link = {"contracted_download_bps": 10_000_000, "contracted_upload_bps": 10_000_000, "collection_interval_sec": 60, "measurement_scope": "shared_interface"}
    current = {"in_octets": 150_000_000, "out_octets": 75_000_000, "speed_mbps": 1000}
    previous = {"in_octets": 0, "out_octets": 0, "sampled_at": (sampled_at - timedelta(seconds=60)).isoformat(), "collection_status": "success", "quality_flags": '{"measurement_scope":"shared_interface"}'}

    rates, flags = _calculate_rates(link, current, previous, sampled_at)

    assert rates["download_bps"] == 20_000_000
    assert rates["upload_bps"] == 10_000_000
    assert rates["download_util_pct"] is None
    assert rates["upload_util_pct"] is None
    assert flags["measurement_scope_shared_interface"] is True
    assert _sample_value({"quality_flags": '{"measurement_scope":"shared_interface"}', "download_util_pct": 99}, "util_95") is None
    assert _sample_value({"quality_flags": '{"measurement_scope":"dedicated"}', "download_util_pct": 99}, "util_95") == 99


def test_unknown_measurement_scope_suppresses_contract_utilization() -> None:
    item = _apply_contract_utilization({"download_bps": 50_000_000, "upload_bps": 10_000_000, "contracted_download_bps": 100_000_000, "contracted_upload_bps": 100_000_000})
    assert item["measurement_scope"] == "shared_interface"
    assert item["download_util_pct"] is None
    assert item["upload_util_pct"] is None


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
        conn.execute(
            "INSERT INTO interfaces (id, device_id, interface_name, if_index, oper_status) VALUES (?, ?, ?, ?, ?)",
            ("interface-unverified", "device-hq", "Et0/1", None, "up"),
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
