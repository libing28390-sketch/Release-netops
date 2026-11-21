from __future__ import annotations

import asyncio

from database import get_db_connection
from services import background_monitor_service as monitor


class _RecordingConnection:
    def __init__(self, connection, *, fail_inserts: bool = False):
        self.connection = connection
        self.fail_inserts = fail_inserts
        self.commit_count = 0
        self.rollback_count = 0

    def execute(self, sql, params=()):
        return self.connection.execute(sql, params)

    def executemany(self, sql, rows):
        if self.fail_inserts and "INSERT INTO protocol_peer_state" in sql:
            raise RuntimeError("controlled peer snapshot insert failure")
        return self.connection.executemany(sql, rows)

    def commit(self):
        self.commit_count += 1
        self.connection.commit()

    def rollback(self):
        self.rollback_count += 1
        self.connection.rollback()

    def close(self):
        self.connection.close()


def _seed_peer_state(device_id: str, peers: dict[str, str]) -> None:
    connection = get_db_connection()
    try:
        connection.executemany(
            """
            INSERT INTO protocol_peer_state (metric_type, device_id, peer, object_name, updated_at)
            VALUES (?, ?, ?, ?, '2026-10-12T00:00:00+00:00')
            """,
            [
                ("bgp_neighbor_down", device_id, peer, object_name)
                for peer, object_name in peers.items()
            ],
        )
        connection.commit()
    finally:
        connection.close()


def _read_peer_state(device_id: str) -> dict[str, str]:
    connection = get_db_connection()
    try:
        rows = connection.execute(
            """
            SELECT peer, object_name
            FROM protocol_peer_state
            WHERE metric_type = 'bgp_neighbor_down' AND device_id = ?
            """,
            (device_id,),
        ).fetchall()
        return {str(row["peer"]): str(row["object_name"] or "") for row in rows}
    finally:
        connection.close()


def test_peer_snapshot_replacement_uses_one_commit(isolated_db, monkeypatch):
    device_id = "peer-snapshot-atomic-device"
    _seed_peer_state(device_id, {"old-peer": "old-object"})
    recording_connections: list[_RecordingConnection] = []
    original_get_connection = monitor.get_db_connection

    def tracked_get_connection():
        connection = _RecordingConnection(original_get_connection())
        recording_connections.append(connection)
        return connection

    monkeypatch.setattr(monitor, "get_db_connection", tracked_get_connection)

    monitor.persist_protocol_peer_state(
        "bgp_neighbor_down",
        device_id,
        {"new-peer-1": "new-object-1", "new-peer-2": "new-object-2"},
    )

    assert len(recording_connections) == 1
    assert recording_connections[0].commit_count == 1
    assert recording_connections[0].rollback_count == 0
    assert _read_peer_state(device_id) == {
        "new-peer-1": "new-object-1",
        "new-peer-2": "new-object-2",
    }


def test_peer_snapshot_insert_failure_keeps_previous_snapshot(isolated_db, monkeypatch):
    device_id = "peer-snapshot-rollback-device"
    previous = {"old-peer": "old-object"}
    _seed_peer_state(device_id, previous)
    recording_connections: list[_RecordingConnection] = []
    original_get_connection = monitor.get_db_connection

    def tracked_get_connection():
        connection = _RecordingConnection(original_get_connection(), fail_inserts=True)
        recording_connections.append(connection)
        return connection

    monkeypatch.setattr(monitor, "get_db_connection", tracked_get_connection)

    try:
        monitor.persist_protocol_peer_state(
            "bgp_neighbor_down",
            device_id,
            {"new-peer": "new-object"},
        )
    except RuntimeError as exc:
        assert str(exc) == "controlled peer snapshot insert failure"
    else:
        raise AssertionError("the failed peer insert must abort snapshot replacement")

    assert len(recording_connections) == 1
    assert recording_connections[0].commit_count == 0
    assert recording_connections[0].rollback_count == 1
    assert _read_peer_state(device_id) == previous


