"""Separate scheduler lease owners from timestamps and use PostgreSQL TSTZ."""

from __future__ import annotations


VERSION = 229
NAME = "scheduler_lock_timestamptz"


def _column_type(cursor, name: str) -> str | None:
    cursor.execute(
        """
        SELECT data_type
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND table_name = 'scheduler_locks'
           AND column_name = %s
        """,
        (name,),
    )
    row = cursor.fetchone()
    return str(row[0]) if row else None


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("scheduler_lock_timestamptz requires PostgreSQL")

    locked_at_type = _column_type(cursor, "locked_at")
    expires_at_type = _column_type(cursor, "expires_at")
    if locked_at_type is None or expires_at_type is None:
        raise RuntimeError("scheduler_locks is missing legacy time columns")

    if locked_at_type == "timestamp with time zone" and expires_at_type == "timestamp with time zone":
        cursor.execute("ALTER TABLE scheduler_locks ADD COLUMN IF NOT EXISTS owner_token TEXT")
        cursor.execute(
            """
            UPDATE scheduler_locks
               SET owner_token = md5(lock_name || clock_timestamp()::text || random()::text)
             WHERE owner_token IS NULL OR BTRIM(owner_token) = ''
            """
        )
        cursor.execute("ALTER TABLE scheduler_locks ALTER COLUMN owner_token SET NOT NULL")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduler_locks_expires ON scheduler_locks(expires_at)")
        return

    if locked_at_type != "text" or expires_at_type != "text":
        raise RuntimeError(
            "scheduler_locks has unsupported time column types: "
            f"locked_at={locked_at_type}, expires_at={expires_at_type}"
        )

    # Old rows used locked_at for either an ISO-8601 acquisition time or an
    # opaque Reindex/Import owner token. Preserve tokens before replacing the
    # legacy column; never try to cast a token to a timestamp.
    cursor.execute("ALTER TABLE scheduler_locks ADD COLUMN IF NOT EXISTS owner_token TEXT")
    cursor.execute("ALTER TABLE scheduler_locks ADD COLUMN IF NOT EXISTS locked_at_tz TIMESTAMPTZ")
    cursor.execute("ALTER TABLE scheduler_locks ADD COLUMN IF NOT EXISTS expires_at_tz TIMESTAMPTZ")
    cursor.execute(
        """
        UPDATE scheduler_locks
           SET owner_token = CASE
                   WHEN COALESCE(NULLIF(BTRIM(owner_token), ''), '') <> '' THEN owner_token
                   WHEN locked_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]'
                       THEN md5(lock_name || clock_timestamp()::text || random()::text)
                   ELSE COALESCE(NULLIF(locked_at, ''), md5(lock_name || random()::text))
               END,
               locked_at_tz = CASE
                   WHEN locked_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ]' THEN locked_at::timestamptz
                   ELSE clock_timestamp()
               END,
               expires_at_tz = expires_at::timestamptz
        """
    )
    cursor.execute("DROP INDEX IF EXISTS idx_scheduler_locks_expires")
    cursor.execute("ALTER TABLE scheduler_locks DROP COLUMN locked_at")
    cursor.execute("ALTER TABLE scheduler_locks DROP COLUMN expires_at")
    cursor.execute("ALTER TABLE scheduler_locks RENAME COLUMN locked_at_tz TO locked_at")
    cursor.execute("ALTER TABLE scheduler_locks RENAME COLUMN expires_at_tz TO expires_at")
    cursor.execute("ALTER TABLE scheduler_locks ALTER COLUMN owner_token SET NOT NULL")
    cursor.execute("ALTER TABLE scheduler_locks ALTER COLUMN locked_at SET NOT NULL")
    cursor.execute("ALTER TABLE scheduler_locks ALTER COLUMN expires_at SET NOT NULL")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduler_locks_expires ON scheduler_locks(expires_at)")


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    if not use_pg:
        raise RuntimeError("scheduler_lock_timestamptz requires PostgreSQL")

    # Restore the V1 shape for a coordinated application rollback. Lease owner
    # tokens remain in locked_at for the two legacy owner-token namespaces;
    # scheduler timestamps are serialized in canonical UTC ISO-8601 form.
    cursor.execute("ALTER TABLE scheduler_locks ADD COLUMN locked_at_text TEXT")
    cursor.execute("ALTER TABLE scheduler_locks ADD COLUMN expires_at_text TEXT")
    cursor.execute(
        """
        UPDATE scheduler_locks
           SET locked_at_text = CASE
                   WHEN lock_name LIKE 'knowledge_reindex:%'
                     OR lock_name LIKE 'knowledge_import:%'
                       THEN owner_token
                   ELSE to_char(locked_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00'
               END,
               expires_at_text = to_char(expires_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00'
        """
    )
    cursor.execute("DROP INDEX IF EXISTS idx_scheduler_locks_expires")
    cursor.execute("ALTER TABLE scheduler_locks DROP COLUMN locked_at")
    cursor.execute("ALTER TABLE scheduler_locks DROP COLUMN expires_at")
    cursor.execute("ALTER TABLE scheduler_locks RENAME COLUMN locked_at_text TO locked_at")
    cursor.execute("ALTER TABLE scheduler_locks RENAME COLUMN expires_at_text TO expires_at")
    cursor.execute("ALTER TABLE scheduler_locks DROP COLUMN owner_token")
    cursor.execute("ALTER TABLE scheduler_locks ALTER COLUMN locked_at SET NOT NULL")
    cursor.execute("ALTER TABLE scheduler_locks ALTER COLUMN expires_at SET NOT NULL")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduler_locks_expires ON scheduler_locks(expires_at)")


__all__ = ["VERSION", "NAME", "upgrade", "downgrade"]
