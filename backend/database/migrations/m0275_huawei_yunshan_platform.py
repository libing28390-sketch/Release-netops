"""Register the independent Huawei YunShan profile and its six parsers.

YunShan uses the Huawei VRP connection driver for transport only. Its release
actions and parser templates remain scoped to the ``huawei_yunshan`` profile.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


VERSION = 275
NAME = "huawei_yunshan_platform"

PROFILE_CODE = "huawei_yunshan"
PROFILE_ID = "system-profile-huawei_yunshan"
RELEASE_ID = "system-release-huawei_yunshan-v1"
CONNECTION_DRIVER = "huawei_vrp"
PARSER_PLATFORM = "huawei_yunshan"

TEMPLATES = {
    "huawei_yunshan_display_version.textfsm": ("get_version", "display version"),
    "huawei_yunshan_display_interface_brief.textfsm": ("get_interface_brief", "display interface brief"),
    "huawei_yunshan_display_ip_interface_brief.textfsm": ("get_ip_interfaces", "display ip interface brief"),
    "huawei_yunshan_display_lldp_neighbor_brief.textfsm": ("get_lldp_neighbors", "display lldp neighbor brief"),
    "huawei_yunshan_display_arp.textfsm": ("get_arp_table", "display arp"),
    "huawei_yunshan_display_mac_address.textfsm": ("get_mac_table", "display mac-address"),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _checksum(value: str | list | dict) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _resolve_template_root(project_root: Path | None = None) -> Path:
    """Find a complete immutable template set in Docker or source layouts.

    Docker keeps release-owned templates outside the persistent ``/app/data``
    volume. In a source checkout, they remain under ``data/textfsm_templates``.
    Require the full migration set before choosing either directory so an empty
    or user-populated volume cannot shadow the image's reviewed templates.
    """
    root = project_root or Path(__file__).resolve().parents[3]
    candidates = (
        root / "release-textfsm-templates",
        root / "data" / "textfsm_templates",
    )
    expected = tuple(TEMPLATES)
    for candidate in candidates:
        if all((candidate / filename).is_file() for filename in expected):
            return candidate

    missing = {
        str(candidate): [filename for filename in expected if not (candidate / filename).is_file()]
        for candidate in candidates
    }
    missing_summary = "; ".join(
        f"{candidate}: {', '.join(filenames) or '(none)'}"
        for candidate, filenames in missing.items()
    )
    raise RuntimeError(
        "Required YunShan TextFSM templates are missing from packaged and source directories: "
        f"{missing_summary}"
    )


def _ensure_action_definitions(cursor, now: str) -> None:
    from services.platform_registry_service import iter_action_definitions

    wanted = {action_code for action_code, _command in TEMPLATES.values()}
    for definition in iter_action_definitions():
        if definition.get("action_code") not in wanted:
            continue
        cursor.execute(
            """INSERT INTO action_definitions (
                 action_code, name_zh, name_en, purpose, risk_level,
                 device_types_json, required_fields_json, optional_fields_json,
                 field_types_json, max_output_bytes, max_records, timeout_seconds,
                 sensitive_level, consumers_json, read_only, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(action_code) DO NOTHING""",
            (
                definition["action_code"], definition.get("name_zh", ""),
                definition.get("name_en", ""), definition.get("purpose", ""),
                definition.get("risk", "low"), _json(definition.get("device_types") or []),
                _json(definition.get("fields") or []), _json(definition.get("optional_fields") or []),
                _json(definition.get("field_types") or {}), 2_000_000,
                int(definition.get("max_records") or 1000),
                int(definition.get("timeout_seconds") or 30),
                "sensitive" if definition.get("risk") == "sensitive" else "normal",
                _json(definition.get("consumers") or []), now,
            ),
        )


def _ensure_profile_and_release(cursor, now: str) -> tuple[str, str]:
    profile_row = cursor.execute(
        """SELECT id FROM platform_profiles
           WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = ?""",
        (PROFILE_CODE,),
    ).fetchone()
    profile_id = str(profile_row[0]) if profile_row else PROFILE_ID
    cursor.execute(
        """INSERT INTO platform_profiles
           (id, tenant_id, platform_code, name_zh, name_en, vendor,
            connection_driver, parser_platform, source, status, description,
            created_by, created_at, updated_at, lock_version)
           VALUES (?, NULL, ?, ?, ?, 'Huawei', ?, ?, 'SYSTEM', 'ACTIVE',
                   'Huawei YunShan OS; Huawei VRP connection driver is used for transport only.',
                   'system', ?, ?, 1)
           ON CONFLICT(id) DO UPDATE SET
             platform_code = excluded.platform_code,
             name_zh = excluded.name_zh,
             name_en = excluded.name_en,
             vendor = excluded.vendor,
             connection_driver = excluded.connection_driver,
             parser_platform = excluded.parser_platform,
             status = 'ACTIVE', updated_at = excluded.updated_at""",
        (profile_id, PROFILE_CODE, "华为 YunShan OS", "Huawei YunShan OS", CONNECTION_DRIVER, PARSER_PLATFORM, now, now),
    )
    cursor.execute(
        """INSERT INTO platform_releases
           (id, profile_id, release_number, status, connection_driver,
            parser_platform, safety_policy_json, checksum, validation_status,
            validation_result_json, created_by, approved_by, published_by,
            created_at, updated_at, lock_version)
           VALUES (?, ?, 1, 'PUBLISHED', ?, ?, ?, ?, 'PASSED',
                   '{"seed":true}', 'system', 'system', 'system', ?, ?, 1)
           ON CONFLICT(profile_id, release_number) DO UPDATE SET
             connection_driver = excluded.connection_driver,
             parser_platform = excluded.parser_platform,
             status = 'PUBLISHED',
             safety_policy_json = excluded.safety_policy_json,
             validation_status = 'PASSED',
             validation_result_json = excluded.validation_result_json,
             updated_at = excluded.updated_at""",
        (
            RELEASE_ID, profile_id, CONNECTION_DRIVER, PARSER_PLATFORM,
            json.dumps({"read_only": True, "allowed_prefixes": ["display", "show"]}, sort_keys=True),
            _checksum(f"{PROFILE_CODE}:1"), now, now,
        ),
    )
    release_row = cursor.execute(
        "SELECT id FROM platform_releases WHERE profile_id = ? AND release_number = 1",
        (profile_id,),
    ).fetchone()
    if not release_row:
        raise RuntimeError("YunShan system release was not materialized")
    release_id = str(release_row[0])
    cursor.execute("UPDATE platform_profiles SET current_release_id = ?, updated_at = ? WHERE id = ?", (release_id, now, profile_id))
    return profile_id, release_id


def _register_templates(
    cursor,
    profile_id: str,
    now: str,
    root: Path,
) -> dict[str, str]:
    versions: dict[str, str] = {}
    for filename, (action_code, command) in TEMPLATES.items():
        path = root / filename
        if not path.is_file():
            raise RuntimeError(f"Required YunShan TextFSM template is missing: {filename}")
        content = path.read_text(encoding="utf-8")
        declared = re.search(r"(?m)^\s*#\s*nexora-action-code\s*:\s*([a-z][a-z0-9_]*)\s*$", content)
        if not declared or declared.group(1) != action_code:
            raise RuntimeError(f"YunShan template action metadata does not match: {filename}")

        template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{filename}"))
        existing = cursor.execute(
            """SELECT id FROM parser_templates
               WHERE tenant_id IS NULL AND source = 'SYSTEM'
                 AND platform_profile_id = ? AND source_filename = ?""",
            (profile_id, filename),
        ).fetchone()
        if existing:
            template_id = str(existing[0])
            cursor.execute(
                """UPDATE parser_templates
                   SET platform_code = ?, template_code = ?, command = ?, name = ?,
                       status = 'ACTIVE', updated_at = ?
                   WHERE id = ? AND tenant_id IS NULL AND source = 'SYSTEM'
                     AND platform_profile_id = ?""",
                (PARSER_PLATFORM, filename[:-len(".textfsm")].upper()[:64], command, path.stem, now, template_id, profile_id),
            )
        else:
            cursor.execute(
                """INSERT INTO parser_templates
                   (id, tenant_id, platform_profile_id, platform_code, template_code,
                    source_filename, command, name, source, status, created_by,
                    created_at, updated_at, lock_version)
                   VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE', 'system', ?, ?, 1)""",
                (
                    template_id, profile_id, PARSER_PLATFORM,
                    filename[:-len(".textfsm")].upper()[:64], filename, command,
                    path.stem, now, now,
                ),
            )

        version_row = cursor.execute(
            "SELECT id FROM parser_template_versions WHERE template_id = ? AND version_number = 1",
            (template_id,),
        ).fetchone()
        version_id = str(version_row[0]) if version_row else str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{filename}:1")
        )
        cursor.execute(
            """INSERT INTO parser_template_versions
               (id, template_id, version_number, status, content, checksum,
                field_contract_json, test_summary_json, created_by, created_at, updated_at)
               VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{"imported":true}', 'system', ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 template_id = excluded.template_id,
                 status = 'PUBLISHED', content = excluded.content,
                 checksum = excluded.checksum, updated_at = excluded.updated_at""",
            (version_id, template_id, content, _checksum(content), now, now),
        )
        versions[action_code] = version_id
    return versions


