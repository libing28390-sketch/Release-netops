from __future__ import annotations

from database.migrations import m0212_h3c_comware_v3_platform as migration


def test_m0212_long_template_codes_keep_a_deterministic_unique_suffix():
    source_code = "H3C_COMWARE_V5_" + ("DISPLAY_INTERFACE_" * 5)

    first = migration._target_template_code("source-a", source_code)
    second = migration._target_template_code("source-b", source_code)

    assert len(first) <= 64
    assert len(second) <= 64
    assert first != second
    assert first == migration._target_template_code("source-a", source_code)


def test_m0212_registers_h3c_v3_profile_release_actions_and_scoped_templates(isolated_db):
    assert migration.VERSION == 212
    conn = isolated_db["module"].get_db_connection()
    try:
        profile = conn.execute(
            """SELECT id, platform_code, vendor, connection_driver, parser_platform,
                      source, status, current_release_id
                 FROM platform_profiles
                WHERE platform_code = 'h3c_comware_v3'
                  AND tenant_id IS NULL"""
        ).fetchone()
        assert profile is not None
        assert dict(profile) == {
            "id": "system-profile-h3c_comware_v3",
            "platform_code": "h3c_comware_v3",
            "vendor": "H3C",
            "connection_driver": "hp_comware",
            "parser_platform": "h3c_comware",
            "source": "SYSTEM",
            "status": "ACTIVE",
            "current_release_id": "system-release-h3c_comware_v3-v1",
        }

        action = conn.execute(
            """SELECT a.command, a.parser_template_version_id
                 FROM platform_release_actions a
                 JOIN platform_releases r ON r.id = a.release_id
                WHERE r.profile_id = ?
                  AND r.status = 'PUBLISHED'
                  AND a.action_code = 'get_bgp_neighbors'""",
            (profile["id"],),
        ).fetchone()
        assert action is not None
        assert action["command"] == "display bgp peer"
        assert action["parser_template_version_id"]
        binding = conn.execute(
            """SELECT t.platform_profile_id, t.platform_code
                 FROM parser_template_versions v
                 JOIN parser_templates t ON t.id = v.template_id
                WHERE v.id = ?""",
            (action["parser_template_version_id"],),
        ).fetchone()
        assert binding is not None
        assert binding["platform_profile_id"] == profile["id"]
        assert binding["platform_code"] == "h3c_comware"

        scoped_templates = conn.execute(
            """SELECT COUNT(*) AS count
                 FROM parser_templates
                WHERE tenant_id IS NULL
                  AND source = 'SYSTEM'
                  AND platform_profile_id = ?""",
            (profile["id"],),
        ).fetchone()
        assert scoped_templates["count"] > 0
    finally:
        conn.close()
