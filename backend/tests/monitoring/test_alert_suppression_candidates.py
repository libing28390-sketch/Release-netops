from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from database import get_db_connection
from services import alert_control_service as alert_control
from services import alert_maintenance_service as maintenance


class _RecordingConnection:
    def __init__(self, connection):
        self.connection = connection
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def execute(self, sql, params=()):
        self.execute_calls.append((sql, tuple(params or ())))
        return self.connection.execute(sql, params)

    def commit(self):
        self.commit_count += 1
        self.connection.commit()

    def rollback(self):
        self.rollback_count += 1
        self.connection.rollback()

    def close(self):
        self.close_count += 1
        self.connection.close()


def _insert_maintenance_window(
    connection,
    *,
    window_id: str,
    selection_mode: str,
    starts_at: str,
    ends_at: str,
    status: str = "active",
    target_ips: list[str] | None = None,
    condition_logic: str = "all",
    match_conditions: list[dict[str, str]] | None = None,
) -> None:
    normalized_target_ips = target_ips or []
    connection.execute(
        """
        INSERT INTO alert_maintenance_windows (
            id, name, target_ip, target_ips_json, selection_mode, condition_logic,
            match_conditions_json, title_pattern, message_pattern, starts_at, ends_at,
            notify_user_ids, reason, status, created_by, created_at, updated_at, last_match_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, '[]', '', ?, 'test', ?, ?, 0)
        """,
        (
            window_id,
            f"Window {window_id}",
            normalized_target_ips[0] if normalized_target_ips else "",
            json.dumps(normalized_target_ips),
            selection_mode,
            condition_logic,
            json.dumps(match_conditions or []),
            starts_at,
            ends_at,
            status,
            starts_at,
            starts_at,
        ),
    )


def _insert_silence(
    connection,
    *,
    silence_id: str,
    tenant_id: str,
    scope: dict,
    starts_at: str,
    ends_at: str,
    status: str = "active",
) -> None:
    connection.execute(
        """
        INSERT INTO alert_silences (
            id, tenant_id, scope_json, reason, starts_at, ends_at, created_by, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'test', ?, ?)
        """,
        (silence_id, tenant_id, json.dumps(scope), silence_id, starts_at, ends_at, status, starts_at),
    )


def test_maintenance_candidate_snapshot_matches_single_finder_and_reads_once(isolated_db) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    active_start = (now - timedelta(hours=3)).isoformat()
    active_end = (now + timedelta(hours=3)).isoformat()
    future_start = (now + timedelta(hours=1)).isoformat()
    future_end = (now + timedelta(hours=2)).isoformat()
    expired_start = (now - timedelta(hours=5)).isoformat()
    expired_end = (now - timedelta(hours=4)).isoformat()

    connection = get_db_connection()
    try:
        _insert_maintenance_window(
            connection,
            window_id="candidate-resource-active",
            selection_mode="resources",
            target_ips=["192.0.2.10", "192.0.2.11"],
            starts_at=active_start,
            ends_at=active_end,
        )
        _insert_maintenance_window(
            connection,
            window_id="candidate-condition-active",
            selection_mode="conditions",
            condition_logic="all",
            match_conditions=[
                {"field": "alert_level", "operator": "equals", "value": "critical"},
                {"field": "alert_description", "operator": "contains", "value": "interface"},
            ],
            starts_at=active_start,
            ends_at=active_end,
        )
        _insert_maintenance_window(
            connection,
            window_id="candidate-resource-future",
            selection_mode="resources",
            target_ips=["192.0.2.12"],
            starts_at=future_start,
            ends_at=future_end,
        )
        _insert_maintenance_window(
            connection,
            window_id="candidate-condition-expired",
            selection_mode="conditions",
            condition_logic="any",
            match_conditions=[{"field": "alert_description", "operator": "contains", "value": "disk"}],
            starts_at=expired_start,
            ends_at=expired_end,
        )
        _insert_maintenance_window(
            connection,
            window_id="candidate-resource-cancelled",
            selection_mode="resources",
            target_ips=["192.0.2.13"],
            starts_at=active_start,
            ends_at=active_end,
            status="cancelled",
        )
        connection.commit()

        alerts = [
            {"ip_address": "192.0.2.11", "title": "Link state", "severity": "warning"},
            {"ip_address": "198.51.100.7", "title": "Interface down", "message": "Port state changed", "severity": "critical"},
            {"ip_address": "192.0.2.12", "title": "Future maintenance", "severity": "warning"},
            {"ip_address": "198.51.100.8", "title": "Disk threshold", "severity": "critical"},
            {"ip_address": "192.0.2.13", "title": "Cancelled maintenance", "severity": "warning"},
        ]
        expected = [maintenance.find_active_window_for_alert(alert, conn=connection) for alert in alerts]

        recording_connection = _RecordingConnection(connection)
        candidates = maintenance.load_maintenance_window_candidates(recording_connection)
        assert len(recording_connection.execute_calls) == 1
        assert "status != 'cancelled'" in recording_connection.execute_calls[0][0]
        actual = [
            maintenance.find_active_window_for_alert(
                alert,
                conn=recording_connection,
                candidate_windows=candidates,
            )
            for alert in alerts
        ]

        assert [item["id"] if item else None for item in actual] == [
            item["id"] if item else None for item in expected
        ]
        assert [item["id"] if item else None for item in expected] == [
            "candidate-resource-active",
            "candidate-condition-active",
            None,
            None,
            None,
        ]
        assert [item["runtime_status"] if item else None for item in actual] == [
            item["runtime_status"] if item else None for item in expected
        ]
        assert len(recording_connection.execute_calls) == 1
        assert recording_connection.commit_count == 0
        assert recording_connection.rollback_count == 0
        assert recording_connection.close_count == 0
    finally:
        connection.close()


