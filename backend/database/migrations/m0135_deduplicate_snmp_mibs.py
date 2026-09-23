"""Consolidate duplicate SNMP MIB catalog rows.

The first built-in seeder could be entered concurrently by two requests while
the repository was empty.  LibreNMS imports can also overlap a curated copy
when the source contains the same file.  This migration keeps one exact
catalog row and preserves the preferred provenance.
"""

from __future__ import annotations


VERSION = 135
NAME = "deduplicate_snmp_mibs"


_SOURCE_PRIORITY = {
    "builtin": 1,
    "librenms": 2,
    "user_upload": 3,
}


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _builtin_identity_key(row):
    name = _norm(row[1])
    vendor = _norm(row[2])
    filename = _norm(row[3])
    source_type = _norm(row[6])
    # Legacy built-in rows may not have a hash. They are still safe to
    # consolidate because the built-in identity is controlled by the catalog.
    if source_type == "builtin":
        return ("builtin", name, vendor, filename)
    return None


def _exact_content_key(row):
    name = _norm(row[1])
    vendor = _norm(row[2])
    filename = _norm(row[3])
    sha256 = _norm(row[4])
    if sha256:
        return ("exact", name, vendor, filename, sha256)
    return None


def _winner(rows):
    return max(
        rows,
        key=lambda row: (
            _SOURCE_PRIORITY.get(_norm(row[6]), 0),
            int(row[5] or 0),
            _norm(row[8]),
            _norm(row[7]),
            _norm(row[0]),
        ),
    )


def _consolidate(cursor, key_builder) -> None:
    rows = cursor.execute(
        "SELECT id, name, vendor, filename, sha256, node_count, source_type, "
        "created_at, updated_at FROM snmp_mibs WHERE is_active = 1"
    ).fetchall()
    grouped = {}
    for row in rows:
        key = key_builder(row)
        if key is not None:
            grouped.setdefault(key, []).append(row)

    for candidates in grouped.values():
        if len(candidates) < 2:
            continue
        winner_id = str(_winner(candidates)[0])
        for row in candidates:
            loser_id = str(row[0])
            if loser_id == winner_id:
                continue
            cursor.execute(
                "UPDATE snmp_mib_import_items SET mib_id = ? WHERE mib_id = ?",
                (winner_id, loser_id),
            )
            cursor.execute("DELETE FROM snmp_mib_nodes WHERE mib_id = ?", (loser_id,))
            cursor.execute("DELETE FROM snmp_mibs WHERE id = ?", (loser_id,))


def upgrade(cursor, use_pg: bool) -> None:
    # First collapse all curated copies by catalog identity, even when legacy
    # rows have missing or different hashes. Then collapse exact content across
    # built-in, LibreNMS, and user-uploaded provenance.
    _consolidate(cursor, _builtin_identity_key)
    _consolidate(cursor, _exact_content_key)

    # Prevent the original race from creating another active built-in copy.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_snmp_mibs_builtin_identity "
        "ON snmp_mibs (LOWER(TRIM(name)), LOWER(TRIM(vendor)), LOWER(TRIM(filename))) "
        "WHERE source_type = 'builtin' AND is_active = 1"
    )


def downgrade(cursor, use_pg: bool) -> None:
    return None
