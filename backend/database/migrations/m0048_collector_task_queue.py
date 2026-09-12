"""Add a leased collector task queue and process-safe worker slots."""

from __future__ import annotations


VERSION = 48
NAME = "collector_task_queue"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS collector_task_queue (
            id TEXT PRIMARY KEY,
            collector TEXT NOT NULL,
            device_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 100,
            available_at TEXT NOT NULL,
            lease_owner TEXT DEFAULT '',
            lease_until TEXT,
            attempt INTEGER NOT NULL DEFAULT 0,
            error_class TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            payload_json TEXT DEFAULT '{}',
            result_json TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE (collector, device_id),
            FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_collector_task_claim "
        "ON collector_task_queue(collector, status, available_at, priority)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_collector_task_lease "
        "ON collector_task_queue(collector, lease_until)"
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS collector_worker_slots (
            collector TEXT NOT NULL,
            slot_id INTEGER NOT NULL,
            task_id TEXT,
            lease_owner TEXT DEFAULT '',
            lease_until TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (collector, slot_id),
            UNIQUE (collector, task_id)
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_collector_worker_slot_lease "
        "ON collector_worker_slots(collector, lease_until)"
    )
