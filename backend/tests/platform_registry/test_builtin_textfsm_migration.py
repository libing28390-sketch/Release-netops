from __future__ import annotations

from database.migrations.m0100_register_builtin_textfsm_templates import upgrade


def test_builtin_cisco_arp_templates_are_registered_and_bound(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        cursor = conn.cursor()
        upgrade(cursor, True)
        conn.commit()

        parser = conn.execute(
            """SELECT t.template_code, t.source, t.command, v.id, v.status
               FROM parser_templates t
               JOIN parser_template_versions v ON v.template_id = t.id
               WHERE t.platform_code = 'cisco_ios'
                 AND t.source_filename = 'cisco_ios_show_ip_arp.textfsm'"""
        ).fetchone()
        assert parser["template_code"] == "CISCO_IOS_SHOW_IP_ARP"
        assert parser["source"] == "SYSTEM"
        assert parser["command"] == "show ip arp"
        assert parser["status"] == "PUBLISHED"

        action = conn.execute(
            """SELECT a.command, a.parser_template_version_id
               FROM platform_release_actions a
               WHERE a.release_id = 'system-release-cisco_ios-v1'
                 AND a.action_code = 'get_arp_table'"""
        ).fetchone()
        assert action["command"] == "show ip arp"
        assert action["parser_template_version_id"] == parser["id"]

        before_count = conn.execute(
            "SELECT COUNT(*) AS count FROM parser_templates WHERE source = 'SYSTEM'"
        ).fetchone()["count"]
        upgrade(cursor, True)
        conn.commit()
        after_count = conn.execute(
            "SELECT COUNT(*) AS count FROM parser_templates WHERE source = 'SYSTEM'"
        ).fetchone()["count"]
        assert after_count == before_count
    finally:
        conn.close()


def test_concrete_h3c_profiles_keep_commands_and_templates_separate(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rows = conn.execute(
            """SELECT p.platform_code, a.command, t.source_filename, t.platform_profile_id
               FROM platform_profiles p
               JOIN platform_releases r ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
               JOIN platform_release_actions a ON a.release_id = r.id AND a.action_code = 'get_arp_table'
               LEFT JOIN parser_template_versions v ON v.id = a.parser_template_version_id
               LEFT JOIN parser_templates t ON t.id = v.template_id
               WHERE p.platform_code IN ('hp_comware', 'h3c_comware')
               ORDER BY p.platform_code"""
        ).fetchall()
        assert [row[0] for row in rows] == ["h3c_comware", "hp_comware"]
        by_platform = {row[0]: row for row in rows}
        assert by_platform["hp_comware"][1] == "display arp"
        assert by_platform["h3c_comware"][1] == "display arp all"
        assert by_platform["hp_comware"][3] == "system-profile-hp_comware"
        assert by_platform["h3c_comware"][3] == "system-profile-h3c_comware"
        assert by_platform["h3c_comware"][2] == "h3c_comware_display_arp_all.textfsm"
    finally:
        conn.close()


def test_shared_parser_family_templates_are_concrete_and_command_strict(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        rows = conn.execute(
            """SELECT p.platform_code, a.command, a.parser_template_version_id,
                      t.source_filename, t.platform_profile_id
               FROM platform_profiles p
               JOIN platform_releases r ON r.id = p.current_release_id AND r.status = 'PUBLISHED'
               JOIN platform_release_actions a ON a.release_id = r.id AND a.action_code = 'get_arp_table'
               LEFT JOIN parser_template_versions v ON v.id = a.parser_template_version_id
               LEFT JOIN parser_templates t ON t.id = v.template_id
               WHERE p.platform_code IN ('zte_5900_v6', 'zte_zsrv2_v3',
                                         'ruijie_s6k_rgos12', 'ruijie_eg_rgos11')
               ORDER BY p.platform_code"""
        ).fetchall()
        assert len(rows) == 4
        assert all(row[1] == "show arp" for row in rows)
        assert all(row[2] for row in rows)
        assert all(
            row[3] == f"{row[0]}__zte_zxros_show_arp.textfsm"
            if row[0].startswith("zte_")
            else row[3] == f"{row[0]}__ruijie_rgos_show_arp.textfsm"
            for row in rows
        )
        assert all(row[4] == f"system-profile-{row[0]}" for row in rows)
        assert len({row[2] for row in rows}) == 4
    finally:
        conn.close()


def test_system_templates_have_concrete_profile_scopes(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        unscoped = conn.execute(
            """SELECT source_filename, platform_code
               FROM parser_templates
               WHERE tenant_id IS NULL AND source = 'SYSTEM'
                 AND (platform_profile_id IS NULL OR platform_profile_id = '')"""
        ).fetchall()
        assert not unscoped

        collisions = conn.execute(
            """SELECT platform_profile_id, source_filename, COUNT(*)
               FROM parser_templates
               WHERE tenant_id IS NULL AND source = 'SYSTEM'
               GROUP BY platform_profile_id, source_filename
               HAVING COUNT(*) > 1"""
        ).fetchall()
        assert not collisions
    finally:
        conn.close()
