"""Persist configuration-backup batches and per-device outcomes.

The legacy ``config_snapshots`` table stores successful snapshots only.  That
is insufficient for an audit-friendly backup history because skipped and
failed devices disappear from the record.  This migration adds a small,
append-oriented execution ledger while keeping the snapshot table backward
compatible.
"""

from __future__ import annotations


VERSION = 42
NAME = "config_backup_runs"


def upgrade(cursor, use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_backup_runs (
            id TEXT PRIMARY KEY,
            trigger TEXT NOT NULL DEFAULT 'scheduled',
            author TEXT NOT NULL DEFAULT 'system',
            status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            total_devices INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            policy_snapshot TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS config_backup_run_devices (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            device_id TEXT,
            hostname TEXT NOT NULL DEFAULT '',
            ip_address TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            snapshot_id TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            duration_ms INTEGER,
            FOREIGN KEY (run_id) REFERENCES config_backup_runs (id) ON DELETE CASCADE,
            FOREIGN KEY (device_id) REFERENCES devices (id) ON DELETE SET NULL
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_backup_runs_started_at "
        "ON config_backup_runs(started_at DESC)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_backup_run_devices_run_id "
        "ON config_backup_run_devices(run_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_config_backup_run_devices_device_id "
        "ON config_backup_run_devices(device_id, started_at DESC)"
    )
