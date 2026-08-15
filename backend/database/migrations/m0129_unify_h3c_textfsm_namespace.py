"""Unify the H3C TextFSM namespace and make grammar variants explicit.

The runtime contract is now ``h3c_comware``.  Existing registry rows created
by earlier builds may still carry ``hp_comware``/``h3c_comware9`` parser keys
and filenames, so this migration moves those rows to the canonical namespace.
V5 and V9 grammars are represented by explicit ``h3c_comware_v5`` and
``h3c_comware_v9`` filename variants; the concrete Profile ID remains the
source of the command/release binding.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


VERSION = 129
NAME = "unify_h3c_textfsm_namespace"

_H3C_OLD_PARSER_KEYS = {"hp_comware", "h3c_comware9"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8].upper()


def _table_exists(cursor, table: str) -> bool:
    try:
        cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
        return True
    except Exception:
        return False


def _canonical_template_filename(filename: str, profile_code: str = "") -> str:
    """Rename only the old H3C prefix while preserving scoped profile names."""
    original = Path(str(filename or "")).name
    if "__" in original:
        outer, inner = original.split("__", 1)
        return f"{outer}__{_canonical_template_basename(inner, profile_code or outer)}"
    return _canonical_template_basename(original, profile_code)


def _canonical_template_basename(filename: str, profile_code: str = "") -> str:
    stem = str(filename or "")
    if not stem.lower().endswith(".textfsm"):
        return stem
    suffix = stem[:-len(".textfsm")]
    lower = suffix.lower()
    if lower.startswith("hp_comware_display_bgp_peer_ipv4_unicast"):
        return f"h3c_comware_{suffix[len('hp_comware_'): ]}.textfsm"
    if lower.startswith("hp_comware_"):
        return f"h3c_comware_v5_{suffix[len('hp_comware_'): ]}.textfsm"
    if lower == "h3c_comware9_display_bgp_peer_ipv4":
        return "h3c_comware_v9_display_bgp_peer_ipv4_unicast.textfsm"
    if lower.startswith("h3c_comware9_"):
        return f"h3c_comware_v9_{suffix[len('h3c_comware9_'): ]}.textfsm"
    return stem


def _template_code(filename: str) -> str:
    stem = Path(filename).stem
    code = re.sub(r"[^A-Za-z0-9_]", "_", stem.upper())
    return code[:64]


def _unique_template_code(cursor, row_id: str, tenant_id, profile_id, platform_code: str, candidate: str, filename: str) -> str:
    candidate = candidate or f"H3C_COMWARE_TEMPLATE_{_digest(filename)}"
    if len(candidate) > 64:
        candidate = candidate[:64]
    current = candidate
    counter = 0
    while True:
        conflict = cursor.execute(
            """SELECT 1 FROM parser_templates
               WHERE id <> ? AND platform_code = ? AND template_code = ?
                 AND ((tenant_id = ?) OR (tenant_id IS NULL AND ? IS NULL))
                 AND ((platform_profile_id = ?) OR (platform_profile_id IS NULL AND ? IS NULL))
               LIMIT 1""",
            (row_id, platform_code, current, tenant_id, tenant_id, profile_id, profile_id),
        ).fetchone()
        if not conflict:
            return current
        counter += 1
        digest = _digest(f"{filename}:{counter}")
        current = f"{candidate[:max(1, 64 - len(digest) - 1)]}_{digest}"


def _update_profile_parser_keys(cursor, now: str) -> None:
    if _table_exists(cursor, "platform_profiles"):
        cursor.execute(
            """UPDATE platform_profiles
               SET parser_platform = 'h3c_comware', updated_at = ?
               WHERE lower(COALESCE(parser_platform, '')) IN ('hp_comware', 'h3c_comware9')""",
            (now,),
        )
    if _table_exists(cursor, "platform_releases"):
        cursor.execute(
            """UPDATE platform_releases
               SET parser_platform = ?, updated_at = ?
               WHERE lower(COALESCE(parser_platform, '')) IN ('hp_comware', 'h3c_comware9')""",
            ("h3c_comware", now),
        )


def _update_parser_templates(cursor, now: str) -> None:
    if not _table_exists(cursor, "parser_templates"):
        return
    rows = cursor.execute(
        """SELECT id, tenant_id, platform_profile_id, platform_code,
                  template_code, source_filename
           FROM parser_templates
           ORDER BY id"""
    ).fetchall()
    for row in rows:
        row_id, tenant_id, profile_id = str(row[0]), row[1], row[2]
        old_platform = str(row[3] or "").strip().lower()
        old_filename = str(row[5] or "")
        profile_code = ""
        if _table_exists(cursor, "platform_profiles") and profile_id:
            profile = cursor.execute(
                "SELECT platform_code FROM platform_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
            profile_code = str(profile[0] or "") if profile else ""
        new_platform = "h3c_comware" if old_platform in _H3C_OLD_PARSER_KEYS else old_platform
        new_filename = _canonical_template_filename(old_filename, profile_code)
        new_code = str(row[4] or "")
        if new_filename != old_filename or new_platform != old_platform:
            new_code = _template_code(new_filename)
        new_code = _unique_template_code(
            cursor, row_id, tenant_id, profile_id, new_platform, new_code, new_filename,
        )
        if (
            new_platform != old_platform
            or new_filename != old_filename
            or new_code != str(row[4] or "")
        ):
            cursor.execute(
                """UPDATE parser_templates
                   SET platform_code = ?, source_filename = ?, template_code = ?, updated_at = ?
                   WHERE id = ?""",
                (new_platform, new_filename, new_code, now, row_id),
            )


def _update_device_platforms(cursor) -> None:
    if not _table_exists(cursor, "devices"):
        return
    try:
        cursor.execute(
            """UPDATE devices SET platform = 'h3c_comware'
               WHERE lower(COALESCE(platform, '')) IN ('hp_comware', 'h3c_comware9')"""
        )
    except Exception:
        # Some early fixtures do not have the platform column yet.
        return


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    now = _now()
    _update_profile_parser_keys(cursor, now)
    _update_parser_templates(cursor, now)
    _update_device_platforms(cursor)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
