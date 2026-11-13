"""Add parser version lifecycle metadata and encrypted sample storage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


VERSION = 86
NAME = "parser_template_lifecycle_security"


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    rows = cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(row[0]).lower() for row in rows}



def _add_columns(cursor, table: str, use_pg: bool, definitions: tuple[tuple[str, str], ...]) -> None:
    columns = _columns(cursor, table, use_pg)
    for name, definition in definitions:
        if name not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def upgrade(cursor, use_pg: bool) -> None:
    _add_columns(cursor, "parser_template_versions", use_pg, (
        ("submitted_by", "TEXT DEFAULT ''"),
        ("approved_by", "TEXT DEFAULT ''"),
        ("published_by", "TEXT DEFAULT ''"),
        ("lock_version", "INTEGER NOT NULL DEFAULT 1"),
    ))
    _add_columns(cursor, "parser_test_samples", use_pg, (
        ("sample_output_encrypted", "TEXT"),
        ("raw_output_expires_at", "TEXT"),
    ))
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_parser_test_samples_output_expiry "
        "ON parser_test_samples(raw_output_expires_at)"
    )

    # Existing installations may contain samples created before the encrypted
    # column existed.  Preserve them only when the application key is
    # available; otherwise quarantine the raw value instead of leaving it in
    # the database.  The old lifecycle API was retired; current template
    # writes are handled by the file-backed TextFSM endpoint.
    from core.crypto import encrypt_credential

    fallback_expiry = (datetime.now(timezone.utc) + timedelta(days=30)).replace(microsecond=0).isoformat()
    rows = cursor.execute(
        "SELECT id, sample_output, sample_output_encrypted, raw_output_expires_at "
        "FROM parser_test_samples"
    ).fetchall()
    for row in rows:
        sample_id, raw_output, encrypted, expiry = row[0], row[1], row[2], row[3]
        raw_text = str(raw_output or "").strip()
        if not raw_text or raw_text == "{}":
            continue
        ciphertext = encrypted
        if not ciphertext:
            try:
                ciphertext = encrypt_credential(raw_text)
            except Exception:
                ciphertext = None
        if ciphertext:
            cursor.execute(
                "UPDATE parser_test_samples SET sample_output = ?, sample_output_encrypted = ?, "
                "raw_output_expires_at = COALESCE(raw_output_expires_at, ?) WHERE id = ?",
                ("{}", ciphertext, expiry or fallback_expiry, sample_id),
            )
        else:
            cursor.execute(
                "UPDATE parser_test_samples SET sample_output = ?, sample_output_encrypted = NULL, "
                "raw_output_expires_at = NULL WHERE id = ?",
                ("{}", sample_id),
            )
