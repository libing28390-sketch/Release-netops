"""Scope every built-in parser template to one concrete system Profile.

The parser namespace and the connection driver may be shared by several
products from one vendor, but a published TextFSM binding belongs to one
concrete platform Profile.  This migration duplicates family-prefixed SYSTEM
templates for every matching concrete Profile and repairs Release bindings by
exact Profile + command.  Tenant-owned templates are deliberately untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


VERSION = 102
NAME = "concrete_system_template_scopes"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _profile_for_template(profile_defs: list[dict], filename: str) -> dict | None:
    stem = Path(filename).stem.lower()
    # The historical unicast file is the V7 grammar despite its hp_comware
    # parser-family filename.
    if stem == "hp_comware_display_bgp_peer_ipv4_unicast":
        return next((item for item in profile_defs if item["platform_code"] == "h3c_comware"), None)
    return next(
        (
            item
            for item in sorted(profile_defs, key=lambda item: len(str(item["platform_code"])), reverse=True)
            if stem.startswith(f"{str(item['platform_code']).lower()}_")
        ),
        None,
    )


def _target_profiles(profile_defs: list[dict], platform_code: str, filename: str) -> list[dict]:
    concrete = _profile_for_template(profile_defs, filename)
    if concrete:
        return [concrete]
    parser_platform = str(platform_code or "").strip().lower()
    return [
        item for item in profile_defs
        if str(item.get("parser_platform") or "").strip().lower() == parser_platform
    ]


def _scoped_identity(profile_code: str, source_filename: str) -> tuple[str, str, str]:
    """Give every concrete system template a visibly distinct registry name."""
    filename = Path(str(source_filename or "")).name
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".textfsm"
    if stem.lower().startswith(f"{profile_code.lower()}_"):
        scoped_stem = stem
    else:
        scoped_stem = f"{profile_code}__{stem}"
    scoped_filename = f"{scoped_stem}{suffix}"
    code = "".join(char if char.isalnum() or char == "_" else "_" for char in scoped_stem.upper())
    # The legacy registry sanitizer converts punctuation to underscores.  A
    # filename such as ``bash_df_-h`` could therefore collide with another
    # filename after sanitization.  Keep the human-readable prefix, but add a
    # deterministic suffix whenever the original stem is not already a safe
    # registry identifier (or when the 64-character limit requires trimming).
    if len(code) > 64 or re.search(r"[^A-Za-z0-9_]", stem):
        digest = _checksum(f"{profile_code}:{filename}")[:8].upper()
        code = f"{code[:55]}_{digest}"
    return scoped_filename, code, scoped_stem


def _allocate_scoped_identity(
    cursor,
    profile_id: str,
    profile_code: str,
    parser_platform: str,
    source_filename: str,
) -> tuple[str, str, str]:
    """Avoid collisions with rows imported by an older migration.

    The source filename is the stable human-facing identity, while the
    database also has to accept legacy rows whose sanitized code was already
    allocated.  If another SYSTEM row in this concrete Profile owns the
    desired code, retain the readable prefix and add a deterministic suffix.
    """
    scoped_filename, scoped_code, scoped_name = _scoped_identity(profile_code, source_filename)
    conflict_rows = cursor.execute(
        """SELECT source_filename
           FROM parser_templates
           WHERE tenant_id IS NULL AND source = 'SYSTEM'
             AND platform_profile_id = ? AND platform_code = ?
             AND template_code = ?""",
        (profile_id, parser_platform, scoped_code),
    ).fetchall()
    if not conflict_rows or any(
        str(row[0] or "").lower() == scoped_filename.lower() for row in conflict_rows
    ):
        return scoped_filename, scoped_code, scoped_name

    digest = _checksum(f"{profile_code}:{source_filename}")[:8].upper()
    base = scoped_code[:55]
    candidate = f"{base}_{digest}"
    counter = 0
    while cursor.execute(
        """SELECT 1
           FROM parser_templates
           WHERE tenant_id IS NULL AND source = 'SYSTEM'
             AND platform_profile_id = ? AND platform_code = ?
             AND template_code = ?""",
        (profile_id, parser_platform, candidate),
    ).fetchone():
        counter += 1
        digest = _checksum(f"{profile_code}:{source_filename}:{counter}")[:8].upper()
        candidate = f"{base}_{digest}"
    return scoped_filename, candidate, scoped_name


def _drop_global_system_template_index(cursor) -> None:
    # The old index ignored platform_profile_id, which made it impossible to
    # store one family template per concrete Profile.
    cursor.execute("DROP INDEX IF EXISTS uq_parser_templates_system_code")
    cursor.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_parser_templates_system_profile_code
           ON parser_templates(platform_code, COALESCE(platform_profile_id, ''), template_code)
           WHERE tenant_id IS NULL"""
    )


