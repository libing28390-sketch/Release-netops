from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone


def _run_async(coroutine):
    """Run a coroutine without leaving the process without a current loop."""
    try:
        return asyncio.run(coroutine)
    finally:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _sample_table() -> str:
    """Use the PostgreSQL partitioned table when the PG contract is active."""
    from database import _USE_PG

    return "wan_link_samples_1m_partitioned" if _USE_PG else "wan_link_samples_1m"


def _seed_link(conn):
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute("INSERT INTO devices (id, hostname, ip_address, site, snmp_community, snmp_port) VALUES (?, ?, ?, ?, ?, ?)", ("wan-device", "edge", "192.0.2.10", "HQ", "public", 161))
    conn.execute("INSERT INTO interfaces (id, device_id, interface_name, if_index, speed, oper_status) VALUES (?, ?, ?, ?, ?, ?)", ("wan-interface", "wan-device", "GigabitEthernet0/0", 7, 1_000_000_000, "up"))
    conn.execute("INSERT INTO wan_links (id, link_name, site_id, site_name, device_id, interface_id, interface_name, if_index, contracted_download_bps, contracted_upload_bps, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("wan-link", "HQ", "site-default", "HQ", "wan-device", "wan-interface", "GigabitEthernet0/0", 7, 200_000_000, 100_000_000, now, now))
    conn.execute("INSERT INTO wan_link_endpoints (id, link_id, side, endpoint_type, tenant_id, site_id, device_id, interface_id, if_index, endpoint_name, counter_orientation, measurement_scope, created_at, updated_at) VALUES (?, ?, 'A', 'managed', 'tenant-default', ?, ?, ?, ?, ?, 'normal', 'dedicated', ?, ?)", ("wan-endpoint-a", "wan-link", "site-default", "wan-device", "wan-interface", 7, "GigabitEthernet0/0", now, now))
    conn.commit()
    return {"id": "wan-link", "device_id": "wan-device", "interface_id": "wan-interface", "if_index": 7, "interface_name": "GigabitEthernet0/0", "contracted_download_bps": 200_000_000, "contracted_upload_bps": 100_000_000, "collection_interval_sec": 60, "direction_mode": "normal", "measurement_scope": "dedicated"}


def test_failed_collection_keeps_last_valid_rate_and_does_not_increment_down(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import _collect_link

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
    finally:
        conn.close()

    first = _run_async(_collect_link(link, {"status": "success", "items": [{"if_index": 7, "name": "GigabitEthernet0/0", "status": "up", "speed_mbps": 1000, "in_octets": 1_000_000_000, "out_octets": 500_000_000, "in_octets_hc": 1_000_000_000, "out_octets_hc": 500_000_000, "counter_width": 64, "counter_source": "ifHCInOctets/ifHCOutOctets", "counter_quality": "hc64"}]}, datetime.now(timezone.utc) - timedelta(minutes=2)))
    second = _run_async(_collect_link(link, {"status": "success", "items": [{"if_index": 7, "name": "GigabitEthernet0/0", "status": "up", "speed_mbps": 1000, "in_octets": 2_500_000_000, "out_octets": 1_250_000_000, "in_octets_hc": 2_500_000_000, "out_octets_hc": 1_250_000_000, "counter_width": 64, "counter_source": "ifHCInOctets/ifHCOutOctets", "counter_quality": "hc64"}]}, datetime.now(timezone.utc) - timedelta(minutes=1)))
    third = _run_async(_collect_link(link, {"status": "timeout", "error_code": "timeout", "error_message": "no response", "items": []}, datetime.now(timezone.utc)))
    assert first["collection_status"] == "success", first
    assert second["collection_status"] == "success", second
    assert third["collection_status"] == "timeout", third

    conn = get_db_connection()
    try:
        sample_table = _sample_table()
        rows = [dict(row) for row in conn.execute(f"SELECT * FROM {sample_table} ORDER BY sampled_at").fetchall()]
        status = dict(conn.execute("SELECT * FROM wan_link_current_status WHERE link_id = ?", ("wan-link",)).fetchone())
    finally:
        conn.close()
    assert rows[-1]["collection_status"] == "timeout"
    assert rows[-1]["download_bps"] is None
    assert rows[1]["oper_status"] == "up"
    assert status["last_success_at"] == rows[1]["sampled_at"]
    assert status["consecutive_down_count"] == 0


def test_wan_collection_and_manual_tests_do_not_poll_profile_oids(isolated_db, monkeypatch):
    from database import get_db_connection
    from services import snmp_metric_profile_service, snmp_service, wan_link_service

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
    finally:
        conn.close()

    profile_calls = []
    transport_calls = []

    def resolve_profile(device):
        profile_calls.append(device)
        return {"interface": {"in_octets_oid": "1.3.6.1.4.1.55555.10"}}

    async def collect_interfaces(*args, **kwargs):
        transport_calls.append((args, kwargs))
        return {"status": "success", "items": []}

    async def collect_interface_rows(*args, **kwargs):
        transport_calls.append((args, kwargs))
        return []

    monkeypatch.setattr(snmp_metric_profile_service, "resolve_metric_profiles", resolve_profile)
    monkeypatch.setattr(snmp_service, "collect_interface_data_detailed", collect_interfaces)
    monkeypatch.setattr(snmp_service, "collect_interface_data", collect_interface_rows)
    monkeypatch.setattr(wan_link_service, "resolve_metric_profiles", resolve_profile, raising=False)
    monkeypatch.setattr(wan_link_service, "collect_interface_data_detailed", collect_interfaces, raising=False)

    scheduled = wan_link_service.run_wan_collection_once()
    manual = _run_async(wan_link_service.test_wan_link_collection(link["id"]))
    configuration = _run_async(wan_link_service.test_wan_link_configuration({
        "device_id": "wan-device", "interface_id": "wan-interface",
    }))

    assert scheduled["results"][0]["collection_status"] == "unsupported"
    assert manual["status"] == "unsupported"
    assert manual["error_code"] == "librenms_interface_rule_unsupported"
    assert configuration["status"] == "unsupported"
    assert configuration["error_code"] == "librenms_interface_rule_unsupported"
    assert profile_calls == []
    assert transport_calls == []


def test_shared_interface_collection_hides_contract_utilization_and_resolves_util_alert(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import _collect_link

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        conn.execute(
            "UPDATE wan_link_endpoints SET measurement_scope = 'shared_interface', binding_version = 2 WHERE link_id = ? AND side = 'A'",
            (link["id"],),
        )
        conn.execute(
            "INSERT INTO wan_link_current_status (link_id, sampled_at, download_bps, upload_bps, download_util_pct, upload_util_pct, health_status, oper_status, collection_status, active_alert_count, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (link["id"], now.isoformat(), 100_000_000, 50_000_000, 50, 50, "critical", "up", "success", 1, now.isoformat()),
        )
        conn.execute(
            "INSERT INTO wan_alert_events (id, event_key, link_id, metric, severity, status, title, message, started_at, last_seen_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("shared-util-event", "shared-util-key", link["id"], "util_95", "critical", "firing", "High utilization", "stale dedicated alert", now.isoformat(), now.isoformat(), now.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    link["measurement_scope"] = "shared_interface"
    link["measurement_scope_version"] = 2
    first = _run_async(_collect_link(
        link,
        {"status": "success", "items": [{"if_index": 7, "name": "GigabitEthernet0/0", "status": "up", "speed_mbps": 1000, "in_octets": 1_000_000_000, "out_octets": 500_000_000, "counter_width": 64}]},
        now - timedelta(minutes=1),
    ))
    second = _run_async(_collect_link(
        link,
        {"status": "success", "items": [{"if_index": 7, "name": "GigabitEthernet0/0", "status": "up", "speed_mbps": 1000, "in_octets": 2_500_000_000, "out_octets": 1_250_000_000, "counter_width": 64}]},
        now,
    ))

    assert first["health_status"] == "unknown"
    assert second["health_status"] == "unknown"
    conn = get_db_connection()
    try:
        sample = dict(conn.execute(f"SELECT * FROM {_sample_table()} WHERE link_id = ? ORDER BY sampled_at DESC LIMIT 1", (link["id"],)).fetchone())
        status = dict(conn.execute("SELECT * FROM wan_link_current_status WHERE link_id = ?", (link["id"],)).fetchone())
        alert = dict(conn.execute("SELECT status, details FROM wan_alert_events WHERE id = ?", ("shared-util-event",)).fetchone())
    finally:
        conn.close()
    assert sample["download_bps"] == 200_000_000
    assert sample["upload_bps"] == 100_000_000
    assert sample["download_util_pct"] is None
    assert sample["upload_util_pct"] is None
    assert sample["quality_flags"]["measurement_scope_shared_interface"] is True
    assert status["download_bps"] == 200_000_000
    assert status["download_util_pct"] is None
    assert status["health_status"] == "unknown"
    assert alert["status"] == "resolved"


def test_error_and_discard_rates_use_actual_sample_interval(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import _collect_link

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
    finally:
        conn.close()
    base = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    item = {"if_index": 7, "name": "GigabitEthernet0/0", "status": "up", "speed_mbps": 1000, "in_octets": 1_000_000_000, "out_octets": 500_000_000, "counter_width": 64, "in_errors": 10, "out_errors": 20, "in_discards": 3, "out_discards": 4}
    _run_async(_collect_link(link, {"status": "success", "items": [item]}, base))
    next_item = {**item, "in_octets": 2_500_000_000, "out_octets": 1_250_000_000, "in_errors": 70, "out_errors": 80, "in_discards": 33, "out_discards": 44}
    _run_async(_collect_link(link, {"status": "success", "items": [next_item]}, base + timedelta(minutes=1)))
    conn = get_db_connection()
    try:
        row = dict(conn.execute(f"SELECT in_error_delta, out_error_delta, in_error_rate, out_error_rate, in_discard_rate, out_discard_rate FROM {_sample_table()} WHERE link_id = ? ORDER BY sampled_at DESC LIMIT 1", (link["id"],)).fetchone())
    finally:
        conn.close()
    assert row["in_error_delta"] == 60 and row["out_error_delta"] == 60
    assert float(row["in_error_rate"]) == 1.0 and float(row["out_error_rate"]) == 1.0
    assert float(row["in_discard_rate"]) == 0.5 and abs(float(row["out_discard_rate"]) - 2 / 3) < 1e-6


def test_p1_rollup_and_p2_binding_contract(isolated_db):
    from database import get_db_connection
    from services.wan_p1_service import rollup_wan_samples_once
    from services.wan_p2_service import list_probe_bindings, upsert_probe_binding

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        sample_table = _sample_table()
        target_id = "probe-target"
        conn.execute("INSERT INTO outbound_probe_targets (id, target_name, host, port, probe_type, is_active, enabled, group_name, url, expected_status_code, expected_keyword, timeout_ms, created_at, updated_at) VALUES (?, ?, ?, ?, ?, TRUE, TRUE, ?, ?, ?, ?, ?, ?, ?)", (target_id, "DNS target", "example.com", 53, "DNS", "business", "", 200, "", 2000, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        for offset in range(0, 10):
            sample_time = (now - timedelta(minutes=offset)).isoformat()
            conn.execute(f"INSERT INTO {sample_table} (id, link_id, sampled_at, download_bps, upload_bps, download_util_pct, upload_util_pct, collection_status, quality_flags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'success', '{{}}', ?)", (f"sample-{offset}", link["id"], sample_time, 100_000_000, 50_000_000, 50, 50, sample_time))
        conn.commit()
    finally:
        conn.close()

    rollup = rollup_wan_samples_once()
    assert rollup["five_min"]["buckets"] > 0

    binding = upsert_probe_binding({"link_id": "wan-link", "target_id": target_id, "purpose": "application", "route_mode": "default"}, {"username": "operator"})
    assert binding["link_id"] == "wan-link"
    assert binding["purpose"] == "application"
    assert [item["purpose"] for item in list_probe_bindings(link_id="wan-link", purpose="application")] == ["application"]


def test_alert_episode_can_recover_and_fire_again(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import _ensure_alert_rules, _evaluate_alerts

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        sample_table = _sample_table()
        base = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        _ensure_alert_rules(conn, link, base.isoformat())
        for offset in range(3):
            sampled = (base - timedelta(minutes=offset)).isoformat()
            conn.execute(f"INSERT INTO {sample_table} (id, link_id, sampled_at, collection_status, oper_status, download_util_pct, upload_util_pct, quality_flags, created_at) VALUES (?, ?, ?, 'success', 'down', 0, 0, '{{}}', ?)", (f"down-{offset}", link["id"], sampled, sampled))
        assert _evaluate_alerts(conn, link, base.isoformat()) == 1
        first_event = conn.execute("SELECT id, status FROM wan_alert_events WHERE link_id = ?", (link["id"],)).fetchone()
        assert first_event["status"] == "firing"
        for offset in range(2):
            sampled = (base + timedelta(minutes=offset + 1)).isoformat()
            conn.execute(f"INSERT INTO {sample_table} (id, link_id, sampled_at, collection_status, oper_status, download_util_pct, upload_util_pct, quality_flags, created_at) VALUES (?, ?, ?, 'success', 'up', 0, 0, '{{}}', ?)", (f"up-{offset}", link["id"], sampled, sampled))
        _evaluate_alerts(conn, link, (base + timedelta(minutes=3)).isoformat())
        assert conn.execute("SELECT status FROM wan_alert_events WHERE id = ?", (first_event["id"],)).fetchone()[0] == "resolved"
        for offset in range(3):
            sampled = (base + timedelta(minutes=5 + offset)).isoformat()
            conn.execute(f"INSERT INTO {sample_table} (id, link_id, sampled_at, collection_status, oper_status, download_util_pct, upload_util_pct, quality_flags, created_at) VALUES (?, ?, ?, 'success', 'down', 0, 0, '{{}}', ?)", (f"down-again-{offset}", link["id"], sampled, sampled))
        _evaluate_alerts(conn, link, (base + timedelta(minutes=8)).isoformat())
        assert conn.execute("SELECT COUNT(*) FROM wan_alert_events WHERE link_id = ?", (link["id"],)).fetchone()[0] == 2
    finally:
        conn.close()


def test_alert_event_filters_support_site_provider_and_time_range(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import list_wan_alert_events

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        conn.execute("UPDATE wan_links SET provider = ? WHERE id = ?", ("ISP-A", link["id"]))
        conn.execute("INSERT INTO wan_alert_events (id, event_key, link_id, metric, severity, status, title, message, started_at, last_seen_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("filter-event", "filter-key", link["id"], "interface_down", "critical", "resolved", "接口 Down", "test", "2026-08-23T10:00:00+00:00", "2026-08-23T10:05:00+00:00", "2026-08-23T10:00:00+00:00"))
        conn.commit()
    finally:
        conn.close()

    result = list_wan_alert_events(site_id="site-default", provider="ISP-A", start_at="2026-08-23T09:00:00+00:00", end_at="2026-08-23T11:00:00+00:00")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "filter-event"
    assert list_wan_alert_events(provider="ISP-B")["total"] == 0


def test_wan_summary_keeps_no_data_as_null_instead_of_zero(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import list_wan_links

    conn = get_db_connection()
    try:
        _seed_link(conn)
    finally:
        conn.close()
    summary = list_wan_links(page=1, page_size=1)["summary"]
    assert summary["download_bps"] is None
    assert summary["upload_bps"] is None
    assert summary["max_util_pct"] is None


def test_wan_link_list_supports_role_and_group_filters(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import list_wan_links
    from services.wan_p1_service import upsert_wan_link_group

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        conn.execute("UPDATE wan_links SET link_role = ? WHERE id = ?", ("backup", link["id"]))
        conn.commit()
    finally:
        conn.close()

    group = upsert_wan_link_group(
        {"group_name": "HQ backup", "mode": "primary_backup", "site_id": "site-default", "members": [{"link_id": link["id"], "role": "backup"}]},
        {"username": "operator"},
    )
    assert list_wan_links(link_role="backup")["total"] == 1
    assert list_wan_links(group_id=group["id"])["total"] == 1
    assert list_wan_links(link_role="primary")["total"] == 0


def test_wan_link_list_accepts_standalone_role_filter(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import list_wan_links

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        conn.execute("UPDATE wan_links SET link_role = ? WHERE id = ?", ("standalone", link["id"]))
        conn.commit()
    finally:
        conn.close()

    assert list_wan_links(link_role="standalone")["total"] == 1


def test_long_history_is_server_downsampled_with_contract_metadata(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import get_wan_link_history

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        sample_table = _sample_table()
        base = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(days=30)
        for offset in range(30 * 24 * 60):
            sampled = (base + timedelta(minutes=offset)).isoformat()
            conn.execute(f"INSERT INTO {sample_table} (id, link_id, sampled_at, collection_status, download_bps, upload_bps, quality_flags, created_at) VALUES (?, ?, ?, 'success', ?, ?, '{{}}', ?)", (f"history-{offset}", link["id"], sampled, 100_000_000, 50_000_000, sampled))
        conn.commit()
    finally:
        conn.close()
    history = get_wan_link_history("wan-link", 720)
    assert history is not None
    assert history["resolution"] == 7200
    assert len(history["history"]) <= 600
    assert history["start_time"] < history["end_time"]


def test_history_resolution_supports_minute_shortcuts():
    from services.wan_link_service import _history_resolution

    assert _history_resolution(5) == 60
    assert _history_resolution(60) == 60
    assert _history_resolution(360) == 300
    assert _history_resolution(1440) == 900
    assert _history_resolution(10080) == 3600
    assert _history_resolution(43200) == 7200


def test_24_hour_history_uses_five_minute_source_before_15_minute_downsample(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import get_wan_link_history

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        for offset in range(0, 12 * 24):
            bucket = (now - timedelta(minutes=5 * offset)).isoformat()
            conn.execute("INSERT INTO wan_link_samples_5m (link_id, bucket_start, sample_count, coverage_pct, avg_download_bps, avg_upload_bps, avg_download_util_pct, avg_upload_util_pct, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (link["id"], bucket, 5, 100, 100_000_000, 50_000_000, 50, 25, bucket))
        conn.commit()
    finally:
        conn.close()
    history = get_wan_link_history("wan-link", history_minutes=1440)
    assert history and history["resolution"] == 900
    assert len(history["history"]) >= 80


def test_contract_edit_recomputes_current_utilization(isolated_db):
    from database import get_db_connection
    from services.wan_link_service import upsert_wan_link

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        conn.execute(
            "INSERT INTO wan_link_current_status (link_id, sampled_at, download_bps, upload_bps, download_util_pct, upload_util_pct, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (link["id"], now, 2_500_000, 2_500_000, 2.5, 2.5, now),
        )
        conn.commit()
    finally:
        conn.close()

    upsert_wan_link(
        {
            "link_name": "HQ",
            "site_id": "",
            "site_name": "HQ",
            "device_id": link["device_id"],
            "interface_id": link["interface_id"],
            "link_role": "primary",
            "direction_mode": "normal",
            "contracted_download_mbps": 10,
            "contracted_upload_mbps": 10,
        },
        link["id"],
    )
    conn = get_db_connection()
    try:
        row = dict(conn.execute("SELECT download_util_pct, upload_util_pct FROM wan_link_current_status WHERE link_id = ?", (link["id"],)).fetchone())
    finally:
        conn.close()
    assert float(row["download_util_pct"]) == 25.0
    assert float(row["upload_util_pct"]) == 25.0


def test_report_generation_is_idempotent_and_export_is_auditable(isolated_db):
    from database import get_db_connection
    from services.wan_p1_service import generate_wan_report, list_wan_reports, mark_wan_report_exported

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        conn.execute("INSERT INTO wan_link_samples_1h (link_id, bucket_start, sample_count, coverage_pct, p95_download_util_pct, p95_upload_util_pct, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (link["id"], now.isoformat(), 60, 100, 90, 70, now.isoformat()))
        conn.commit()
    finally:
        conn.close()
    start, end = (now - timedelta(hours=1)).isoformat(), (now + timedelta(hours=1)).isoformat()
    first = generate_wan_report("daily", start, end, {"username": "operator"})
    second = generate_wan_report("daily", start, end, {"username": "operator"})
    assert first["report_id"] == second["report_id"]
    report_id = first["report_id"]
    assert list_wan_reports(limit=5)[0]["id"] == report_id
    exported = mark_wan_report_exported(report_id, {"username": "operator"})
    assert exported and exported["exported_by"] == "operator"


def test_probe_binding_requires_enabled_target_and_records_route_evidence(isolated_db):
    from database import get_db_connection
    from services.wan_p2_service import upsert_probe_binding

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO outbound_probe_targets (id, target_name, host, port, probe_type, is_active, enabled, group_name, url, expected_status_code, expected_keyword, timeout_ms, created_at, updated_at) VALUES (?, ?, ?, ?, ?, FALSE, TRUE, ?, ?, ?, ?, ?, ?, ?)", ("disabled-target", "Disabled", "example.com", 53, "DNS_RESOLVE", "business", "", 200, "", 2000, now, now))
        conn.commit()
    finally:
        conn.close()
    try:
        upsert_probe_binding({"link_id": link["id"], "target_id": "disabled-target", "purpose": "application"}, {"username": "operator"})
        assert False, "disabled targets must not be bindable"
    except ValueError as exc:
        assert "disabled" in str(exc).lower()

    conn = get_db_connection()
    try:
        conn.execute("UPDATE outbound_probe_targets SET is_active = TRUE WHERE id = ?", ("disabled-target",))
        conn.commit()
    finally:
        conn.close()
    binding = upsert_probe_binding({"link_id": link["id"], "target_id": "disabled-target", "purpose": "application", "route_mode": "source_ip", "source_ip": "192.0.2.10"}, {"username": "operator"})
    evidence = binding["route_evidence_json"]
    assert "source_ip_configured_unverified" in (
        evidence if isinstance(evidence, str) else str(evidence.get("evidence_status", ""))
    )


def test_daily_maintenance_window_crossing_midnight_is_active(isolated_db):
    from database import get_db_connection
    from services.wan_p1_service import is_wan_link_in_maintenance, upsert_wan_maintenance_window

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        # 00:02 in Asia/Shanghai: the daily occurrence started at 23:52
        # yesterday and must remain active for its final 20 minutes.
        now = datetime(2026, 10, 12, 16, 2, tzinfo=timezone.utc)
        start = now - timedelta(days=1, minutes=10)
        end = start + timedelta(minutes=30)
        upsert_wan_maintenance_window({"name": "daily window", "link_id": link["id"], "starts_at": start.isoformat(), "ends_at": end.isoformat(), "recurrence": "daily"}, {"username": "operator"})
        assert is_wan_link_in_maintenance(conn, link["id"], "site-default", now.isoformat()) is True
        assert is_wan_link_in_maintenance(conn, link["id"], "site-default", (now + timedelta(hours=1)).isoformat()) is False
    finally:
        conn.close()


def test_weekly_maintenance_window_crossing_recurrence_boundary_is_active(isolated_db):
    from database import get_db_connection
    from services.wan_p1_service import is_wan_link_in_maintenance, upsert_wan_maintenance_window

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        # 00:02 Wednesday in Asia/Shanghai, 10 minutes after the weekly
        # occurrence that began at 23:52 on the previous Wednesday.
        now = datetime(2026, 10, 13, 16, 2, tzinfo=timezone.utc)
        start = now - timedelta(days=6, minutes=10)
        end = start + timedelta(minutes=30)
        upsert_wan_maintenance_window({"name": "weekly window", "link_id": link["id"], "starts_at": start.isoformat(), "ends_at": end.isoformat(), "recurrence": "weekly"}, {"username": "operator"})
        assert is_wan_link_in_maintenance(conn, link["id"], "site-default", now.isoformat()) is True
        assert is_wan_link_in_maintenance(conn, link["id"], "site-default", (now + timedelta(hours=1)).isoformat()) is False
    finally:
        conn.close()


def test_monthly_maintenance_window_crossing_month_boundary_is_active(isolated_db):
    from database import get_db_connection
    from services.wan_p1_service import is_wan_link_in_maintenance, upsert_wan_maintenance_window

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        # 00:05 on November 1 in Asia/Shanghai, 10 minutes after the October
        # 31 monthly occurrence began.
        now = datetime(2026, 10, 31, 16, 5, tzinfo=timezone.utc)
        start = now - timedelta(minutes=10)
        end = start + timedelta(minutes=30)
        upsert_wan_maintenance_window({"name": "monthly window", "link_id": link["id"], "starts_at": start.isoformat(), "ends_at": end.isoformat(), "recurrence": "monthly"}, {"username": "operator"})
        assert is_wan_link_in_maintenance(conn, link["id"], "site-default", now.isoformat()) is True
        assert is_wan_link_in_maintenance(conn, link["id"], "site-default", (now + timedelta(hours=1)).isoformat()) is False
    finally:
        conn.close()


def test_correlation_event_resolves_on_next_healthy_recompute(isolated_db):
    from database import get_db_connection
    from services.wan_p2_service import get_wan_correlation_event, list_wan_correlation_events, recompute_wan_correlations

    conn = get_db_connection()
    try:
        link = _seed_link(conn)
        conn.execute("UPDATE wan_links SET provider = ? WHERE id = ?", ("ISP-A", link["id"]))
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
        conn.execute("INSERT INTO wan_link_current_status (link_id, sampled_at, collection_status, oper_status, health_status, updated_at) VALUES (?, ?, 'success', 'down', 'critical', ?)", (link["id"], now, now))
        conn.commit()
    finally:
        conn.close()

    recompute_wan_correlations()
    filtered = list_wan_correlation_events(site_id="site-default", provider="ISP-A", severity="critical", keyword="接口")
    assert filtered["total"] == 1 and filtered["items"][0]["link_name"] == "HQ"
    conn = get_db_connection()
    try:
        event_row = conn.execute("SELECT id, status FROM wan_correlation_events WHERE root_cause_code = 'egress_interface_fault'").fetchone()
        assert event_row and event_row[1] == "open"
        conn.execute("UPDATE wan_link_current_status SET oper_status = 'up', health_status = 'healthy', sampled_at = ?, updated_at = ? WHERE link_id = ?", (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), link["id"]))
        conn.commit()
        event_id = event_row[0]
    finally:
        conn.close()

    recompute_wan_correlations()
    event = get_wan_correlation_event(event_id)
    assert event and event["status"] == "resolved"
