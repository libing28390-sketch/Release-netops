"""Encrypted storage and retention helpers for Playbook execution output."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import settings
from core.crypto import decrypt_credential, encrypt_credential
from database import get_db_connection

logger = logging.getLogger(__name__)


class PlaybookOutputError(RuntimeError):
    """Raised when encrypted Playbook output cannot be decrypted or decoded."""


def _bounded_retention_days(value: Any, default: int = 30) -> int:
    try:
        return max(1, min(3650, int(value)))
    except (TypeError, ValueError):
        return default


def _retention_days() -> int:
    configured = os.environ.get("PLAYBOOK_RAW_OUTPUT_RETENTION_DAYS")
    if configured is None:
        configured = getattr(settings, "PLAYBOOK_RAW_OUTPUT_RETENTION_DAYS", 30)
    return _bounded_retention_days(configured)


def raw_output_expiry(now: datetime | None = None, *, retention_days: int | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    days = _retention_days() if retention_days is None else _bounded_retention_days(retention_days)
    return (current + timedelta(days=days)).replace(microsecond=0).isoformat()


def _serialize(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"), default=str)


def protect_output(
    value: Any,
    *,
    now: datetime | None = None,
    retention_days: int | None = None,
) -> tuple[str | None, str, str | None, bool]:
    """Return ciphertext, safe legacy placeholder, expiry and encryption status.

    New rows never store the raw JSON in the legacy column. If the application
    key is unavailable, the raw payload is discarded and callers can still
    persist execution status/counters safely.
    """
    plaintext = _serialize(value)
    try:
        ciphertext = encrypt_credential(plaintext)
    except Exception:
        logger.error("Playbook output encryption is unavailable; raw payload was discarded", exc_info=True)
        return None, "{}", None, False
    return ciphertext, "{}", raw_output_expiry(now, retention_days=retention_days), True


def load_output(ciphertext: str | None, legacy_json: str | None) -> Any:
    """Load encrypted output and fail closed on historical plaintext rows."""
    if ciphertext:
        try:
            plaintext = decrypt_credential(ciphertext)
        except Exception as exc:
            raise PlaybookOutputError("Encrypted Playbook output is unavailable") from exc
        if plaintext is None:
            raise PlaybookOutputError("Encrypted Playbook output is unavailable")
    else:
        # The legacy column is retained only as a compatibility placeholder.
        # Reading historical contents here would re-expose device output and
        # credentials after the encryption rollout.
        legacy = str(legacy_json or "").strip()
        if legacy and legacy != "{}":
            raise PlaybookOutputError("Historical plaintext Playbook output was quarantined")
        plaintext = "{}"
    try:
        return json.loads(plaintext)
    except (TypeError, json.JSONDecodeError) as exc:
        raise PlaybookOutputError("Playbook output is not valid JSON") from exc


def cleanup_expired_playbook_outputs(conn=None) -> int:
    """Delete ciphertext and legacy raw output after its retention deadline."""
    own_conn = conn is None
    if own_conn:
        conn = get_db_connection()
    deleted = 0
    try:
        for index, (table, encrypted_column, legacy_column) in enumerate((
            ("playbook_executions", "results_encrypted", "results_json"),
            ("execution_device_results", "phases_encrypted", "phases_json"),
        )):
            savepoint = f"playbook_output_cleanup_{index}"
            try:
                conn.execute(f"SAVEPOINT {savepoint}")
                cursor = conn.execute(
                    f"UPDATE {table} SET {encrypted_column} = NULL, {legacy_column} = ?, "
                    "raw_output_expires_at = NULL "
                    "WHERE raw_output_expires_at IS NOT NULL AND raw_output_expires_at < ?",
                    ("{}", datetime.now(timezone.utc).replace(microsecond=0).isoformat()),
                )
                deleted += int(getattr(cursor, "rowcount", 0) or 0)
            except Exception:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                except Exception:
                    pass
                # Older test databases and installations are upgraded before
                # this job runs; one absent table must not block the other.
                logger.debug("Playbook output cleanup skipped for %s", table, exc_info=True)
            finally:
                try:
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    pass
        if own_conn:
            conn.commit()
        return deleted
    finally:
        if own_conn:
            conn.close()
