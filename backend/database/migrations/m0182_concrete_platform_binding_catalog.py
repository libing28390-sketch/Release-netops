"""Publish the concrete vendor/platform/version catalog for device binding.

The TextFSM editor already exposes concrete namespaces such as
``huawei_vrp8`` and ``ruijie_rgos_v12``.  Device binding must resolve to the
same concrete identity instead of asking operators to guess from a family
name.  Keep legacy profiles for existing bindings, add the planned system
profiles, and scope a usable parser template set to newly-created profiles.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone


VERSION = 182
NAME = "concrete_platform_binding_catalog"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _template_code(value: str) -> str:
    code = re.sub(r"[^A-Z0-9_]", "_", str(value or "").upper())
    return code[:64] if code else "TEMPLATE"


def _clone_missing_templates(cursor, profile_defs: list[dict], profile_ids: dict[str, str], now: str) -> None:
    """Give every new concrete profile a scoped parser source when possible."""
    from database.migrations.m0102_concrete_system_template_scopes import _copy_versions

    concrete_codes = {
        str(item["platform_code"])
        for item in profile_defs
        if str(item.get("platform_code") or "") in {
            "huawei_vrp5", "huawei_vrp8", "huawei_vrp_unknown",
            "h3c_comware_v5", "h3c_comware_v7", "h3c_comware_v9", "h3c_comware_unknown",
            "maipu_mypower_v6", "maipu_mypower_v8", "maipu_mypower_v9", "maipu_mypower_unknown",
            "ruijie_rgos_v10", "ruijie_rgos_v11", "ruijie_rgos_v12", "ruijie_rgos_unknown",
            "zte_zxros", "zte_rosng", "zte_os_unknown",
            "dptech_conplat", "dptech_conplat_unknown",
        }
    }
    for profile in profile_defs:
        target_code = str(profile.get("platform_code") or "")
        target_id = profile_ids.get(target_code)
        if target_code not in concrete_codes or not target_id:
            continue
        existing_count = int(cursor.execute(
            "SELECT COUNT(*) FROM parser_templates WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_profile_id = ?",
            (target_id,),
        ).fetchone()[0] or 0)
        if existing_count:
            continue

        parser_platform = str(profile.get("parser_platform") or "").strip()
        source_rows = cursor.execute(
            """SELECT id, platform_code, template_code, source_filename, command,
                      name, source, status, created_by, created_at, updated_at, lock_version
                 FROM parser_templates
                 WHERE tenant_id IS NULL AND source = 'SYSTEM'
                   AND platform_profile_id IS NOT NULL
                   AND platform_code = ?
                 ORDER BY source_filename, id""",
            (parser_platform,),
        ).fetchall()
        for source in source_rows:
            source_id = str(source[0])
            scoped_name = f"{target_code}__{source[3] or source[2]}"
            scoped_code = _template_code(scoped_name)
            if not re.match(r"^[A-Z]", scoped_code):
                continue
            conflict = cursor.execute(
                """SELECT 1 FROM parser_templates
                   WHERE tenant_id IS NULL AND platform_profile_id = ?
                     AND platform_code = ? AND template_code = ?""",
                (target_id, parser_platform, scoped_code),
            ).fetchone()
            if conflict:
                digest = _checksum(f"{target_code}:{source_id}")[:8].upper()
                scoped_code = f"{scoped_code[:55]}_{digest}"
            target_id_value = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"nexora:m0182-template:{target_code}:{source_id}",
            ))
            cursor.execute(
                """INSERT INTO parser_templates
                   (id, tenant_id, platform_profile_id, platform_code, template_code,
                    source_filename, command, name, source, status, created_by,
                    created_at, updated_at, lock_version)
                   VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     platform_profile_id=excluded.platform_profile_id,
                     platform_code=excluded.platform_code,
                     template_code=excluded.template_code,
                     source_filename=excluded.source_filename,
                     command=excluded.command,
                     name=excluded.name,
                     updated_at=excluded.updated_at""",
                (
                    target_id_value,
                    target_id,
                    parser_platform,
                    scoped_code,
                    scoped_name,
                    source[4],
                    f"{target_code}: {source[5] or source[2]}",
                    source[7] or "ACTIVE",
                    source[8] or "system",
                    source[9] or now,
                    now,
                    source[11] or 1,
                ),
            )
            _copy_versions(cursor, source_id, target_id_value, target_code, now)


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    from services.platform_registry_service import SYSTEM_PROFILES
    from database.migrations.m0101_split_platform_profiles import _ensure_system_profiles
    from database.migrations.m0102_concrete_system_template_scopes import (
        _drop_global_system_template_index,
        _import_family_file_templates,
        _repair_release_bindings,
        _scope_templates,
    )

    now = _now()
    profile_defs = list(SYSTEM_PROFILES)
    _ensure_system_profiles(cursor, now)
    profile_ids = {
        str(row[1]): str(row[0])
        for row in cursor.execute(
            """SELECT id, platform_code FROM platform_profiles
               WHERE source = 'SYSTEM' AND tenant_id IS NULL"""
        ).fetchall()
    }
    _drop_global_system_template_index(cursor)
    _import_family_file_templates(cursor, profile_defs, now)
    _scope_templates(cursor, profile_defs, profile_ids, now)
    _clone_missing_templates(cursor, profile_defs, profile_ids, now)
    _repair_release_bindings(cursor, profile_defs, profile_ids, now)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Existing devices may already reference the concrete profiles.  Keeping
    # them during downgrade is safer than silently turning those bindings into
    # legacy family values.
    return None
