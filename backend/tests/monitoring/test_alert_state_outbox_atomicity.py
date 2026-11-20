from __future__ import annotations

from database import get_db_connection
from services import background_monitor_service as monitor
from services import monitoring_notification_outbox_service as outbox


def _insert_device(device_id: str) -> None:
    connection = get_db_connection()
    try:
        connection.execute(
            "INSERT INTO devices (id, hostname, ip_address, tenant_id) VALUES (?, ?, ?, ?)",
            (device_id, f"host-{device_id}", "192.0.2.40", "tenant-default"),
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


def test_alert_event_activity_state_and_delivery_intent_commit_together(isolated_db, monkeypatch) -> None:
    device_id = "atomic-alert-device"
    dedupe_key = "atomic-alert-open"
    _insert_device(device_id)
    _clear_process_state(dedupe_key)
    monkeypatch.setattr(monitor.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "find_active_silence_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor.settings, "ALERT_NOTIFY_WEBHOOK_URL", "")

    try:
        monitor.set_alert_state(
            dedupe_key,
            True,
            "critical",
            "Atomic alert",
            "CPU utilization is high",
            device_id,
            rule={"id": "atomic-alert-rule", "for_duration_seconds": 0, "notification_channels": ["workspace"]},
        )

        connection = get_db_connection()
        try:
            event = connection.execute(
                "SELECT id, resolved_at FROM alert_events WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            assert event is not None
            assert event["resolved_at"] is None
            activity = connection.execute(
                "SELECT event_type FROM alert_activity WHERE alert_id = ? AND event_type = 'OPENED'",
                (event["id"],),
            ).fetchone()
            assert activity is not None and activity["event_type"] == "OPENED"
            delivery = connection.execute(
                "SELECT channel, status FROM alert_delivery_outbox WHERE delivery_key LIKE ?",
                (f"{dedupe_key}:workspace:active:%",),
            ).fetchone()
            assert delivery is not None
            assert delivery["channel"] == "workspace"
            assert delivery["status"] == "pending"
            assert connection.execute(
                "SELECT 1 FROM alert_rule_states WHERE rule_id = ?",
                ("atomic-alert-rule",),
            ).fetchone() is not None
        finally:
            connection.close()
    finally:
        _clear_process_state(dedupe_key)


def test_enqueue_failure_rolls_back_alert_lifecycle_and_keeps_process_projection_unadvanced(
    isolated_db, monkeypatch
) -> None:
    device_id = "atomic-rollback-device"
    dedupe_key = "atomic-alert-rollback"
    _insert_device(device_id)
    _clear_process_state(dedupe_key)
    monkeypatch.setattr(monitor.alert_maintenance_service, "find_active_window_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "find_active_silence_for_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor.settings, "ALERT_NOTIFY_WEBHOOK_URL", "")

    def fail_enqueue(**_kwargs):
        raise RuntimeError("test enqueue failure")

    monkeypatch.setattr(outbox, "enqueue_alert_delivery", fail_enqueue)
    try:
        try:
            monitor.set_alert_state(
                dedupe_key,
                True,
                "critical",
                "Atomic rollback alert",
                "CPU utilization is high",
                device_id,
                rule={"id": "atomic-rollback-rule", "for_duration_seconds": 0, "notification_channels": ["workspace"]},
            )
        except RuntimeError as exc:
            assert str(exc) == "test enqueue failure"
        else:
            raise AssertionError("enqueue failure should abort the alert transaction")

        connection = get_db_connection()
        try:
            assert connection.execute(
                "SELECT 1 FROM alert_events WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone() is None
            assert connection.execute(
                "SELECT 1 FROM alert_activity WHERE event_type = 'OPENED' AND metadata_json LIKE ?",
                (f"%{dedupe_key}%",),
            ).fetchone() is None
            assert connection.execute(
                "SELECT 1 FROM alert_delivery_outbox WHERE delivery_key LIKE ?",
                (f"{dedupe_key}:%",),
            ).fetchone() is None
            assert connection.execute(
                "SELECT 1 FROM alert_rule_states WHERE rule_id = ?",
                ("atomic-rollback-rule",),
            ).fetchone() is None
        finally:
            connection.close()
        assert dedupe_key not in monitor.open_alerts
        assert dedupe_key not in monitor.alert_transition_states
        assert dedupe_key not in monitor.webhook_last_sent
    finally:
        _clear_process_state(dedupe_key)