def test_silence_candidate_snapshot_matches_single_finder_and_reads_once(isolated_db) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    active_start = (now - timedelta(hours=3)).isoformat()
    active_end = (now + timedelta(hours=3)).isoformat()
    future_start = (now + timedelta(hours=1)).isoformat()
    future_end = (now + timedelta(hours=2)).isoformat()
    expired_start = (now - timedelta(hours=5)).isoformat()
    expired_end = (now - timedelta(hours=4)).isoformat()

    connection = get_db_connection()
    try:
        _insert_silence(
            connection,
            silence_id="candidate-silence-device-a",
            tenant_id="tenant-a",
            scope={"device_ids": ["device-a"]},
            starts_at=active_start,
            ends_at=active_end,
        )
        _insert_silence(
            connection,
            silence_id="candidate-silence-site-default",
            tenant_id="tenant-default",
            scope={"site_ids": ["site-west"]},
            starts_at=active_start,
            ends_at=active_end,
        )
        _insert_silence(
            connection,
            silence_id="candidate-silence-type-b",
            tenant_id="tenant-b",
            scope={"types": ["interface_down"]},
            starts_at=active_start,
            ends_at=active_end,
        )
        _insert_silence(
            connection,
            silence_id="candidate-silence-device-expired",
            tenant_id="tenant-default",
            scope={"device_ids": ["device-expired"]},
            starts_at=expired_start,
            ends_at=expired_end,
        )
        _insert_silence(
            connection,
            silence_id="candidate-silence-type-future",
            tenant_id="tenant-default",
            scope={"alert_types": ["future_alert"]},
            starts_at=future_start,
            ends_at=future_end,
        )
        _insert_silence(
            connection,
            silence_id="candidate-silence-expired-status",
            tenant_id="tenant-default",
            scope={"device_ids": ["device-status-expired"]},
            starts_at=active_start,
            ends_at=active_end,
            status="expired",
        )
        connection.commit()

        alerts = [
            {"tenant_id": "tenant-a", "device_id": "device-a", "site_id": "site-east", "type": "cpu_high"},
            {"tenant_id": "tenant-b", "device_id": "device-a", "site_id": "site-east", "type": "cpu_high"},
            {"tenant_id": "tenant-c", "device_id": "device-c", "site": "site-west", "type": "cpu_high"},
            {"tenant_id": "tenant-b", "device_id": "device-b", "type": "interface_down"},
            {"tenant_id": "tenant-c", "device_id": "device-expired", "type": "cpu_high"},
            {"tenant_id": "tenant-c", "device_id": "device-future", "type": "future_alert"},
            {"tenant_id": "tenant-c", "device_id": "device-status-expired", "type": "cpu_high"},
        ]
        expected = [
            alert_control.find_active_silence_for_alert(alert, now=now, connection=connection)
            for alert in alerts
        ]

        recording_connection = _RecordingConnection(connection)
        candidates = alert_control.load_active_silence_candidates(recording_connection)
        assert len(recording_connection.execute_calls) == 1
        assert "status = 'active'" in recording_connection.execute_calls[0][0]
        actual = [
            alert_control.find_active_silence_for_alert(
                alert,
                now=now,
                connection=recording_connection,
                candidates=candidates,
            )
            for alert in alerts
        ]

        assert actual == expected
        assert [item["id"] if item else None for item in actual] == [
            "candidate-silence-device-a",
            None,
            "candidate-silence-site-default",
            "candidate-silence-type-b",
            None,
            None,
            None,
        ]
        assert len(recording_connection.execute_calls) == 1
        assert recording_connection.commit_count == 0
        assert recording_connection.rollback_count == 0
        assert recording_connection.close_count == 0
    finally:
        connection.close()


def test_silence_candidate_loading_and_matching_fail_open(isolated_db, monkeypatch) -> None:
    class _BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("storage unavailable")

    assert alert_control.load_active_silence_candidates(_BrokenConnection()) == []

    monkeypatch.setattr(
        alert_control,
        "silence_matches",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("matcher unavailable")),
    )
    candidate = {
        "id": "broken-matcher",
        "tenant_id": "tenant-default",
        "scope": {},
        "reason": "test",
        "starts_at": "2020-01-01T00:00:00+00:00",
        "ends_at": "2030-01-01T00:00:00+00:00",
        "created_by": "test",
    }
    assert alert_control.find_active_silence_for_alert(
        {"tenant_id": "tenant-a"},
        candidates=[candidate],
    ) is None
