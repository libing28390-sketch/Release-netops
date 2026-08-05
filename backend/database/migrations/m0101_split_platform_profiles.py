"""Split concrete platform identities and repair scoped parser bindings.

The original registry used one parser/connection family as if it were the
concrete platform identity.  That is unsafe when one vendor has multiple
command grammars.  This migration keeps the existing H3C V7 profile, adds the
V5/V9 profiles, imports each file template into its concrete Profile scope,
and repairs every SYSTEM action binding by exact profile + command match.

The same mechanics are intentionally data-driven: future vendors can add
multiple system/custom Profiles without introducing a vendor-specific runtime
fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


VERSION = 101
NAME = "split_platform_profiles"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _system_profile_id(cursor, profile: dict) -> str:
    expected_id = f"system-profile-{profile['platform_code']}"
    row = cursor.execute(
        "SELECT id FROM platform_profiles WHERE source = 'SYSTEM' AND tenant_id IS NULL AND platform_code = ?",
        (profile["platform_code"],),
    ).fetchone()
    return str(row[0]) if row else expected_id


def _ensure_system_profiles(cursor, now: str) -> dict[str, str]:
    from services.platform_registry_service import SYSTEM_PROFILES, get_profile_action_commands

    profile_ids: dict[str, str] = {}
    for profile in SYSTEM_PROFILES:
        profile_code = str(profile["platform_code"])
        profile_id = _system_profile_id(cursor, profile)
        profile_ids[profile_code] = profile_id
        cursor.execute(
            """INSERT INTO platform_profiles
               (id, tenant_id, platform_code, name_zh, name_en, vendor,
                connection_driver, parser_platform, source, status, description,
                created_by, created_at, updated_at, lock_version)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE', '',
                       'system', ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                 platform_code=excluded.platform_code,
                 name_zh=excluded.name_zh,
                 name_en=excluded.name_en,
                 vendor=excluded.vendor,
                 connection_driver=excluded.connection_driver,
                 parser_platform=excluded.parser_platform,
                 updated_at=excluded.updated_at""",
            (
                profile_id,
                profile_code,
                profile["name_zh"],
                profile["name_en"],
                profile["vendor"],
                profile["connection_driver"],
                profile["parser_platform"],
                now,
                now,
            ),
        )

        release_id = f"system-release-{profile_code}-v1"
        cursor.execute(
            """INSERT INTO platform_releases
               (id, profile_id, release_number, status, connection_driver,
                parser_platform, safety_policy_json, checksum, validation_status,
                validation_result_json, created_by, approved_by, published_by,
                created_at, updated_at, lock_version)
               VALUES (?, ?, 1, 'PUBLISHED', ?, ?, ?, ?, 'PASSED',
                       '{"seed":true}', 'system', 'system', 'system', ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                 profile_id=excluded.profile_id,
                 connection_driver=excluded.connection_driver,
                 parser_platform=excluded.parser_platform,
                 updated_at=excluded.updated_at""",
            (
                release_id,
                profile_id,
                profile["connection_driver"],
                profile["parser_platform"],
                json.dumps({"read_only": True, "allowed_prefixes": ["show", "display"]}, ensure_ascii=False, sort_keys=True),
                _checksum(f"{profile_code}:1"),
                now,
                now,
            ),
        )
        cursor.execute(
            "UPDATE platform_profiles SET current_release_id = ? WHERE id = ? AND (current_release_id IS NULL OR current_release_id = '')",
            (release_id, profile_id),
        )
        for action_code, command in get_profile_action_commands(profile).items():
            action_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}"))
            cursor.execute(
                """INSERT INTO platform_release_actions
                   (id, release_id, action_code, command, field_contract_json,
                    command_checksum, created_at, updated_at)
                   VALUES (?, ?, ?, ?, '{}', ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     command=excluded.command,
                     command_checksum=excluded.command_checksum,
                     updated_at=excluded.updated_at""",
                (action_id, release_id, action_code, command, _checksum(command), now, now),
            )
    return profile_ids


def _profile_for_template(profile_defs: list[dict], filename: str) -> dict | None:
    stem = Path(filename).stem.lower()
    # The unicast template was added under the historical hp_comware filename
    # but belongs to the V7 command grammar.  Keep the file name for backward
    # compatibility while moving its registry scope to the V7 Profile.
    if stem == "hp_comware_display_bgp_peer_ipv4_unicast":
        return next((item for item in profile_defs if item["platform_code"] == "h3c_comware"), None)
    return next(
        (item for item in sorted(profile_defs, key=lambda item: len(str(item["platform_code"])), reverse=True)
         if stem.startswith(f"{str(item['platform_code']).lower()}_")),
        None,
    )


def _parser_platform_for_template(profile_defs: list[dict], filename: str) -> str:
    """Return a parser family for a family-prefixed SYSTEM template."""
    profile = _profile_for_template(profile_defs, filename)
    if profile:
        return str(profile["parser_platform"])
    stem = Path(filename).stem.lower()
    parser_platforms = sorted(
        {str(item["parser_platform"]) for item in profile_defs},
        key=len,
        reverse=True,
    )
    return next(
        (parser_platform for parser_platform in parser_platforms
         if stem.startswith(f"{parser_platform.lower()}_")),
        "",
    )


def _import_scoped_file_templates(cursor, profile_ids: dict[str, str], now: str) -> None:
    from services.platform_registry_service import SYSTEM_PROFILES
    from core.textfsm import _canonical_template_command

    root = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates"
    if not root.exists():
        return

    for path in sorted(root.glob("*.textfsm"), key=lambda item: item.name.lower()):
        profile = _profile_for_template(list(SYSTEM_PROFILES), path.name)
        if not profile:
            continue
        parser_platform = str(profile["parser_platform"])
        profile_code = str(profile["platform_code"])
        profile_id = profile_ids.get(profile_code)
        if not profile_id:
            continue
        filename_stem = path.stem
        source_prefix = "hp_comware" if filename_stem.lower().startswith("hp_comware_") else profile_code
        command_part = filename_stem[len(source_prefix) + 1:].replace("_", " ")
        command = str(_canonical_template_command(parser_platform, command_part) or command_part).strip()
        template_code = re.sub(r"[^A-Z0-9_]", "_", filename_stem.upper())[:64]
        if not template_code or not re.match(r"^[A-Z]", template_code):
            continue
        content = path.read_text(encoding="utf-8")
        template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{path.name}"))
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{path.name}:1"))
        cursor.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, command, name, source, status, created_by,
                created_at, updated_at, lock_version)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE', 'system',
                       ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                 platform_profile_id=excluded.platform_profile_id,
                 platform_code=excluded.platform_code,
                 source_filename=excluded.source_filename,
                 command=excluded.command,
                 name=excluded.name,
                 updated_at=excluded.updated_at""",
            (
                template_id,
                profile_id,
                parser_platform,
                template_code,
                path.name,
                command,
                path.stem,
                now,
                now,
            ),
        )
        cursor.execute(
            """INSERT INTO parser_template_versions
               (id, template_id, version_number, status, content, checksum,
                field_contract_json, test_summary_json, created_by, created_at,
                updated_at)
               VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{"imported":true}',
                       'system', ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 content=excluded.content, checksum=excluded.checksum,
                 updated_at=excluded.updated_at""",
            (version_id, template_id, content, _checksum(content), now, now),
        )


def _scope_existing_system_templates(cursor, profile_ids: dict[str, str], now: str) -> None:
    from services.platform_registry_service import SYSTEM_PROFILES

    for row in cursor.execute(
        "SELECT id, source_filename FROM parser_templates WHERE source = 'SYSTEM' AND tenant_id IS NULL"
    ).fetchall():
        template_id, filename = str(row[0]), str(row[1] or "")
        profile = _profile_for_template(list(SYSTEM_PROFILES), filename)
        if not profile or profile["platform_code"] not in profile_ids:
            continue
        profile_id = profile_ids[str(profile["platform_code"])]
        cursor.execute(
            "UPDATE parser_templates SET platform_profile_id = ?, updated_at = ? WHERE id = ?",
            (profile_id, now, template_id),
        )


def _repair_release_parser_bindings(cursor, profile_ids: dict[str, str], now: str) -> None:
    from services.platform_registry_service import SYSTEM_PROFILES

    profiles = {str(item["platform_code"]): item for item in SYSTEM_PROFILES}
    releases = cursor.execute(
        """SELECT r.id, p.id, p.platform_code, p.parser_platform
           FROM platform_releases r JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM' AND p.tenant_id IS NULL
             AND r.status IN ('PUBLISHED', 'DRAFT', 'DEPRECATED')"""
    ).fetchall()
    for release in releases:
        release_id, profile_id, profile_code, parser_platform = map(str, release)
        profile = profiles.get(profile_code, {"platform_code": profile_code, "parser_platform": parser_platform})
        actions = cursor.execute(
            "SELECT action_code, command, parser_template_version_id, field_contract_json FROM platform_release_actions WHERE release_id = ?",
            (release_id,),
        ).fetchall()
        changed = False
        for action in actions:
            action_code, command, old_version_id, field_contract = action
            candidates = cursor.execute(
                """SELECT v.id, t.command
                   FROM parser_template_versions v
                   JOIN parser_templates t ON t.id = v.template_id
                   WHERE v.status = 'PUBLISHED' AND t.source = 'SYSTEM'
                     AND t.platform_code = ?
                     AND t.platform_profile_id = ?
                   ORDER BY v.version_number DESC, v.id""",
                (profile.get("parser_platform") or parser_platform, profile_id),
            ).fetchall()
            candidate = next((item for item in candidates if _normalize(item[1]) == _normalize(command)), None)
            candidate_id = str(candidate[0]) if candidate else None
            if str(old_version_id or "") != str(candidate_id or ""):
                cursor.execute(
                    "UPDATE platform_release_actions SET parser_template_version_id = ?, updated_at = ? WHERE release_id = ? AND action_code = ?",
                    (candidate_id, now, release_id, action_code),
                )
                changed = True
        if changed:
            refreshed = [
                dict(row)
                for row in cursor.execute(
                    "SELECT action_code, command, parser_template_version_id, field_contract_json FROM platform_release_actions WHERE release_id = ? ORDER BY action_code",
                    (release_id,),
                ).fetchall()
            ]
            cursor.execute(
                "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
                (_checksum(refreshed), now, release_id),
            )


def _repair_device_bindings(cursor, profile_ids: dict[str, str]) -> None:
    from services.platform_registry_service import PLATFORM_ALIASES

    # First repair the explicit versioned codes.  This is important for old
    # databases where hp_comware was previously collapsed into h3c_comware.
    for profile_code, profile_id in profile_ids.items():
        raw_values = {profile_code}
        raw_values.update(raw for raw, canonical in PLATFORM_ALIASES.items() if canonical == profile_code)
        for raw in raw_values:
            cursor.execute(
                """UPDATE devices SET platform_profile_id = ?, platform_source = 'SYSTEM',
                          platform_locked = COALESCE(platform_locked, 0)
                   WHERE lower(COALESCE(platform, '')) = ?
                     AND (platform_profile_id IS NULL OR platform_profile_id = ''
                          OR platform_profile_id = 'system-profile-h3c_comware')""",
                (profile_id, str(raw).lower()),
            )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    now = _now()
    profile_ids = _ensure_system_profiles(cursor, now)
    _scope_existing_system_templates(cursor, profile_ids, now)
    _import_scoped_file_templates(cursor, profile_ids, now)
    _scope_existing_system_templates(cursor, profile_ids, now)
    _repair_release_parser_bindings(cursor, profile_ids, now)
    _repair_device_bindings(cursor, profile_ids)
