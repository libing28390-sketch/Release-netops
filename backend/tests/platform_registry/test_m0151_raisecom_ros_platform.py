from __future__ import annotations

from database.migrations import m0151_raisecom_ros_platform as migration


def test_m0151_is_idempotent_on_postgresql_registry(isolated_db):
    """Exercise migration 151 against PostgreSQL's real registry constraints."""

    conn = isolated_db["module"].get_db_connection()
    try:
        cursor = conn.cursor()

        # Simulate a production database that reached version 150 before the
        # startup-config action was added to the catalog.  Migration 151 must
        # repair the definition before inserting FK-constrained release rows.
        cursor.execute(
            "DELETE FROM platform_release_actions WHERE action_code = ?",
            ("get_startup_config",),
        )
        cursor.execute(
            "DELETE FROM action_definitions WHERE action_code = ?",
            ("get_startup_config",),
        )
        conn.commit()

        # Recreate the legacy H3C row that caused the original production
        # failure: migration 151 must not refresh unrelated templates and hit
        # this PostgreSQL expression-based unique index.
        cursor.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, command, name, source, status, created_by,
                created_at, updated_at, lock_version)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'SYSTEM', 'ACTIVE',
                       'system', ?, ?, 1)
               ON CONFLICT DO NOTHING""",
            (
                "legacy-h3c-template",
                "system-profile-hp_comware",
                "h3c_comware",
                "H3C_COMWARE_V5_DISPLAY_BGP_PEER_IPV4",
                "h3c_comware_v5_display_bgp_peer_ipv4.textfsm",
                "display bgp peer ipv4",
                "legacy H3C template",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()

        migration.upgrade(cursor, True)
        conn.commit()
        migration.upgrade(cursor, True)
        conn.commit()

        raisecom_template = conn.execute(
            """SELECT t.id, COUNT(v.id) AS version_count
               FROM parser_templates t
               LEFT JOIN parser_template_versions v ON v.template_id = t.id
               WHERE t.tenant_id IS NULL
                 AND t.platform_code = 'raisecom_ros'
                 AND t.platform_profile_id = 'system-profile-raisecom_ros'
                 AND t.template_code = 'RAISECOM_ROS_SHOW_VERSION'
               GROUP BY t.id"""
        ).fetchone()
        assert raisecom_template is not None
        assert raisecom_template[1] == 1

        raisecom_rules = conn.execute(
            """SELECT COUNT(*)
               FROM platform_identification_rules
               WHERE platform_profile_id = 'system-profile-raisecom_ros'"""
        ).fetchone()[0]
        assert raisecom_rules == 3

        get_version_binding = conn.execute(
            """SELECT COUNT(*)
               FROM platform_release_actions
               WHERE release_id = 'system-release-raisecom_ros-v1'
                 AND action_code = 'get_version'
                 AND parser_template_version_id IS NOT NULL"""
        ).fetchone()[0]
        assert get_version_binding == 1

        startup_definition = conn.execute(
            "SELECT risk_level, consumers_json FROM action_definitions "
            "WHERE action_code = ?",
            ("get_startup_config",),
        ).fetchone()
        assert startup_definition is not None
        assert startup_definition[0] == "sensitive"
        assert "configuration" in startup_definition[1]

        raisecom_startup_binding = conn.execute(
            """SELECT COUNT(*) FROM platform_release_actions
               WHERE release_id = 'system-release-raisecom_ros-v1'
                 AND action_code = 'get_startup_config'"""
        ).fetchone()[0]
        assert raisecom_startup_binding == 1

        h3c_template_count = conn.execute(
            """SELECT COUNT(*)
               FROM parser_templates
               WHERE tenant_id IS NULL
                 AND platform_code = 'h3c_comware'
                 AND platform_profile_id = 'system-profile-hp_comware'
                 AND template_code = 'H3C_COMWARE_V5_DISPLAY_BGP_PEER_IPV4'"""
        ).fetchone()[0]
        assert h3c_template_count == 1
    finally:
        conn.close()
