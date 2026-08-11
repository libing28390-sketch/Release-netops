"""Register runtime NTC TextFSM templates in the versioned parser registry.

The parser runtime has always been able to see ``ntc_templates`` files, but
the platform registry only imported files from ``data/textfsm_templates``.
That made a built-in parser visible in the parser browser while its matching
platform action still appeared unbound.  This migration makes the registry
the same source of truth for supported system platforms and binds only exact
command matches.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


VERSION = 100
NAME = "register_builtin_textfsm_templates"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_command(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _template_code(filename: str) -> str:
    stem = Path(filename).stem
    return "".join(char if char.isalnum() or char == "_" else "_" for char in stem.upper())[:64]


def _resolve_template_code(cursor, platform: str, code: str, template_id: str, filename: str) -> str:
    """Keep legacy file imports and hyphenated NTC names uniquely addressable."""
    imported = cursor.execute(
        "SELECT template_code FROM parser_templates WHERE id = ? AND tenant_id IS NULL",
        (template_id,),
    ).fetchone()
    if imported:
        return str(imported[0])
    existing = cursor.execute(
        """SELECT id FROM parser_templates
           WHERE tenant_id IS NULL AND platform_code = ? AND template_code = ?""",
        (platform, code),
    ).fetchone()
    if not existing or str(existing[0]) == template_id:
        return code

    suffix = _checksum(filename)[:8].upper()
    candidate = f"{code[:max(1, 64 - len(suffix) - 1)]}_{suffix}"
    while cursor.execute(
        """SELECT 1 FROM parser_templates
           WHERE tenant_id IS NULL AND platform_code = ? AND template_code = ?""",
        (platform, candidate),
    ).fetchone():
        suffix = _checksum(f"{filename}:{candidate}")[:8].upper()
        candidate = f"{code[:max(1, 64 - len(suffix) - 1)]}_{suffix}"
    return candidate


def _iter_builtin_templates(profile_defs):
    """Yield effective runtime templates, packaged files taking precedence."""
    from core.textfsm import _get_builtin_templates_dir, _get_packaged_templates_dir

    roots: list[Path] = []
    packaged = _get_packaged_templates_dir()
    builtin = _get_builtin_templates_dir()
    if packaged:
        roots.append(packaged)
    if builtin and builtin not in roots:
        roots.append(builtin)

    profile_defs = sorted(profile_defs, key=lambda item: len(str(item["platform_code"])), reverse=True)
    seen_filenames: set[str] = set()
    for root in roots:
        for path in sorted(root.glob("*.textfsm"), key=lambda item: item.name.lower()):
            if path.name in seen_filenames:
                continue
            seen_filenames.add(path.name)
            filename = path.name
            stem = path.stem.lower()
            # H3C's public parser family is shared, but variant filenames must
            # be assigned to their concrete grammar Profile before the generic
            # ``h3c_comware_`` prefix is considered.
            variant_profile_code = None
            command_prefix = ""
            for variant_prefix, profile_code in (
                ("h3c_comware_v5", "hp_comware"),
                ("h3c_comware_v9", "h3c_comware9"),
            ):
                if stem.startswith(f"{variant_prefix}_"):
                    variant_profile_code = profile_code
                    command_prefix = variant_prefix
                    break
            profile = next(
                (candidate for candidate in profile_defs
                 if variant_profile_code
                 and str(candidate["platform_code"]).lower() == variant_profile_code),
                None,
            )
            if not profile:
                profile = next(
                    (candidate for candidate in profile_defs
                     if stem.startswith(f"{str(candidate['platform_code']).lower()}_")),
                    None,
                )
            if profile:
                if not command_prefix:
                    command_prefix = str(profile["platform_code"])
            else:
                # Several concrete Profiles may intentionally share one
                # parser family (for example Ruijie or ZTE).  Family-prefixed
                # SYSTEM templates are global so each Profile can bind the
                # same template by its exact command without assigning the
                # template to whichever Profile is listed first.
                parser_platform = next(
                    (str(candidate["parser_platform"])
                     for candidate in profile_defs
                     if stem.startswith(f"{str(candidate['parser_platform']).lower()}_")),
                    "",
                )
                if not parser_platform:
                    continue
                profile = {"platform_code": "", "parser_platform": parser_platform}
                command_prefix = parser_platform
            profile_code = str(profile["platform_code"])
            parser_platform = str(profile["parser_platform"])
            command_part = path.stem[len(command_prefix) + 1:].replace("_", " ")
            try:
                from core.textfsm import _canonical_template_command
                command = str(_canonical_template_command(parser_platform, command_part) or "").strip()
            except Exception:
                command = command_part.strip()
            if not command:
                continue
            code = _template_code(filename)
            if not code or not code[0].isalpha():
                continue
            yield profile_code, parser_platform, command, code, path


def _refresh_release_checksum(cursor, release_id: str, now: str) -> None:
    actions = [
        dict(row)
        for row in cursor.execute(
            """SELECT action_code, command, parser_template_version_id, field_contract_json
               FROM platform_release_actions WHERE release_id = ? ORDER BY action_code""",
            (release_id,),
        ).fetchall()
    ]
    cursor.execute(
        "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
        (_checksum(actions), now, release_id),
    )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg  # SQL uses the migration adapter's portable '?' placeholders.
    from services.platform_registry_service import SYSTEM_PROFILES

    supported_profile_codes = {str(item["platform_code"]) for item in SYSTEM_PROFILES}
    profiles = {
        str(row[1]): str(row[0])
        for row in cursor.execute(
            """SELECT id, platform_code FROM platform_profiles
               WHERE source = 'SYSTEM' AND tenant_id IS NULL
               ORDER BY id"""
        ).fetchall()
        if str(row[1]) in supported_profile_codes
    }
    if not profiles:
        return

    now = _now()
    command_versions: dict[tuple[str, str], str] = {}
    for profile_code, parser_platform, command, template_code, path in _iter_builtin_templates(SYSTEM_PROFILES):
        profile_id = profiles.get(profile_code)
        if profile_code and not profile_id:
            continue
        content = path.read_text(encoding="utf-8")
        template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{path.name}"))
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{path.name}:1"))
        template_code = _resolve_template_code(cursor, parser_platform, template_code, template_id, path.name)
        cursor.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, command, name, source, status, created_by,
                created_at, updated_at, lock_version)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE',
                       'system', ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                 -- m0102 may have already split a family template into
                 -- concrete Profile rows.  Re-running this legacy importer
                 -- must not collapse that scope back to NULL.
                 platform_profile_id=COALESCE(parser_templates.platform_profile_id, excluded.platform_profile_id),
                 platform_code=excluded.platform_code,
                 source_filename=CASE WHEN parser_templates.platform_profile_id IS NULL THEN excluded.source_filename ELSE parser_templates.source_filename END,
                 template_code=CASE WHEN parser_templates.platform_profile_id IS NULL THEN excluded.template_code ELSE parser_templates.template_code END,
                 command=excluded.command,
                 name=CASE WHEN parser_templates.platform_profile_id IS NULL THEN excluded.name ELSE parser_templates.name END,
                 updated_at=excluded.updated_at""",
            (
                template_id,
                profile_id or None,
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
                field_contract_json, test_summary_json, created_by, created_at, updated_at)
               VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{\"imported\":true}',
                       'system', ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 content=excluded.content, checksum=excluded.checksum,
                 updated_at=excluded.updated_at""",
            (version_id, template_id, content, _checksum(content), now, now),
        )
        command_versions.setdefault((str(profile_id or ""), _normalize_command(command)), version_id)

    changed_release_ids: set[str] = set()
    releases = cursor.execute(
        """SELECT r.id, p.id
           FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM' AND p.tenant_id IS NULL
             AND r.status IN ('PUBLISHED', 'DRAFT')"""
    ).fetchall()
    for release in releases:
        release_id = str(release[0])
        profile_id = str(release[1])
        actions = cursor.execute(
            """SELECT action_code, command, parser_template_version_id
               FROM platform_release_actions WHERE release_id = ?""",
            (release_id,),
        ).fetchall()
        changed = False
        for action in actions:
            if action[2]:
                continue
            normalized_command = _normalize_command(action[1])
            version_id = command_versions.get((profile_id, normalized_command))
            if not version_id:
                version_id = command_versions.get(("", normalized_command))
            if not version_id:
                continue
            cursor.execute(
                """UPDATE platform_release_actions
                   SET parser_template_version_id = ?, updated_at = ?
                   WHERE release_id = ? AND action_code = ?
                     AND (parser_template_version_id IS NULL OR parser_template_version_id = '')""",
                (version_id, now, release_id, action[0]),
            )
            changed = True
        if changed:
            changed_release_ids.add(release_id)

    for release_id in changed_release_ids:
        _refresh_release_checksum(cursor, release_id, now)
