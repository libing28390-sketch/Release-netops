"""Keep one active LibreNMS row per upstream relative path.

Before this migration, ``source_id`` was derived from the Git commit. Every
upstream update therefore looked like a new source and could leave the old
active rows beside the new rows. The commit remains available on source and
import-run records; catalog identity is now the logical LibreNMS path.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone


VERSION = 136
NAME = "stabilize_librenms_source_identity"


def _stable_source_id() -> str:
    value = "librenms\0librenms\0catalog".encode("utf-8")
    return f"source-{hashlib.sha256(value).hexdigest()[:24]}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _value(row, index: int):
    return row[index]


def _winner(rows):
    return max(
        rows,
        key=lambda row: (
            1 if str(_value(row, 2) or "").strip().lower() in {"parsed", "zero_node"} else 0,
            str(_value(row, 4) or ""),
            int(_value(row, 3) or 0),
            str(_value(row, 0) or ""),
        ),
    )


def upgrade(cursor, use_pg: bool) -> None:
    stable_id = _stable_source_id()

    # Re-key only path-aware LibreNMS rows. Legacy rows without a relative
    # path remain eligible for the existing filename/vendor adoption fallback.
    cursor.execute(
        "UPDATE snmp_mibs SET source_id = ? "
        "WHERE source_type = 'librenms' AND relative_path <> '' AND source_id <> ?",
        (stable_id, stable_id),
    )
    cursor.execute(
        "UPDATE snmp_mib_import_items SET source_id = ? "
        "WHERE mib_id IN ("
        "SELECT id FROM snmp_mibs WHERE source_type = 'librenms' AND relative_path <> ''"
        ")",
        (stable_id,),
    )

    rows = cursor.execute(
        "SELECT id, relative_path, parse_status, node_count, updated_at "
        "FROM snmp_mibs "
        "WHERE source_type = 'librenms' AND is_active = 1 AND relative_path <> ''"
    ).fetchall()
    grouped = {}
    for row in rows:
        grouped.setdefault(str(_value(row, 1) or ""), []).append(row)

    retired_at = _now()
    for candidates in grouped.values():
        if len(candidates) < 2:
            continue
        winner_id = str(_value(_winner(candidates), 0))
        for row in candidates:
            loser_id = str(_value(row, 0))
            if loser_id == winner_id:
                continue
            cursor.execute(
                "UPDATE snmp_mib_import_items SET mib_id = ? WHERE mib_id = ?",
                (winner_id, loser_id),
            )
            # Preserve the old row and its nodes for audit/recovery, but keep
            # it out of the active catalog and filtered counts.
            cursor.execute(
                "UPDATE snmp_mibs SET is_active = 0, updated_at = ? WHERE id = ?",
                (retired_at, loser_id),
            )

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_snmp_mibs_librenms_path "
        "ON snmp_mibs (source_id, relative_path) "
        "WHERE source_type = 'librenms' AND is_active = 1 AND relative_path <> ''"
    )


def downgrade(cursor, use_pg: bool) -> None:
    # The catalog identity correction is intentionally not reversed: restoring
    # commit-based identity would reintroduce duplicate active MIBs.
    return None