def test_protocol_peer_transitions_use_batched_alert_writer_and_commit_snapshot_first(monkeypatch):
    device_id = "protocol-peer-batch-device"
    old_bgp = {"192.0.2.1": "192.0.2.1"}
    monkeypatch.setattr(monitor, "protocol_peer_cache", {
        ("bgp_neighbor_down", device_id): old_bgp,
    })
    monkeypatch.setattr(monitor, "protocol_aggregate_threshold", 10)
    monkeypatch.setattr(monitor, "decrypt_credential", lambda value: value)
    monkeypatch.setattr(monitor, "should_collect", lambda *_args: True)
    monkeypatch.setattr(monitor, "resolve_collector_credentials", lambda *_args: {
        "snmp": {"configured": False},
        "ssh": {"username": "test-user", "password": "test-password"},
    })
    monkeypatch.setattr(monitor, "collect_operational_data", lambda *_args: {
        "categories": [
            {"key": "bgp", "success": True, "records": [{"neighbor": "192.0.2.2", "state": "Idle"}]},
            {"key": "ospf", "success": True, "records": [{"neighbor_id": "2.2.2.2", "state": "Down"}]},
            {"key": "bfd", "success": True, "records": [{"neighbor_addr": "192.0.2.3", "state": "Down"}]},
        ],
    })
    monkeypatch.setattr(monitor, "resolve_alert_rule", lambda *_args, **_kwargs: {
        "id": "protocol-peer-rule",
        "severity": "critical",
    })
    monkeypatch.setattr(monitor, "_sync_protocol_aggregate_alert", lambda *_args: None)
    monkeypatch.setattr(monitor, "_sync_protocol_flap_alert", lambda *_args: None)
    monkeypatch.setattr(monitor, "_is_protocol_notification_suppressed", lambda *_args: False)

    batch_calls: list[list[dict]] = []

    def record_batch(updates):
        batch_calls.append(list(updates))

    monkeypatch.setattr(monitor, "_set_alert_states_batched", record_batch)
    persisted: list[tuple[str, dict[str, str]]] = []

    def record_snapshot(metric_type: str, current_device_id: str, peers: dict[str, str]):
        assert current_device_id == device_id
        assert monitor.protocol_peer_cache.get((metric_type, current_device_id), {}) != peers
        persisted.append((metric_type, dict(peers)))

    monkeypatch.setattr(monitor, "persist_protocol_peer_state", record_snapshot)

    async def run_sync_work(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(monitor, "_run_monitoring_sync_work", run_sync_work)

    asyncio.run(monitor._collect_protocol_neighbor_alerts(
        {"id": device_id, "username": "test-user", "password": "test-password"},
        "192.0.2.10",
    ))

    assert [len(call) for call in batch_calls] == [2, 1, 1]
    assert [len(updates) for updates in batch_calls] == [2, 1, 1]
    assert [metric_type for metric_type, _peers in persisted] == [
        "bgp_neighbor_down",
        "ospf_neighbor_down",
        "bfd_session_down",
    ]
    assert monitor.protocol_peer_cache[("bgp_neighbor_down", device_id)] == {
        "192.0.2.2": "192.0.2.2",
    }
    assert monitor.protocol_peer_cache[("ospf_neighbor_down", device_id)] == {
        "2.2.2.2": "2.2.2.2",
    }
    assert monitor.protocol_peer_cache[("bfd_session_down", device_id)] == {
        "192.0.2.3": "192.0.2.3",
    }


def test_device_offline_peer_transitions_use_batched_alert_writer(monkeypatch):
    device_id = "offline-peer-batch-device"
    monkeypatch.setattr(monitor, "protocol_peer_cache", {
        ("bgp_neighbor_down", device_id): {
            "192.0.2.1": "192.0.2.1",
            "192.0.2.2": "192.0.2.2",
        },
    })
    monkeypatch.setattr(monitor, "protocol_aggregate_threshold", 10)
    monkeypatch.setattr(monitor, "resolve_alert_rule", lambda *_args, **_kwargs: {
        "id": "offline-peer-rule",
        "severity": "critical",
    })
    monkeypatch.setattr(monitor, "_sync_protocol_aggregate_alert", lambda *_args: None)
    monkeypatch.setattr(monitor, "_sync_protocol_flap_alert", lambda *_args: None)
    batch_calls: list[list[dict]] = []
    monkeypatch.setattr(monitor, "_set_alert_states_batched", lambda updates: batch_calls.append(list(updates)))

    monitor._set_protocol_alerts_for_device_offline(
        {"id": device_id, "hostname": "edge-offline"},
        "192.0.2.10",
    )

    assert [len(call) for call in batch_calls] == [2, 0, 0]
    assert [update["args"][0] for update in batch_calls[0]] == [
        f"bgp_neighbor_down:{device_id}:192.0.2.1",
        f"bgp_neighbor_down:{device_id}:192.0.2.2",
    ]
