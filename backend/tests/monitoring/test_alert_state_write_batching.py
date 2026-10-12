from __future__ import annotations

import asyncio
import threading

from database import get_db_connection
from services import background_monitor_service as monitor
from services import monitoring_notification_outbox_service as outbox


def _insert_device(device_id: str) -> None:
    connection = get_db_connection()
    try:
        connection.execute(
            "INSERT INTO devices (id, hostname, ip_address, tenant_id) VALUES (?, ?, ?, ?)",
            (device_id, f"host-{device_id}", "192.0.2.41", "tenant-default"),
        )
        connection.commit()
    finally:
        connection.close()


def _clear_process_state(dedupe_key: str) -> None:
    monitor.open_alerts.pop(dedupe_key, None)
    monitor.alert_transition_states.pop(dedupe_key, None)
    monitor.webhook_last_sent.pop(dedupe_key, None)
    monitor.protocol_transition_history.pop(dedupe_key, None)
    monitor.protocol_notify_suppressed_until.pop(dedupe_key, None)


class _RecordingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.commit_count = 0
        self.rollback_count = 0
        self.executemany_calls: list[tuple[str, int]] = []

    def execute(self, sql, params=()):
        return self.connection.execute(sql, params)

    def executemany(self, sql, rows):
        materialized_rows = list(rows)
        self.executemany_calls.append((sql, len(materialized_rows)))
        return self.connection.executemany(sql, materialized_rows)

    def commit(self):
        self.commit_count += 1
        self.connection.commit()

    def rollback(self):
        self.rollback_count += 1
        self.connection.rollback()

    def close(self):
        self.connection.close()


def _active_alert_update(dedupe_key: str, device_id: str, rule_id: str) -> dict:
    return {
        "args": (
            dedupe_key,
            True,
            "critical",
            "Batched alert",
            "A monitored threshold was breached",
            device_id,
        ),
        "kwargs": {
            "status": "active",
            "rule": {"id": rule_id, "for_duration_seconds": 0, "notification_channels": ["workspace"]},
        },
    }


