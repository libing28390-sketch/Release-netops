"""Register the H3C Comware V3 system platform profile.

H3C V3 is an older Comware generation and uses the same Netmiko transport as
the existing H3C profiles.  There is no verified V3-specific TextFSM grammar
in the repository yet, so the runtime intentionally routes its parser/action
selection through the legacy V5-compatible command forms and existing H3C
templates.  The migration still scopes the published system template rows to
the new immutable Profile so old Docker installations receive the same
registry contract as fresh installations.
"""

from __future__ import annotations

import hashlib
import uuid


VERSION = 212
NAME = "h3c_comware_v3_platform"


def _target_template_code(source_id: str, source_code: str) -> str:
    """Build a deterministic, unique code within the database's 64-char limit."""

    raw_code = f"H3C_V3_{source_code}"
    if len(raw_code) <= 64:
        return raw_code

    digest = hashlib.sha256(f"{source_id}:{source_code}".encode("utf-8")).hexdigest()[:8].upper()
    return f"{raw_code[:55]}_{digest}"


def _clone_v5_templates_to_v3(cursor, profile_ids: dict[str, str], now: str) -> None:
    """Give V3 the verified legacy V5 parser bindings without new files."""

    from database.migrations.m0102_concrete_system_template_scopes import _copy_versions

    source_profile_id = profile_ids.get("hp_comware")
    target_profile_id = profile_ids.get("h3c_comware_v3")
    if not source_profile_id or not target_profile_id:
        return

    rows = cursor.execute(
        """SELECT id, platform_code, template_code, source_filename, command,
                  name, source, status, created_by, created_at, updated_at,
                  lock_version
             FROM parser_templates
            WHERE tenant_id IS NULL
              AND source = 'SYSTEM'
              AND platform_profile_id = ?
            ORDER BY source_filename, id""",
        (source_profile_id,),
    ).fetchall()
    for row in rows:
        source_id = str(row[0])
        target_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"nexora:m0212-h3c-v3-template:{source_id}",
        ))
        source_code = str(row[2] or "TEMPLATE").upper()
        target_code = _target_template_code(source_id, source_code)
        cursor.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, command, name, source, status, created_by,
                created_at, updated_at, lock_version)
               VALUES (?, NULL, ?, 'h3c_comware', ?, ?, ?, ?, 'SYSTEM', ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 platform_profile_id=excluded.platform_profile_id,
                 platform_code=excluded.platform_code,
                 template_code=excluded.template_code,
                 source_filename=excluded.source_filename,
                 command=excluded.command,
                 name=excluded.name,
                 status=excluded.status,
                 updated_at=excluded.updated_at""",
            (
                target_id,
                target_profile_id,
                target_code,
                f"h3c_comware_v3__{row[3] or row[2]}",
                row[4] or "",
                f"H3C Comware V3 compatibility: {row[5] or row[2]}",
                row[7] or "ACTIVE",
                row[8] or "system",
                row[9] or now,
                now,
                row[11] or 1,
            ),
        )
        _copy_versions(cursor, source_id, target_id, "h3c_comware_v3", now)


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg

    from services.platform_registry_service import SYSTEM_PROFILES
    from database.migrations.m0101_split_platform_profiles import _ensure_system_profiles, _now
    from database.migrations.m0102_concrete_system_template_scopes import (
        _drop_global_system_template_index,
        _repair_release_bindings,
        _scope_templates,
    )

    now = _now()
    profile_defs = list(SYSTEM_PROFILES)

    # This helper is idempotent and also repairs the published action snapshot
    # for the new profile from the current declarative service definition.
    _ensure_system_profiles(cursor, now)
    profile_ids = {
        str(row[1]): str(row[0])
        for row in cursor.execute(
            """SELECT id, platform_code FROM platform_profiles
               WHERE source = 'SYSTEM' AND tenant_id IS NULL"""
        ).fetchall()
    }

    # Reuse the established concrete-profile scoping contract.  For V3 this
    # creates profile-owned copies of the existing H3C family templates; no
    # unverified V3 grammar file is invented by the migration.
    _drop_global_system_template_index(cursor)
    _scope_templates(cursor, profile_defs, profile_ids, now)
    _clone_v5_templates_to_v3(cursor, profile_ids, now)
    _repair_release_bindings(cursor, profile_defs, profile_ids, now)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Existing devices may already reference the new system profile. Keeping
    # it is safer than silently changing their transport/parser identity.
    return None