def _bind_actions(cursor, release_id: str, versions: dict[str, str], now: str) -> None:
    from services.platform_registry_service import iter_action_definitions

    definitions = {item["action_code"] for item in iter_action_definitions()}
    for filename, (action_code, command) in TEMPLATES.items():
        if action_code not in definitions:
            raise RuntimeError(f"YunShan action definition is missing: {action_code}")
        action_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}"))
        cursor.execute(
            """INSERT INTO platform_release_actions
               (id, release_id, action_code, command, parser_template_version_id,
                field_contract_json, command_checksum, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?)
               ON CONFLICT(release_id, action_code) DO UPDATE SET
                 command = excluded.command,
                 parser_template_version_id = excluded.parser_template_version_id,
                 command_checksum = excluded.command_checksum,
                 updated_at = excluded.updated_at""",
            (action_id, release_id, action_code, command, versions[action_code], _checksum(command), now, now),
        )

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


def _ensure_identification_rule(cursor, profile_id: str, now: str) -> None:
    rule_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:identification:{PROFILE_CODE}:YunShan OS"))
    cursor.execute(
        """INSERT INTO platform_identification_rules
           (id, platform_profile_id, command, match_type, pattern, logic_group,
            rule_order, confidence, negate, enabled, created_at)
           VALUES (?, ?, 'display version', 'contains', 'YunShan OS', 'ANY', 1, 0.99, 0, 1, ?)
           ON CONFLICT(id) DO UPDATE SET
             platform_profile_id = excluded.platform_profile_id,
             command = excluded.command,
             match_type = excluded.match_type,
             pattern = excluded.pattern,
             logic_group = excluded.logic_group,
             rule_order = excluded.rule_order,
             confidence = excluded.confidence,
             negate = excluded.negate,
             enabled = excluded.enabled""",
        (rule_id, profile_id, now),
    )


def upgrade(cursor, use_pg: bool) -> None:
    if not use_pg:
        raise RuntimeError("Huawei YunShan platform registration requires PostgreSQL")

    # Validate deployment assets before writing any rows. This also resolves
    # the distinct immutable-template path used by Docker images.
    template_root = _resolve_template_root()
    now = _now()
    _ensure_action_definitions(cursor, now)
    profile_id, release_id = _ensure_profile_and_release(cursor, now)
    versions = _register_templates(cursor, profile_id, now, template_root)
    _bind_actions(cursor, release_id, versions, now)
    _ensure_identification_rule(cursor, profile_id, now)


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