def test_async_alert_state_write_runs_in_worker_thread_and_persists_atomically(isolated_db, monkeypatch):
    device_id = "off-loop-alert-device"
    dedupe_key = "off-loop-alert-state"
    _insert_device(device_id)
    _clear_process_state(dedupe_key)
    monkeypatch.setattr(monitor.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "find_active_silence_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor.settings, "ALERT_NOTIFY_WEBHOOK_URL", "")

    event_loop_thread = threading.get_ident()
    connection_threads: list[int] = []
    original_get_db_connection = monitor.get_db_connection

    def tracked_get_db_connection():
        connection_threads.append(threading.get_ident())
        return original_get_db_connection()

    monkeypatch.setattr(monitor, "get_db_connection", tracked_get_db_connection)

    try:
        asyncio.run(monitor._set_alert_state_off_loop(
            dedupe_key,
            True,
            "critical",
            "Off-loop alert",
            "CPU utilization is high",
            device_id,
            rule={"id": "off-loop-alert-rule", "for_duration_seconds": 0, "notification_channels": ["workspace"]},
        ))

        assert connection_threads
        assert all(thread_id != event_loop_thread for thread_id in connection_threads)

        connection = get_db_connection()
        try:
            event = connection.execute(
                "SELECT id, resolved_at FROM alert_events WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            assert event is not None and event["resolved_at"] is None
            assert connection.execute(
                "SELECT 1 FROM alert_activity WHERE alert_id = ? AND event_type = 'OPENED'",
                (event["id"],),
            ).fetchone() is not None
            assert connection.execute(
                "SELECT 1 FROM alert_rule_states WHERE rule_id = ?",
                ("off-loop-alert-rule",),
            ).fetchone() is not None
            assert connection.execute(
                "SELECT 1 FROM alert_delivery_outbox WHERE delivery_key LIKE ? AND status = 'pending'",
                (f"{dedupe_key}:workspace:active:%",),
            ).fetchone() is not None
        finally:
            connection.close()
    finally:
        _clear_process_state(dedupe_key)


def test_alert_state_batch_bounds_transactions_and_batches_state_upserts(isolated_db, monkeypatch):
    batch_count = monitor._ALERT_STATE_BATCH_SIZE + 1
    device_ids = [f"batch-alert-device-{index}" for index in range(batch_count)]
    dedupe_keys = [f"batch-alert-{index}" for index in range(batch_count)]
    rule_ids = [f"batch-rule-{index}" for index in range(batch_count)]
    connection = get_db_connection()
    try:
        connection.executemany(
            "INSERT INTO devices (id, hostname, ip_address, tenant_id) VALUES (?, ?, ?, ?)",
            [
                (device_id, f"host-{device_id}", "192.0.2.41", "tenant-default")
                for device_id in device_ids
            ],
        )
        connection.commit()
    finally:
        connection.close()
    for dedupe_key in dedupe_keys:
        _clear_process_state(dedupe_key)
    monkeypatch.setattr(monitor.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "find_active_silence_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor.settings, "ALERT_NOTIFY_WEBHOOK_URL", "")

    recording_connections: list[_RecordingConnection] = []
    original_get_db_connection = monitor.get_db_connection

    def tracked_get_db_connection():
        connection = _RecordingConnection(original_get_db_connection())
        recording_connections.append(connection)
        return connection

    monkeypatch.setattr(monitor, "get_db_connection", tracked_get_db_connection)
    try:
        monitor._set_alert_states_batched([
            _active_alert_update(dedupe_keys[index], device_ids[index], rule_ids[index])
            for index in range(batch_count)
        ])

        assert len(recording_connections) == 2
        assert [recording_connection.commit_count for recording_connection in recording_connections] == [1, 1]
        state_calls = [call for recording_connection in recording_connections for call in recording_connection.executemany_calls]
        assert len(state_calls) == 2
        assert all("INSERT INTO alert_rule_states" in sql for sql, _row_count in state_calls)
        assert sorted(row_count for _sql, row_count in state_calls) == [1, monitor._ALERT_STATE_BATCH_SIZE]

        connection = get_db_connection()
        try:
            dedupe_placeholders = ", ".join("?" for _ in dedupe_keys)
            rule_placeholders = ", ".join("?" for _ in rule_ids)
            events = connection.execute(
                f"SELECT id, dedupe_key FROM alert_events WHERE dedupe_key IN ({dedupe_placeholders})",
                dedupe_keys,
            ).fetchall()
            assert {event["dedupe_key"] for event in events} == set(dedupe_keys)
            alert_ids = [event["id"] for event in events]
            alert_placeholders = ", ".join("?" for _ in alert_ids)
            assert connection.execute(
                f"SELECT COUNT(*) AS count FROM alert_activity WHERE alert_id IN ({alert_placeholders}) AND event_type = 'OPENED'",
                alert_ids,
            ).fetchone()["count"] == batch_count
            assert connection.execute(
                f"SELECT COUNT(*) AS count FROM alert_delivery_outbox WHERE alert_id IN ({alert_placeholders})",
                alert_ids,
            ).fetchone()["count"] == batch_count
            assert connection.execute(
                f"SELECT COUNT(*) AS count FROM alert_rule_states WHERE rule_id IN ({rule_placeholders})",
                rule_ids,
            ).fetchone()["count"] == batch_count
        finally:
            connection.close()
    finally:
        for dedupe_key in dedupe_keys:
            _clear_process_state(dedupe_key)


def test_alert_state_batch_rolls_back_events_outbox_and_hysteresis_together(isolated_db, monkeypatch):
    device_ids = ["rollback-batch-device-1", "rollback-batch-device-2"]
    dedupe_keys = ["rollback-batch-one", "rollback-batch-two"]
    rule_ids = ["rollback-batch-rule-one", "rollback-batch-rule-two"]
    for device_id in device_ids:
        _insert_device(device_id)
    for dedupe_key in dedupe_keys:
        _clear_process_state(dedupe_key)
    monkeypatch.setattr(monitor.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "find_active_silence_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor.settings, "ALERT_NOTIFY_WEBHOOK_URL", "")

    enqueue_count = 0
    original_enqueue = outbox.enqueue_alert_delivery

    def fail_second_enqueue(**kwargs):
        nonlocal enqueue_count
        enqueue_count += 1
        if enqueue_count == 2:
            raise RuntimeError("controlled batch enqueue failure")
        return original_enqueue(**kwargs)

    monkeypatch.setattr(outbox, "enqueue_alert_delivery", fail_second_enqueue)
    try:
        try:
            monitor._set_alert_states_batched([
                _active_alert_update(dedupe_keys[index], device_ids[index], rule_ids[index])
                for index in range(2)
            ])
        except RuntimeError as exc:
            assert str(exc) == "controlled batch enqueue failure"
        else:
            raise AssertionError("the second enqueue failure should abort the whole bounded batch")

        connection = get_db_connection()
        try:
            for dedupe_key, rule_id in zip(dedupe_keys, rule_ids):
                assert connection.execute(
                    "SELECT 1 FROM alert_events WHERE dedupe_key = ?",
                    (dedupe_key,),
                ).fetchone() is None
                assert connection.execute(
                    "SELECT 1 FROM alert_delivery_outbox WHERE delivery_key LIKE ?",
                    (f"{dedupe_key}:%",),
                ).fetchone() is None
                assert connection.execute(
                    "SELECT 1 FROM alert_rule_states WHERE rule_id = ?",
                    (rule_id,),
                ).fetchone() is None
                assert dedupe_key not in monitor.open_alerts
                assert dedupe_key not in monitor.alert_transition_states
        finally:
            connection.close()
    finally:
        monkeypatch.setattr(outbox, "enqueue_alert_delivery", original_enqueue)
        for dedupe_key in dedupe_keys:
            _clear_process_state(dedupe_key)
