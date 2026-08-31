from __future__ import annotations

from backend.tests.pg_test_utils import postgresql_test_driver
from database.migrations import m0128_repair_h3c_aggregation_actions as migration


def test_repairs_h3c_aggregation_action_idempotently(monkeypatch):
    conn = postgresql_test_driver.connect()
    conn.row_factory = postgresql_test_driver.Row
    conn.executescript(
        """
        CREATE TABLE action_definitions (
            action_code TEXT PRIMARY KEY, name_zh TEXT, name_en TEXT, purpose TEXT,
            risk_level TEXT, device_types_json TEXT, required_fields_json TEXT,
            optional_fields_json TEXT, field_types_json TEXT, max_output_bytes INTEGER,
            max_records INTEGER, timeout_seconds INTEGER, sensitive_level TEXT,
            consumers_json TEXT, read_only INTEGER, created_at TEXT
        );
        CREATE TABLE platform_profiles (
            id TEXT PRIMARY KEY, tenant_id TEXT, platform_code TEXT,
            parser_platform TEXT, source TEXT, current_release_id TEXT
        );
        CREATE TABLE platform_releases (
            id TEXT PRIMARY KEY, profile_id TEXT, status TEXT,
            checksum TEXT, updated_at TEXT
        );
        CREATE TABLE platform_release_actions (
            id TEXT PRIMARY KEY, release_id TEXT NOT NULL, action_code TEXT NOT NULL,
            command TEXT NOT NULL, parser_template_version_id TEXT,
            field_contract_json TEXT NOT NULL, command_checksum TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (release_id, action_code)
        );
        INSERT INTO platform_profiles
            (id, tenant_id, platform_code, parser_platform, source, current_release_id)
            VALUES ('system-profile-h3c_comware', NULL, 'h3c_comware', 'h3c_comware',
                    'SYSTEM', 'system-release-h3c_comware-v1');
        INSERT INTO platform_releases
            (id, profile_id, status, checksum, updated_at)
            VALUES ('system-release-h3c_comware-v1', 'system-profile-h3c_comware',
                    'PUBLISHED', '', '');
        """
    )

    import services.platform_registry_service as registry

    monkeypatch.setattr(
        registry,
        "SYSTEM_PROFILES",
        [{"platform_code": "h3c_comware", "parser_platform": "h3c_comware"}],
    )
    monkeypatch.setattr(
        registry,
        "get_profile_action_commands",
        lambda _: {"get_link_aggregation": "display link-aggregation verbose"},
    )
    monkeypatch.setattr(
        registry,
        "iter_action_definitions",
        lambda: [{
            "action_code": "get_link_aggregation",
            "name_zh": "获取链路聚合",
            "name_en": "Get Link Aggregation",
            "purpose": "聚合口采集",
            "risk": "low",
            "fields": ["group", "interface", "member"],
            "max_records": 1000,
        }],
    )

    migration.upgrade(conn.cursor(), True)
    migration.upgrade(conn.cursor(), True)

    row = conn.execute(
        "SELECT command FROM platform_release_actions "
        "WHERE release_id = ? AND action_code = ?",
        ("system-release-h3c_comware-v1", "get_link_aggregation"),
    ).fetchone()
    assert row["command"] == "display link-aggregation verbose"
    assert conn.execute(
        "SELECT COUNT(*) FROM platform_release_actions "
        "WHERE release_id = ? AND action_code = ?",
        ("system-release-h3c_comware-v1", "get_link_aggregation"),
    ).fetchone()[0] == 1
