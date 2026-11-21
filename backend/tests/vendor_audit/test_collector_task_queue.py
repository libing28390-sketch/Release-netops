from backend.tests.pg_test_utils import postgresql_test_driver
from datetime import datetime, timedelta, timezone

import services.collector_task_queue_service as queue_service
from database.migrations.m0048_collector_task_queue import upgrade as upgrade_queue
from database.migrations.m0049_arp_cache_source_index import upgrade as upgrade_arp_cache


class _ConnectionProxy:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self):
        pass


def _patch_queue_db(monkeypatch):
    connection = postgresql_test_driver.connect()
    connection.row_factory = postgresql_test_driver.Row
    connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
    upgrade_queue(connection.cursor(), use_pg=True)
    monkeypatch.setattr(queue_service, "get_db_connection", lambda: _ConnectionProxy(connection))
    monkeypatch.setattr(queue_service, "_USE_PG", True)
    connection.execute("INSERT INTO devices (id) VALUES (?)", ("device-1",))
    return connection


def test_queue_claim_is_exclusive_and_failed_task_is_requeued(monkeypatch):
    connection = _patch_queue_db(monkeypatch)
    queue_service.ensure_worker_slots("arp", 1)
    queue_service.enqueue_tasks(
        "arp",
        run_id="run-1",
        device_ids=["device-1"],
        payload_by_device={"device-1": {"arp_policy_override": True}},
    )

    task = queue_service.claim_task("arp", worker_id="worker-1", slot_count=1, lease_seconds=120)
    assert task and task["status"] == "running"
    assert queue_service.claim_task("arp", worker_id="worker-2", slot_count=1, lease_seconds=120) is None

    queue_service.finish_task(
        task,
        worker_id="worker-1",
        success=False,
        retry_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        error_class="unreachable",
    )
    assert connection.execute("SELECT status FROM collector_task_queue").fetchone()[0] == "pending"
    assert connection.execute("SELECT task_id FROM collector_worker_slots").fetchone()[0] is None


def test_queue_migrations_are_idempotent_and_arp_source_is_backfilled():
    connection = postgresql_test_driver.connect()
    connection.execute("CREATE TABLE devices (id TEXT PRIMARY KEY)")
    connection.execute(
        """CREATE TABLE arp_cache (
            target_ip TEXT PRIMARY KEY, mac TEXT NOT NULL, vlan_id INTEGER,
            arp_source TEXT NOT NULL DEFAULT '{}', cached_at TEXT NOT NULL, expires_at REAL NOT NULL
        )"""
    )
    connection.execute(
        "INSERT INTO arp_cache(target_ip, mac, arp_source, cached_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        ("10.0.0.1", "0000-0000-0001", '{"device_id":"device-1"}', "now", 1),
    )
    upgrade_arp_cache(connection.cursor(), use_pg=True)
    upgrade_arp_cache(connection.cursor(), use_pg=True)
    source = connection.execute("SELECT source_device_id FROM arp_cache").fetchone()[0]
    assert source == "device-1"
