"""Track the latest user who changed a scheduled job."""

from __future__ import annotations


VERSION = 288
NAME = "scheduled_job_updated_by"


def upgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    cursor.execute(
        "ALTER TABLE scheduled_jobs "
        "ADD COLUMN IF NOT EXISTS updated_by TEXT NOT NULL DEFAULT ''"
    )
    cursor.execute(
        """
        UPDATE scheduled_jobs
           SET updated_by = COALESCE(NULLIF(BTRIM(updated_by), ''),
                                     NULLIF(BTRIM(created_by), ''),
                                     'system')
         WHERE BTRIM(COALESCE(updated_by, '')) = ''
        """
    )


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep the audit metadata if application code is rolled back.
    return None


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
