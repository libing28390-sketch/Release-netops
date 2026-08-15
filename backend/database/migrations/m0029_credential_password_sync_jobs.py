"""Persist credential password synchronization jobs and per-device snapshots."""

VERSION = 29
NAME = "credential_password_sync_jobs"


def upgrade(cursor, _use_pg: bool) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS credential_password_sync_jobs (
            job_id TEXT PRIMARY KEY,
            credential_id TEXT NOT NULL,
            new_password TEXT DEFAULT '',
            new_enable_password TEXT DEFAULT '',
            actor_username TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'queued',
            central_commit_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            central_committed_at TEXT DEFAULT '',
            FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS credential_password_sync_locks (
            credential_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS credential_password_sync_targets (
            job_target_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            role TEXT NOT NULL,
            target_username TEXT DEFAULT '',
            old_target_password TEXT DEFAULT '',
            old_admin_username TEXT DEFAULT '',
            old_admin_password TEXT DEFAULT '',
            old_enable_password TEXT DEFAULT '',
            device_snapshot_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (job_id) REFERENCES credential_password_sync_jobs (job_id) ON DELETE CASCADE,
            FOREIGN KEY (job_target_id) REFERENCES job_targets (id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_credential_sync_jobs_credential "
        "ON credential_password_sync_jobs (credential_id, status)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_credential_sync_targets_job "
        "ON credential_password_sync_targets (job_id, device_id)"
    )
