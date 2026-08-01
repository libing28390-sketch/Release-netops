import sqlite3

from database.migrations.m0058_official_domestic_vendor_templates import upgrade
from services.config_template_validation_service import validate_template


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE templates (
            id TEXT PRIMARY KEY, name TEXT, type TEXT, category TEXT, vendor TEXT,
            content TEXT, rollback TEXT, last_used TEXT, description TEXT DEFAULT '',
            platform_family TEXT DEFAULT '', software_version TEXT DEFAULT '',
            official_reference TEXT DEFAULT '', validation_status TEXT DEFAULT 'draft',
            source_type TEXT DEFAULT 'custom', is_official INTEGER DEFAULT 0,
            status TEXT DEFAULT 'draft', current_version TEXT DEFAULT '1.0',
            created_by TEXT DEFAULT '', created_at TEXT DEFAULT '', updated_at TEXT DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE config_template_compatibility (
            id TEXT PRIMARY KEY, template_id TEXT, vendor TEXT, platform TEXT,
            model_pattern TEXT, min_version TEXT, max_version TEXT,
            required_capabilities_json TEXT, excluded_versions_json TEXT
        )
        """
    )
    return conn


def test_domestic_vendor_templates_are_idempotent_and_renderable() -> None:
    conn = _connection()
    try:
        upgrade(conn, use_pg=False)
        upgrade(conn, use_pg=False)
        rows = conn.execute(
            "SELECT id, vendor, platform_family, content, rollback FROM templates ORDER BY id"
        ).fetchall()
        compatibility_count = conn.execute(
            "SELECT COUNT(*) FROM config_template_compatibility"
        ).fetchone()[0]
    finally:
        conn.close()

    assert len(rows) == 10
    assert compatibility_count == len(rows)
    assert {row[1] for row in rows} == {"Ruijie", "ZTE", "DPtech", "Maipu"}
    for template_id, vendor, platform, content, rollback in rows:
        result = validate_template(
            content,
            vendor=vendor,
            platform=platform,
            variables={
                "netmask": "24",
                "wildcard": "0.0.0.255",
            },
            rollback=rollback,
        )
        assert result["syntax_valid"] is True, template_id
        assert result["render_valid"] is True, (template_id, result["issues"])
        assert result["warnings"] == [
            warning for warning in result["warnings"]
            if warning["code"] != "vendor_command_family_mismatch"
        ]