def _copy_versions(cursor, source_template_id: str, target_template_id: str, profile_code: str, now: str) -> None:
    versions = cursor.execute(
        """SELECT version_number, status, content, checksum, field_contract_json,
                  test_summary_json, created_by, created_at, updated_at
           FROM parser_template_versions
           WHERE template_id = ? ORDER BY version_number""",
        (source_template_id,),
    ).fetchall()
    for version in versions:
        version_number = int(version[0])
        version_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"nexora:system-template-version:{target_template_id}:{profile_code}:{version_number}",
            )
        )
        cursor.execute(
            """INSERT INTO parser_template_versions
               (id, template_id, version_number, status, content, checksum,
                field_contract_json, test_summary_json, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 template_id=excluded.template_id,
                 version_number=excluded.version_number,
                 status=excluded.status,
                 content=excluded.content,
                 checksum=excluded.checksum,
                 field_contract_json=excluded.field_contract_json,
                 test_summary_json=excluded.test_summary_json,
                 updated_at=excluded.updated_at""",
            (
                version_id,
                target_template_id,
                version_number,
                version[1],
                version[2],
                version[3],
                version[4],
                version[5],
                version[6],
                version[7],
                now,
            ),
        )


def _import_family_file_templates(cursor, profile_defs: list[dict], now: str) -> None:
    """Bring release-owned family templates into the migration input set.

    m0101 deliberately imports only files whose names already contain a
    concrete Profile code.  Files such as ``zte_zxros_*`` and
    ``ruijie_rgos_*`` are parser-family files, so import them once as a
    temporary SYSTEM row and let this migration duplicate them into every
    concrete Profile that uses that parser family.
    """
    from core.textfsm import _canonical_template_command

    root = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates"
    if not root.exists():
        return
    parser_platforms = sorted(
        {str(item.get("parser_platform") or "").strip() for item in profile_defs},
        key=len,
        reverse=True,
    )
    for path in sorted(root.glob("*.textfsm"), key=lambda item: item.name.lower()):
        if _profile_for_template(profile_defs, path.name):
            continue
        stem = path.stem
        parser_platform = next(
            (
                parser
                for parser in parser_platforms
                if stem.lower().startswith(f"{parser.lower()}_")
            ),
            "",
        )
        if not parser_platform:
            continue
        command_part = stem[len(parser_platform) + 1 :].replace("_", " ")
        command = str(_canonical_template_command(parser_platform, command_part) or command_part).strip()
        if not command:
            continue
        content = path.read_text(encoding="utf-8")
        template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{path.name}"))
        template_code = re.sub(r"[^A-Z0-9_]", "_", stem.upper())[:64]
        if not template_code or not re.match(r"^[A-Z]", template_code):
            continue
        existing = cursor.execute(
            """SELECT id
               FROM parser_templates
               WHERE tenant_id IS NULL AND platform_code = ?
                 AND template_code = ? AND id <> ?""",
            (parser_platform, template_code, template_id),
        ).fetchone()
        if existing:
            digest = _checksum(path.name)[:8].upper()
            template_code = f"{template_code[:55]}_{digest}"
        cursor.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, command, name, source, status, created_by,
                created_at, updated_at, lock_version)
               VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE',
                       'system', ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET
                 platform_code=excluded.platform_code,
                 platform_profile_id=COALESCE(parser_templates.platform_profile_id,
                                              excluded.platform_profile_id),
                 source_filename=CASE WHEN parser_templates.platform_profile_id IS NULL
                                      THEN excluded.source_filename
                                      ELSE parser_templates.source_filename END,
                 template_code=CASE WHEN parser_templates.platform_profile_id IS NULL
                                    THEN excluded.template_code
                                    ELSE parser_templates.template_code END,
                 command=excluded.command,
                 name=CASE WHEN parser_templates.platform_profile_id IS NULL
                           THEN excluded.name ELSE parser_templates.name END,
                 updated_at=excluded.updated_at""",
            (
                template_id,
                parser_platform,
                template_code,
                path.name,
                command,
                path.stem,
                now,
                now,
            ),
        )
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{path.name}:1"))
        cursor.execute(
            """INSERT INTO parser_template_versions
               (id, template_id, version_number, status, content, checksum,
                field_contract_json, test_summary_json, created_by, created_at,
                updated_at)
               VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{\"imported\":true}',
                       'system', ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 content=excluded.content, checksum=excluded.checksum,
                 updated_at=excluded.updated_at""",
            (version_id, template_id, content, _checksum(content), now, now),
        )


def _scope_templates(cursor, profile_defs: list[dict], profile_ids: dict[str, str], now: str) -> None:
    rows = cursor.execute(
        """SELECT id, platform_profile_id, platform_code, template_code,
                  source_filename, name, source, status, created_by,
                  created_at, updated_at, lock_version, command
           FROM parser_templates
           WHERE tenant_id IS NULL AND source = 'SYSTEM'
           ORDER BY source_filename, id"""
    ).fetchall()
    groups: dict[tuple[str, str, str], list[tuple]] = {}
    for row in rows:
        key = (str(row[4] or "").lower(), str(row[2] or "").lower(), str(row[3] or ""))
        groups.setdefault(key, []).append(row)

    for (_filename, _parser_platform, _template_code), group in groups.items():
        source_row = group[0]
        targets = _target_profiles(profile_defs, source_row[2], source_row[4])
        target_codes = {str(item["platform_code"]) for item in targets}
        if not targets:
            continue

        existing_by_profile = {
            str(row[1]): row for row in group if row[1] and str(row[1]) in target_codes
        }
        unscoped = next((row for row in group if not row[1]), None)
        unscoped_used = False

        for target in targets:
            profile_code = str(target["platform_code"])
            profile_id = profile_ids.get(profile_code)
            if not profile_id:
                continue
            scoped_filename, scoped_code, scoped_name = _allocate_scoped_identity(
                cursor,
                profile_id,
                profile_code,
                str(source_row[2]),
                str(source_row[4] or ""),
            )
            existing = existing_by_profile.get(profile_id)
            if not existing:
                # Older migrations may have registered the same source file
                # with a different sanitized code.  Reuse that row instead of
                # creating a second row that violates the new Profile-scoped
                # uniqueness key.
                existing = cursor.execute(
                    """SELECT id, platform_profile_id
                       FROM parser_templates
                       WHERE tenant_id IS NULL AND source = 'SYSTEM'
                         AND platform_code = ?
                         AND (platform_profile_id = ? OR platform_profile_id IS NULL)
                         AND lower(COALESCE(source_filename, '')) IN (lower(?), lower(?))
                       ORDER BY CASE WHEN platform_profile_id = ? THEN 0 ELSE 1 END, id
                       LIMIT 1""",
                    (
                        str(source_row[2]),
                        profile_id,
                        str(source_row[4] or ""),
                        scoped_filename,
                        profile_id,
                    ),
                ).fetchone()
            if existing:
                cursor.execute(
                    """UPDATE parser_templates
                       SET platform_profile_id = ?, source_filename = ?,
                           template_code = ?, name = ?, command = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        profile_id,
                        scoped_filename,
                        scoped_code,
                        scoped_name,
                        source_row[12],
                        now,
                        existing[0],
                    ),
                )
                if not existing[1] and unscoped is not None and existing[0] == unscoped[0]:
                    unscoped_used = True
                continue

            if unscoped is not None and not unscoped_used:
                cursor.execute(
                    """UPDATE parser_templates
                       SET platform_profile_id = ?, source_filename = ?,
                           template_code = ?, name = ?, command = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        profile_id,
                        scoped_filename,
                        scoped_code,
                        scoped_name,
                        source_row[12],
                        now,
                        unscoped[0],
                    ),
                )
                existing_by_profile[profile_id] = (*unscoped[:1], profile_id, *unscoped[2:])
                unscoped_used = True
                continue

            target_template_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"nexora:system-template:{source_row[4]}:{source_row[3]}:{profile_code}",
                )
            )
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
                     status=excluded.status,
                     updated_at=excluded.updated_at""",
                (
                    target_template_id,
                    profile_id,
                    source_row[2],
                    scoped_code,
                    scoped_filename,
                    source_row[12],
                    scoped_name,
                    source_row[7],
                    source_row[8],
                    source_row[9] or now,
                    now,
                    source_row[11] or 1,
                ),
            )
            _copy_versions(cursor, str(source_row[0]), target_template_id, profile_code, now)


