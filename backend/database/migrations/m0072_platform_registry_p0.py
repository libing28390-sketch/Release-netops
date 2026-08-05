"""P0 platform registry, immutable releases, action catalog and parser versions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from datetime import datetime, timezone


VERSION = 72
NAME = "platform_registry_p0"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _columns(cursor, table: str, use_pg: bool) -> set[str]:
    if use_pg:
        rows = cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchall()
        return {str(row[0]).lower() for row in rows}
    return {str(row[1]).lower() for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(cursor, table: str, column: str, definition: str, use_pg: bool) -> None:
    if column not in _columns(cursor, table, use_pg):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _json(value) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _create_tables(cursor, use_pg: bool) -> None:
    code_check = "platform_code ~ '^[a-z][a-z0-9_]{2,63}$'" if use_pg else "platform_code NOT GLOB '*[^a-z0-9_]*' AND platform_code GLOB '[a-z]*' AND length(platform_code) BETWEEN 3 AND 64"
    template_check = "template_code ~ '^[A-Z][A-Z0-9_]{0,63}$'" if use_pg else "template_code NOT GLOB '*[^A-Z0-9_]*' AND template_code GLOB '[A-Z]*' AND length(template_code) BETWEEN 1 AND 64"
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS platform_profiles (
            id TEXT PRIMARY KEY, tenant_id TEXT, platform_code TEXT NOT NULL,
            name_zh TEXT NOT NULL DEFAULT '', name_en TEXT NOT NULL DEFAULT '', vendor TEXT NOT NULL DEFAULT '',
            connection_driver TEXT NOT NULL, parser_platform TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'CUSTOM',
            status TEXT NOT NULL DEFAULT 'ACTIVE', description TEXT DEFAULT '', current_release_id TEXT,
            created_by TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, lock_version INTEGER NOT NULL DEFAULT 1,
            CHECK ({code_check}), CHECK (source IN ('SYSTEM', 'CUSTOM', 'FORKED'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS platform_releases (
            id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, release_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'DRAFT', connection_driver TEXT NOT NULL, parser_platform TEXT NOT NULL,
            safety_policy_json TEXT NOT NULL DEFAULT '{}', checksum TEXT NOT NULL DEFAULT '', validation_status TEXT NOT NULL DEFAULT 'PENDING',
            validation_result_json TEXT NOT NULL DEFAULT '{}', created_by TEXT DEFAULT '', submitted_by TEXT DEFAULT '', approved_by TEXT DEFAULT '', published_by TEXT DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, lock_version INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (profile_id) REFERENCES platform_profiles(id) ON DELETE CASCADE,
            UNIQUE (profile_id, release_number)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS action_definitions (
            action_code TEXT PRIMARY KEY, name_zh TEXT NOT NULL, name_en TEXT NOT NULL, purpose TEXT NOT NULL DEFAULT '', risk_level TEXT NOT NULL DEFAULT 'low',
            device_types_json TEXT NOT NULL DEFAULT '[]', required_fields_json TEXT NOT NULL DEFAULT '[]', optional_fields_json TEXT NOT NULL DEFAULT '[]', field_types_json TEXT NOT NULL DEFAULT '{}',
            max_output_bytes INTEGER NOT NULL DEFAULT 2000000, max_records INTEGER NOT NULL DEFAULT 1000, timeout_seconds INTEGER NOT NULL DEFAULT 30,
            sensitive_level TEXT NOT NULL DEFAULT 'normal', consumers_json TEXT NOT NULL DEFAULT '[]', read_only INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS platform_release_actions (
            id TEXT PRIMARY KEY, release_id TEXT NOT NULL, action_code TEXT NOT NULL, command TEXT NOT NULL,
            parser_template_version_id TEXT, field_contract_json TEXT NOT NULL DEFAULT '{}', command_checksum TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY (release_id) REFERENCES platform_releases(id) ON DELETE CASCADE,
            FOREIGN KEY (action_code) REFERENCES action_definitions(action_code) ON DELETE RESTRICT,
            UNIQUE (release_id, action_code)
        )
    """)
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS parser_templates (
            id TEXT PRIMARY KEY, tenant_id TEXT, platform_profile_id TEXT, platform_code TEXT NOT NULL, template_code TEXT NOT NULL,
            source_filename TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'CUSTOM', status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_by TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, lock_version INTEGER NOT NULL DEFAULT 1,
            CHECK ({template_check}), FOREIGN KEY (platform_profile_id) REFERENCES platform_profiles(id) ON DELETE SET NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parser_template_versions (
            id TEXT PRIMARY KEY, template_id TEXT NOT NULL, version_number INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
            content TEXT NOT NULL, checksum TEXT NOT NULL, field_contract_json TEXT NOT NULL DEFAULT '{}', test_summary_json TEXT NOT NULL DEFAULT '{}',
            created_by TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY (template_id) REFERENCES parser_templates(id) ON DELETE CASCADE, UNIQUE (template_id, version_number)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parser_test_samples (
            id TEXT PRIMARY KEY, template_version_id TEXT NOT NULL, sample_name TEXT NOT NULL, sample_output TEXT NOT NULL,
            expected_records_json TEXT NOT NULL DEFAULT '[]', checksum TEXT NOT NULL, created_by TEXT DEFAULT '', created_at TEXT NOT NULL,
            FOREIGN KEY (template_version_id) REFERENCES parser_template_versions(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS platform_identification_rules (
            id TEXT PRIMARY KEY, platform_profile_id TEXT NOT NULL, command TEXT NOT NULL, match_type TEXT NOT NULL,
            pattern TEXT NOT NULL, logic_group TEXT NOT NULL DEFAULT 'ALL', rule_order INTEGER NOT NULL DEFAULT 100, confidence REAL NOT NULL DEFAULT 0,
            negate INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
            FOREIGN KEY (platform_profile_id) REFERENCES platform_profiles(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS platform_release_audit_logs (
            id TEXT PRIMARY KEY, release_id TEXT NOT NULL, event_type TEXT NOT NULL, actor_id TEXT, actor_username TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
            FOREIGN KEY (release_id) REFERENCES platform_releases(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS playbook_release_audit_logs (
            id TEXT PRIMARY KEY, playbook_id TEXT NOT NULL, playbook_version_id TEXT, event_type TEXT NOT NULL, actor_id TEXT, actor_username TEXT,
            platform_release_ids_json TEXT NOT NULL DEFAULT '[]', metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        )
    """)
    for table in ("platform_profiles", "platform_releases", "action_definitions", "platform_release_actions", "parser_templates", "parser_template_versions", "parser_test_samples", "platform_identification_rules", "platform_release_audit_logs", "playbook_release_audit_logs"):
        cursor.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_created_at ON {table}(created_at)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_profiles_system_code ON platform_profiles(platform_code) WHERE tenant_id IS NULL AND source = 'SYSTEM'")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_profiles_tenant_code ON platform_profiles(tenant_id, platform_code) WHERE tenant_id IS NOT NULL")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_parser_templates_system_code ON parser_templates(platform_code, template_code) WHERE tenant_id IS NULL")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_parser_templates_tenant_code ON parser_templates(tenant_id, platform_code, template_code) WHERE tenant_id IS NOT NULL")


def _seed_action_definitions(cursor) -> None:
    from services.platform_registry_service import iter_action_definitions

    now = _now()
    for item in iter_action_definitions():
        cursor.execute(
            """INSERT INTO action_definitions (action_code, name_zh, name_en, purpose, risk_level, device_types_json, required_fields_json, optional_fields_json, field_types_json, max_output_bytes, max_records, timeout_seconds, sensitive_level, consumers_json, read_only, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(action_code) DO UPDATE SET name_zh=excluded.name_zh, name_en=excluded.name_en, purpose=excluded.purpose, risk_level=excluded.risk_level, device_types_json=excluded.device_types_json, required_fields_json=excluded.required_fields_json, optional_fields_json=excluded.optional_fields_json, field_types_json=excluded.field_types_json, max_records=excluded.max_records, timeout_seconds=excluded.timeout_seconds, sensitive_level=excluded.sensitive_level, consumers_json=excluded.consumers_json""",
            (item["action_code"], item["name_zh"], item["name_en"], item["purpose"], item["risk"], _json(item.get("device_types") or []), _json(item.get("fields") or []), _json(item.get("optional_fields") or []), _json(item.get("field_types") or {}), 2_000_000, int(item.get("max_records") or 1000), int(item.get("timeout_seconds") or 30), "sensitive" if item["risk"] == "sensitive" else "normal", _json(item.get("consumers") or []), now),
        )


def _seed_profiles_and_releases(cursor) -> None:
    from services.platform_registry_service import SYSTEM_PROFILES, get_profile_action_commands

    now = _now()
    for profile in SYSTEM_PROFILES:
        profile_id = f"system-profile-{profile['platform_code']}"
        cursor.execute(
            """INSERT INTO platform_profiles (id, tenant_id, platform_code, name_zh, name_en, vendor, connection_driver, parser_platform, source, status, description, created_by, created_at, updated_at, lock_version)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE', '', 'system', ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET name_zh=excluded.name_zh, name_en=excluded.name_en, vendor=excluded.vendor, connection_driver=excluded.connection_driver, parser_platform=excluded.parser_platform, updated_at=excluded.updated_at""",
            (profile_id, profile["platform_code"], profile["name_zh"], profile["name_en"], profile["vendor"], profile["connection_driver"], profile["parser_platform"], now, now),
        )
        release_id = f"system-release-{profile['platform_code']}-v1"
        checksum = _sha(f"{profile['platform_code']}:1")
        cursor.execute(
            """INSERT INTO platform_releases (id, profile_id, release_number, status, connection_driver, parser_platform, safety_policy_json, checksum, validation_status, validation_result_json, created_by, approved_by, published_by, created_at, updated_at, lock_version)
               VALUES (?, ?, 1, 'PUBLISHED', ?, ?, ?, ?, 'PASSED', '{"seed":true}', 'system', 'system', 'system', ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET connection_driver=excluded.connection_driver, parser_platform=excluded.parser_platform, updated_at=excluded.updated_at""",
            (release_id, profile_id, profile["connection_driver"], profile["parser_platform"], _json({"read_only": True, "allowed_prefixes": ["show", "display"]}), checksum, now, now),
        )
        cursor.execute("UPDATE platform_profiles SET current_release_id = ? WHERE id = ? AND (current_release_id IS NULL OR current_release_id = '')", (release_id, profile_id))
        for action_code, command in get_profile_action_commands(profile).items():
            cursor.execute("SELECT id FROM platform_release_actions WHERE release_id = ? AND action_code = ?", (release_id, action_code))
            if cursor.fetchone():
                continue
            cursor.execute(
                "INSERT INTO platform_release_actions (id, release_id, action_code, command, field_contract_json, command_checksum, created_at, updated_at) VALUES (?, ?, ?, ?, '{}', ?, ?, ?)",
                (str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:{release_id}:{action_code}")), release_id, action_code, command, _sha(command), now, now),
            )


def _refresh_release_checksums(cursor) -> None:
    for row in cursor.execute("SELECT id FROM platform_releases WHERE status = 'PUBLISHED'").fetchall():
        release_id = row[0]
        actions = [dict(item) for item in cursor.execute(
            "SELECT action_code, command, parser_template_version_id, field_contract_json FROM platform_release_actions WHERE release_id = ? ORDER BY action_code",
            (release_id,),
        ).fetchall()]
        cursor.execute("UPDATE platform_releases SET checksum = ? WHERE id = ?", (_sha(_json(actions)), release_id))


def _import_custom_templates(cursor, use_pg: bool) -> None:
    """Import existing file templates as immutable SYSTEM v1 records.

    The file remains available for backward compatibility, but the registry
    becomes the identity/checksum source for new execution paths.
    """
    from services.platform_registry_service import SYSTEM_PROFILES

    root = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates"
    if not root.exists():
        return
    # Match a filename to the concrete Profile code first.  Several concrete
    # profiles may intentionally share one parser family (for example H3C
    # Comware V5/V7 both use the hp_comware driver), so selecting by parser
    # platform alone would put templates into the wrong Profile.
    profile_defs = sorted(SYSTEM_PROFILES, key=lambda item: len(str(item["platform_code"])), reverse=True)
    now = _now()
    for path in sorted(root.glob("*.textfsm")):
        stem = path.stem
        profile = next((item for item in profile_defs if stem.startswith(str(item["platform_code"]) + "_")), None)
        if not profile:
            continue
        profile_code = str(profile["platform_code"])
        parser_platform = str(profile["parser_platform"])
        template_code = re.sub(r"[^A-Z0-9_]", "_", stem.upper())[:64]
        if not template_code or not re.match(r"^[A-Z]", template_code):
            continue
        content = path.read_text(encoding="utf-8")
        checksum = _sha(content)
        template_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template:{path.name}"))
        version_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"nexora:system-template-version:{path.name}:1"))
        profile_row = cursor.execute("SELECT id FROM platform_profiles WHERE platform_code = ? AND source = 'SYSTEM' ORDER BY id LIMIT 1", (profile_code,)).fetchone()
        profile_id = profile_row[0] if profile_row else None
        cursor.execute(
            """INSERT INTO parser_templates (id, tenant_id, platform_profile_id, platform_code, template_code, source_filename, name, source, status, created_by, created_at, updated_at, lock_version)
               VALUES (?, NULL, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE', 'system', ?, ?, 1)
               ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at""",
            (template_id, profile_id, parser_platform, template_code, path.name, path.stem, now, now),
        )
        cursor.execute(
            """INSERT INTO parser_template_versions (id, template_id, version_number, status, content, checksum, field_contract_json, test_summary_json, created_by, created_at, updated_at)
               VALUES (?, ?, 1, 'PUBLISHED', ?, ?, '{}', '{"imported":true}', 'system', ?, ?)
               ON CONFLICT(id) DO UPDATE SET content=excluded.content, checksum=excluded.checksum, updated_at=excluded.updated_at""",
            (version_id, template_id, content, checksum, now, now),
        )
        # Bind a matching imported template version when the release command
        # uses the same canonical filename.
        for release_row in cursor.execute("SELECT r.id FROM platform_releases r JOIN platform_profiles p ON p.id = r.profile_id WHERE p.id = ? AND r.status = 'PUBLISHED'", (profile_id,)).fetchall():
            command = path.stem[len(profile_code) + 1:].replace("_", " ")
            cursor.execute("UPDATE platform_release_actions SET parser_template_version_id = ? WHERE release_id = ? AND lower(replace(command, '-', ' ')) = ?", (version_id, release_row[0], command.lower()))


def _backfill_devices(cursor) -> None:
    from services.platform_registry_service import PLATFORM_ALIASES

    for raw, canonical in PLATFORM_ALIASES.items():
        profile_id = f"system-profile-{canonical}"
        cursor.execute("UPDATE devices SET platform_profile_id = ?, platform_source = 'SYSTEM', platform_locked = COALESCE(platform_locked, 0) WHERE (platform_profile_id IS NULL OR platform_profile_id = '') AND lower(COALESCE(platform, '')) = ?", (profile_id, raw))
    for canonical in {p for p in PLATFORM_ALIASES.values()}:
        profile_id = f"system-profile-{canonical}"
        cursor.execute("UPDATE devices SET platform_profile_id = ?, platform_source = 'SYSTEM', platform_locked = COALESCE(platform_locked, 0) WHERE (platform_profile_id IS NULL OR platform_profile_id = '') AND lower(COALESCE(platform, '')) = ?", (profile_id, canonical))


def upgrade(cursor, use_pg: bool) -> None:
    for column, definition in (
        ("platform_profile_id", "TEXT"),
        ("platform_source", "TEXT DEFAULT 'LEGACY'"),
        ("platform_locked", "INTEGER DEFAULT 0"),
        ("tenant_id", "TEXT"),
    ):
        _ensure_column(cursor, "devices", column, definition, use_pg)
    _create_tables(cursor, use_pg)
    _seed_action_definitions(cursor)
    _seed_profiles_and_releases(cursor)
    _import_custom_templates(cursor, use_pg)
    _refresh_release_checksums(cursor)
    _backfill_devices(cursor)
