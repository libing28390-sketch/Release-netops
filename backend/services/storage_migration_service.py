"""Explicit, resumable migration of legacy PAM/config files to StorageService."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from database import get_db_connection
from services.config_snapshot_storage import put_legacy_snapshot
from services.pam_recording_storage import recording_content_type, recording_object_key
from services.storage_service import build_storage_service


def _row_value(row, name: str, default=""):
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return default


def migrate_legacy_storage(*, limit: int = 100, dry_run: bool = False) -> dict[str, int]:
    """Migrate old rows without deleting their legacy files.

    The operation is intentionally explicit.  It never changes the selected
    provider and never treats a provider failure as permission to write a
    different backend.
    """

    max_rows = max(1, min(int(limit), 1000))
    result = {"config_attempted": 0, "config_migrated": 0, "pam_attempted": 0, "pam_migrated": 0, "failed": 0}
    conn = get_db_connection()
    try:
        config_rows = conn.execute(
            """SELECT * FROM config_snapshots
               WHERE COALESCE(object_key, '') = '' AND COALESCE(file_path, '') <> ''
               ORDER BY timestamp ASC LIMIT ?""",
            (max_rows,),
        ).fetchall()
        pam_rows = conn.execute(
            """SELECT * FROM pam_sessions
               WHERE COALESCE(object_key, '') = '' AND COALESCE(recording_path, '') <> ''
                 AND status NOT IN ('active', 'connecting')
               ORDER BY created_at ASC LIMIT ?""",
            (max_rows,),
        ).fetchall()
    finally:
        conn.close()

    if dry_run:
        result["config_attempted"] = len(config_rows)
        result["pam_attempted"] = len(pam_rows)
        return result

    for row in config_rows:
        result["config_attempted"] += 1
        try:
            stored = put_legacy_snapshot(
                snapshot_id=str(row["id"]),
                file_path=str(row["file_path"]),
            )
            conn = get_db_connection()
            try:
                conn.execute(
                    """UPDATE config_snapshots
                       SET storage_backend=?, storage_config_id=?, storage_bucket=?, object_key=?, object_version_id=?,
                           object_size=?, object_sha256=?, content_type=?, storage_status='READY',
                           storage_error='', storage_updated_at=?
                       WHERE id=?""",
                    (
                        stored.backend, getattr(stored, "storage_config_id", None), stored.bucket or "", stored.object_key, stored.version_id or "",
                        stored.size, stored.sha256 or "", stored.content_type or "application/octet-stream",
                        datetime.now(timezone.utc).isoformat(), row["id"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            result["config_migrated"] += 1
        except Exception:
            result["failed"] += 1

    for row in pam_rows:
        result["pam_attempted"] += 1
        path = Path(str(row["recording_path"] or ""))
        try:
            if not path.is_file():
                raise FileNotFoundError(str(path))
            suffix = path.suffix.lower() or ".cast"
            key = recording_object_key(str(row["id"]), row["created_at"], suffix)
            service = build_storage_service(purpose="pam_recording")
            with path.open("rb") as handle:
                stored = service.put_stream(key, handle, recording_content_type(suffix))
            conn = get_db_connection()
            try:
                conn.execute(
                    """UPDATE pam_sessions
                       SET storage_backend=?, storage_config_id=?, storage_bucket=?, object_key=?, object_version_id=?,
                           object_size=?, object_sha256=?, content_type=?, storage_status='READY',
                           storage_error='', storage_updated_at=?
                       WHERE id=?""",
                    (
                        stored.backend, getattr(stored, "storage_config_id", None), stored.bucket or "", stored.object_key, stored.version_id or "",
                        stored.size, stored.sha256 or "", stored.content_type or recording_content_type(suffix),
                        datetime.now(timezone.utc).isoformat(), row["id"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            result["pam_migrated"] += 1
        except Exception:
            result["failed"] += 1
    return result


__all__ = ["migrate_legacy_storage"]
