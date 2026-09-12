"""Quarantine any Playbook output that remained in legacy plaintext columns."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


VERSION = 79
NAME = "quarantine_playbook_plaintext"


def _table_exists(cursor, table: str, use_pg: bool) -> bool:
    return bool(cursor.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchone())



def _expiry(value: object) -> str:
    now = datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    return (now + timedelta(days=30)).replace(microsecond=0).isoformat()


def _quarantine(cursor, table: str, encrypted_column: str, legacy_column: str, timestamp_column: str, use_pg: bool) -> None:
    if not _table_exists(cursor, table, use_pg):
        return
    from core.crypto import encrypt_credential

    rows = cursor.execute(
        f"SELECT id, {encrypted_column}, {legacy_column}, {timestamp_column} FROM {table} "
        f"WHERE {legacy_column} IS NOT NULL AND {legacy_column} <> '{{}}'"
    ).fetchall()
    for row in rows:
        ciphertext = row[1]
        legacy = str(row[2] or "")
        if ciphertext:
            cursor.execute(f"UPDATE {table} SET {legacy_column} = '{{}}' WHERE id = ?", (row[0],))
            continue
        try:
            ciphertext = encrypt_credential(legacy)
        except Exception:
            ciphertext = None
        if ciphertext:
            cursor.execute(
                f"UPDATE {table} SET {encrypted_column} = ?, {legacy_column} = '{{}}', raw_output_expires_at = ? WHERE id = ?",
                (ciphertext, _expiry(row[3]), row[0]),
            )
        else:
            # Do not create a key during migration.  Without one, discard the
            # plaintext instead of leaving a recoverable secret in the DB.
            cursor.execute(
                f"UPDATE {table} SET {encrypted_column} = NULL, {legacy_column} = '{{}}', raw_output_expires_at = NULL WHERE id = ?",
                (row[0],),
            )


def upgrade(cursor, use_pg: bool) -> None:
    _quarantine(cursor, "playbook_executions", "results_encrypted", "results_json", "updated_at", use_pg)
    _quarantine(cursor, "execution_device_results", "phases_encrypted", "phases_json", "completed_at", use_pg)
