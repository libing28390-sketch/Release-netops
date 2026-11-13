"""Durable cursors for bounded, resumable collector sweeps."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database import _USE_PG, get_db_connection


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def reserve_collector_sweep_batch(
    collector: str,
    *,
    total_candidates: int,
    batch_size: int,
    run_id: str = "",
) -> dict[str, int | str]:
    """Reserve the next stable slice of a collector's candidate list.

    The caller supplies a deterministically ordered candidate list.  The
    cursor is advanced before network work starts, so a crashed worker cannot
    repeatedly hammer the same first page of devices on every retry.
    PostgreSQL uses a row lock; SQLite remains compatible for local installs.
    """
    total = max(0, int(total_candidates or 0))
    requested = max(0, int(batch_size or 0))
    if total == 0:
        return {"start_cursor": 0, "selected_count": 0, "next_cursor": 0}

    limit = total if requested == 0 else min(total, requested)
    now = _now()
    placeholder = "%s" if _USE_PG else "?"
    conn = get_db_connection()
    try:
        conn.execute(
            f"""
            INSERT INTO collector_sweep_state (
                collector, cursor_position, updated_at
            ) VALUES ({placeholder}, 0, {placeholder})
            ON CONFLICT(collector) DO NOTHING
            """,
            (collector, now),
        )
        lock_suffix = " FOR UPDATE" if _USE_PG else ""
        row = conn.execute(
            f"SELECT cursor_position FROM collector_sweep_state WHERE collector = {placeholder}{lock_suffix}",
            (collector,),
        ).fetchone()
        current = int((row[0] if row else 0) or 0) % total
        next_cursor = (current + limit) % total
        conn.execute(
            f"""
            UPDATE collector_sweep_state
               SET cursor_position = {placeholder}, last_run_id = {placeholder},
                   last_started_at = {placeholder}, last_eligible = {placeholder},
                   last_selected = {placeholder}, last_batch_size = {placeholder},
                   updated_at = {placeholder}
             WHERE collector = {placeholder}
            """,
            (next_cursor, run_id, now, total, limit, limit, now, collector),
        )
        conn.commit()
        return {
            "start_cursor": current,
            "selected_count": limit,
            "next_cursor": next_cursor,
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        # A missing migration must not prevent a network collection.  Falling
        # back to the first batch is safe; startup will apply the migration.
        return {"start_cursor": 0, "selected_count": limit, "next_cursor": limit % total}
    finally:
        conn.close()


def complete_collector_sweep(
    collector: str,
    *,
    run_id: str,
    successful_devices: int,
    failed_devices: int,
    collected_entries: int,
) -> None:
    """Record completion counters without affecting collector data."""
    now = _now()
    placeholder = "%s" if _USE_PG else "?"
    conn = get_db_connection()
    try:
        conn.execute(
            f"""
            UPDATE collector_sweep_state
               SET last_run_id = {placeholder}, last_completed_at = {placeholder},
                   last_successful = {placeholder}, last_failed = {placeholder},
                   last_collected = {placeholder}, updated_at = {placeholder}
             WHERE collector = {placeholder}
            """,
            (run_id, now, successful_devices, failed_devices, collected_entries, now, collector),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def get_collector_sweep_state(collector: str) -> dict[str, Any]:
    """Read the latest bounded-sweep state for API/status consumers."""
    conn = get_db_connection()
    try:
        placeholder = "%s" if _USE_PG else "?"
        row = conn.execute(
            f"SELECT * FROM collector_sweep_state WHERE collector = {placeholder}",
            (collector,),
        ).fetchone()
        return dict(row) if row is not None and hasattr(row, "keys") else (dict(row) if row else {})
    except Exception:
        return {}
    finally:
        conn.close()
