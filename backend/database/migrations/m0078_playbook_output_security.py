"""Add encrypted Playbook output columns and retention timestamps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


VERSION = 78
NAME = "playbook_output_security"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(cursor, table: str, use_pg: bool) -> bool:
    if use_pg:
        row = cursor.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchone()
        return bool(row)
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def _add_columns(cursor, table: str, use_pg: bool, additions: tuple[tuple[str, str], ...]) -> set[str]:
    if not _table_exists(cursor, table, use_pg):
        return set()
    columns = _columns(cursor, table, use_pg)
    for name, definition in additions:
        if name not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
            columns.add(name)
    return columns


def _retention_expiry(value: str | None) -> str:
    now = datetime.now(timezone.utc)
    try:
        if value:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            now = parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    return (now + timedelta(days=30)).replace(microsecond=0).isoformat()


def _encrypt_legacy_rows(cursor, table: str, encrypted_column: str, legacy_column: str, timestamp_column: str) -> None:
    """Best-effort backfill; a missing key leaves legacy rows for later cleanup."""
    try:
        from core.crypto import encrypt_credential

        rows = cursor.execute(
            f"SELECT id, {legacy_column}, {timestamp_column} FROM {table} "
            f"WHERE ({encrypted_column} IS NULL OR {encrypted_column} = '') "
            f"AND {legacy_column} IS NOT NULL AND {legacy_column} <> '{{}}'"
        ).fetchall()
        for row in rows:
            legacy = row[1]
            if not legacy:
                continue
            try:
                ciphertext = encrypt_credential(str(legacy))
            except Exception:
                continue
            if not ciphertext:
                continue
            cursor.execute(
                f"UPDATE {table} SET {encrypted_column} = ?, {legacy_column} = ?, "
                f"raw_output_expires_at = ? WHERE id = ?",
                (ciphertext, "{}", _retention_expiry(row[2]), row[0]),
            )
    except Exception:
        # Schema upgrade must remain available even when an operator has not
        # configured the master key yet; new writes will fail closed instead.
        return


def upgrade(cursor, use_pg: bool) -> None:
    execution_columns = _add_columns(
        cursor,
        "playbook_executions",
        use_pg,
        (("results_encrypted", "TEXT"), ("raw_output_expires_at", "TEXT")),
    )
    if {"results_encrypted", "raw_output_expires_at", "results_json", "updated_at"} <= execution_columns:
        _encrypt_legacy_rows(cursor, "playbook_executions", "results_encrypted", "results_json", "updated_at")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_playbook_executions_output_expiry "
            "ON playbook_executions(raw_output_expires_at)"
        )

    device_columns = _add_columns(
        cursor,
        "execution_device_results",
        use_pg,
        (("phases_encrypted", "TEXT"), ("raw_output_expires_at", "TEXT")),
    )
    if {"phases_encrypted", "raw_output_expires_at", "phases_json", "completed_at"} <= device_columns:
        _encrypt_legacy_rows(cursor, "execution_device_results", "phases_encrypted", "phases_json", "completed_at")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS ix_execution_device_results_output_expiry "
            "ON execution_device_results(raw_output_expires_at)"
        )
