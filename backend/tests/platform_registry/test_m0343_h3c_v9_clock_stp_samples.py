from __future__ import annotations

import hashlib
from pathlib import Path

from database import get_db_connection
from database.migrations import discover_migrations

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = {
    "get_clock": ("display clock", "h3c_comware_v9_display_clock.textfsm"),
    "get_stp": ("display stp brief", "h3c_comware_v9_display_stp_brief.textfsm"),
}


def test_h3c_v9_clock_and_stp_migration_mirrors_templates_and_binds_current_actions(isolated_db):
    versions = [int(module.VERSION) for module in discover_migrations()]
    assert versions == sorted(versions)
    assert 343 in versions

    conn = get_db_connection()
    try:
        applied = conn.execute(
            "SELECT name FROM schema_migrations WHERE version = ?",
            (343,),
        ).fetchone()
        assert applied and applied[0] == "h3c_v9_clock_stp_samples"

        for action_code, (command, filename) in TEMPLATES.items():
            row = conn.execute(
                """SELECT a.command, a.parser_template_version_id,
                          t.source_filename, t.platform_profile_id,
                          v.content, v.checksum, p.current_release_id
                   FROM platform_profiles p
                   JOIN platform_releases r ON r.id = p.current_release_id
                   JOIN platform_release_actions a ON a.release_id = r.id
                   JOIN parser_template_versions v
                     ON v.id = a.parser_template_version_id
                   JOIN parser_templates t ON t.id = v.template_id
                   WHERE p.platform_code = 'h3c_comware_v9'
                     AND p.source = 'SYSTEM' AND p.tenant_id IS NULL
                     AND p.status = 'ACTIVE' AND r.status = 'PUBLISHED'
                     AND a.action_code = ?""",
                (action_code,),
            ).fetchone()
            assert row is not None
            assert row[0] == command
            assert row[2] == filename
            assert row[3] == "system-profile-h3c_comware_v9"

            expected_bytes = (
                ROOT / "data" / "textfsm_templates" / filename
            ).read_text(encoding="utf-8")
            assert row[4] == expected_bytes
            assert row[5] == hashlib.sha256(expected_bytes.encode("utf-8")).hexdigest()
    finally:
        conn.close()
