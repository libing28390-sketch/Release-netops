from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import uuid

from api import monitoring
from database import fetch_interface_data, fetch_interface_data_for_devices, get_db_connection
from services.device_health_service import load_devices_for_health


class _CountingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.execute_count = 0

    def execute(self, *args, **kwargs):
        self.execute_count += 1
        return self.connection.execute(*args, **kwargs)

    def rollback(self):
        return self.connection.rollback()


def test_batched_interface_reader_matches_per_device_reader(isolated_db):
    device_ids = [f"batch-device-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    earlier = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    latest = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    conn = get_db_connection()
    try:
        for index, device_id in enumerate(device_ids, start=1):
            conn.execute(
                "INSERT INTO devices (id, hostname, ip_address, platform, status) VALUES (?, ?, ?, ?, ?)",
                (device_id, f"batch-{index}", f"192.0.2.{index}", "h3c_comware", "online"),
            )
            conn.execute(
                "INSERT INTO interfaces (id, device_id, interface_name, oper_status, speed) VALUES (?, ?, ?, ?, ?)",
                (f"interface-{device_id}", device_id, f"GigabitEthernet0/{index}", "down", 1_000_000_000),
            )
        conn.executemany(
            """
            INSERT INTO interface_telemetry_raw
                (ts, device_id, interface_name, status, speed_mbps, in_bps, out_bps,
                 bw_in_pct, bw_out_pct, in_pkts, out_pkts, in_errors, out_errors,
                 in_discards, out_discards, packet_counter_source, fcs_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (earlier, device_ids[0], "GigabitEthernet0/1", "up", 1000, 10, 20, 1, 2, 1, 2, 0, 0, 0, 0, "ifHC", "native"),
                (latest, device_ids[0], "GigabitEthernet0/1", "up", 1000, 30, 40, 3, 4, 3, 4, 5, 6, 7, 8, "ifHC", "native"),
                (latest, device_ids[1], "GigabitEthernet0/2", "down", 1000, 50, 60, 5, 6, 5, 6, 1, 2, 3, 4, "ifHC", "native"),
            ],
        )
        conn.commit()

        expected = {device_id: fetch_interface_data(conn, device_id) for device_id in device_ids}
        counted = _CountingConnection(conn)
        actual = fetch_interface_data_for_devices(counted, device_ids)

        assert actual == expected
        assert counted.execute_count == 1
        assert fetch_interface_data_for_devices(counted, []) == {}
        assert counted.execute_count == 1
        assert fetch_interface_data_for_devices(counted, device_ids, chunk_size=1) == expected
        assert counted.execute_count == 3
    finally:
        conn.close()


def test_device_health_snapshot_batches_interface_reads(isolated_db):
    device_ids = [f"health-batch-device-{uuid.uuid4().hex[:8]}" for _ in range(12)]
    conn = get_db_connection()
    try:
        conn.executemany(
            "INSERT INTO devices (id, hostname, ip_address, platform, status) VALUES (?, ?, ?, ?, ?)",
            [
                (device_id, f"health-batch-{index}", f"192.0.2.{index}", "h3c_comware", "online")
                for index, device_id in enumerate(device_ids, start=1)
            ],
        )
        conn.executemany(
            "INSERT INTO interfaces (id, device_id, interface_name, oper_status, speed) VALUES (?, ?, ?, ?, ?)",
            [
                (f"health-interface-{index}", device_id, f"GigabitEthernet0/{index}", "up", 1_000_000_000)
                for index, device_id in enumerate(device_ids, start=1)
            ],
        )
        conn.commit()

        expected = {device_id: fetch_interface_data(conn, device_id) for device_id in device_ids}
        counted = _CountingConnection(conn)
        actual = load_devices_for_health(counted)

        assert len(actual) == len(device_ids)
        assert {item["id"]: item["interface_data"] for item in actual} == expected
        assert counted.execute_count == 2
    finally:
        conn.close()


def test_forced_overview_refresh_is_single_flight_per_tenant(isolated_db, monkeypatch):
    tenant_id = f"overview-single-flight-{uuid.uuid4().hex[:8]}"
    device_ids = [f"single-flight-device-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    cache_key = ("tenant", tenant_id)
    user = {"username": "viewer", "role": "Viewer", "tenant_id": tenant_id}
    entered_summary = threading.Event()
    release_summary = threading.Event()
    waiter_joined = threading.Event()
    counter_lock = threading.Lock()
    summary_calls = 0
    batch_calls = 0

    conn = get_db_connection()
    try:
        conn.execute("INSERT INTO tenants (id, name) VALUES (?, ?)", (tenant_id, tenant_id))
        conn.executemany(
            "INSERT INTO devices (id, hostname, ip_address, platform, status, tenant_id) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (device_ids[0], "single-flight-online", "192.0.2.10", "h3c_comware", "online", tenant_id),
                (device_ids[1], "single-flight-offline", "192.0.2.11", "h3c_comware", "offline", tenant_id),
            ],
        )
        conn.executemany(
            "INSERT INTO interfaces (id, device_id, interface_name, oper_status, speed) VALUES (?, ?, ?, ?, ?)",
            [
                (f"interface-{device_ids[0]}", device_ids[0], "GigabitEthernet0/1", "up", 1_000_000_000),
                (f"interface-{device_ids[1]}", device_ids[1], "GigabitEthernet0/2", "down", 1_000_000_000),
            ],
        )
        conn.execute(
            """
            INSERT INTO interface_telemetry_raw
                (ts, device_id, interface_name, status, speed_mbps, in_bps, out_bps,
                 bw_in_pct, bw_out_pct, in_pkts, out_pkts, in_errors, out_errors,
                 in_discards, out_discards)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                device_ids[0],
                "GigabitEthernet0/1",
                "up",
                1000,
                10,
                20,
                90,
                10,
                1,
                2,
                0,
                0,
                0,
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    original_batch_reader = monitoring.fetch_interface_data_for_devices

    def count_batch_reader(connection, device_ids):
        nonlocal batch_calls
        with counter_lock:
            batch_calls += 1
        return original_batch_reader(connection, device_ids)

    def slow_collection_summary(*, tenant_id):
        nonlocal summary_calls
        with counter_lock:
            summary_calls += 1
        entered_summary.set()
        if not release_summary.wait(timeout=5):
            raise TimeoutError("single-flight overview gate was not released")
        return {"by_status": {}, "by_collector": {}, "queues": {}, "sweeps": {}}

    monkeypatch.setattr(monitoring, "collection_status_summary", slow_collection_summary)
    monkeypatch.setattr(monitoring, "fetch_interface_data_for_devices", count_batch_reader)
    with monitoring._overview_cache_lock:
        monitoring._overview_cache.pop(cache_key, None)
        monitoring._overview_inflight.pop(cache_key, None)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(monitoring.monitoring_overview, True, user)
            assert entered_summary.wait(timeout=5)
            with monitoring._overview_cache_lock:
                refresh_event = monitoring._overview_inflight[cache_key]
            original_wait = refresh_event.wait

            def observed_wait(*args, **kwargs):
                waiter_joined.set()
                return original_wait(*args, **kwargs)

            refresh_event.wait = observed_wait
            second = executor.submit(monitoring.monitoring_overview, True, user)
            assert waiter_joined.wait(timeout=5)
            release_summary.set()
            first_payload = first.result(timeout=10)
            second_payload = second.result(timeout=10)

        assert first_payload["total_devices"] == 2
        assert second_payload["total_devices"] == 2
        assert first_payload["interfaces_up"] == 1
        assert first_payload["high_util_interfaces"] == 1
        assert first_payload["device_health_summary"]["total_devices"] == 2
        assert first_payload["top_hot_interfaces"][0]["device_id"] == device_ids[0]
        assert summary_calls == 1
        assert batch_calls == 1
    finally:
        release_summary.set()
        with monitoring._overview_cache_lock:
            monitoring._overview_cache.pop(cache_key, None)
            monitoring._overview_inflight.pop(cache_key, None)