def _repair_release_bindings(cursor, profile_defs: list[dict], profile_ids: dict[str, str], now: str) -> None:
    profile_by_code = {str(item["platform_code"]): item for item in profile_defs}
    releases = cursor.execute(
        """SELECT r.id, p.id, p.platform_code, p.parser_platform
           FROM platform_releases r
           JOIN platform_profiles p ON p.id = r.profile_id
           WHERE p.source = 'SYSTEM' AND p.tenant_id IS NULL
             AND r.status IN ('PUBLISHED', 'DRAFT', 'DEPRECATED')"""
    ).fetchall()
    for release in releases:
        release_id, profile_id, profile_code, parser_platform = map(str, release)
        profile = profile_by_code.get(profile_code, {"parser_platform": parser_platform})
        actions = cursor.execute(
            """SELECT action_code, command, parser_template_version_id,
                      field_contract_json
               FROM platform_release_actions WHERE release_id = ?""",
            (release_id,),
        ).fetchall()
        changed = False
        for action in actions:
            candidates = cursor.execute(
                """SELECT v.id, t.command
                   FROM parser_template_versions v
                   JOIN parser_templates t ON t.id = v.template_id
                   WHERE v.status = 'PUBLISHED' AND t.source = 'SYSTEM'
                     AND t.platform_code = ? AND t.platform_profile_id = ?
                   ORDER BY v.version_number DESC, v.id""",
                (profile.get("parser_platform") or parser_platform, profile_id),
            ).fetchall()
            candidate = next(
                (item for item in candidates if _normalize(item[1]) == _normalize(action[1])),
                None,
            )
            candidate_id = str(candidate[0]) if candidate else None
            if str(action[2] or "") != str(candidate_id or ""):
                cursor.execute(
                    """UPDATE platform_release_actions
                       SET parser_template_version_id = ?, updated_at = ?
                       WHERE release_id = ? AND action_code = ?""",
                    (candidate_id, now, release_id, action[0]),
                )
                changed = True
        if changed:
            actions_after = [
                dict(row) for row in cursor.execute(
                    """SELECT action_code, command, parser_template_version_id,
                              field_contract_json
                       FROM platform_release_actions
                       WHERE release_id = ? ORDER BY action_code""",
                    (release_id,),
                ).fetchall()
            ]
            cursor.execute(
                "UPDATE platform_releases SET checksum = ?, updated_at = ? WHERE id = ?",
                (_checksum(actions_after), now, release_id),
            )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    from services.platform_registry_service import SYSTEM_PROFILES

    now = _now()
    profile_defs = list(SYSTEM_PROFILES)
    profile_ids = {
        str(row[1]): str(row[0])
        for row in cursor.execute(
            """SELECT id, platform_code FROM platform_profiles
               WHERE source = 'SYSTEM' AND tenant_id IS NULL"""
        ).fetchall()
    }
    if not profile_ids:
        return
    _drop_global_system_template_index(cursor)
    _import_family_file_templates(cursor, profile_defs, now)
    _scope_templates(cursor, profile_defs, profile_ids, now)
    _repair_release_bindings(cursor, profile_defs, profile_ids, now)
