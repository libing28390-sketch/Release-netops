from __future__ import annotations

import pytest

from database.migrations import m0275_huawei_yunshan_platform as migration


def test_m0275_uses_packaged_templates_when_docker_data_volume_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        migration,
        "TEMPLATES",
        {"huawei_yunshan_display_version.textfsm": ("get_version", "display version")},
    )
    # Docker mounts persistent storage at /app/data, so the source-layout
    # directory may exist while containing no release-owned templates.
    (tmp_path / "data" / "textfsm_templates").mkdir(parents=True)
    packaged = tmp_path / "release-textfsm-templates"
    packaged.mkdir()
    (packaged / "huawei_yunshan_display_version.textfsm").write_text(
        "# packaged YunShan template\n", encoding="utf-8",
    )

    assert migration._resolve_template_root(tmp_path) == packaged


def test_m0275_falls_back_to_source_templates_for_development(tmp_path, monkeypatch) -> None:
    filename = "huawei_yunshan_display_version.textfsm"
    monkeypatch.setattr(migration, "TEMPLATES", {filename: ("get_version", "display version")})
    source = tmp_path / "data" / "textfsm_templates"
    source.mkdir(parents=True)
    (source / filename).write_text("# source YunShan template\n", encoding="utf-8")

    assert migration._resolve_template_root(tmp_path) == source


def test_m0275_reports_missing_templates_before_registration(tmp_path, monkeypatch) -> None:
    missing = (
        "huawei_yunshan_display_version.textfsm",
        "huawei_yunshan_display_interface_brief.textfsm",
    )
    monkeypatch.setattr(
        migration,
        "TEMPLATES",
        {filename: ("get_version", "display version") for filename in missing},
    )
    (tmp_path / "release-textfsm-templates").mkdir()
    (tmp_path / "data" / "textfsm_templates").mkdir(parents=True)

    with pytest.raises(RuntimeError) as exc_info:
        migration._resolve_template_root(tmp_path)

    assert all(filename in str(exc_info.value) for filename in missing)


def _remove_system_yunshan_seed(conn) -> None:
    conn.execute(
        """DELETE FROM platform_identification_rules
           WHERE platform_profile_id IN (
             SELECT id FROM platform_profiles
             WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = 'huawei_yunshan'
           )"""
    )
    conn.execute(
        """DELETE FROM parser_template_versions
           WHERE template_id IN (
             SELECT id FROM parser_templates
             WHERE tenant_id IS NULL AND source = 'SYSTEM'
               AND source_filename LIKE 'huawei_yunshan_%'
           )"""
    )
    conn.execute(
        """DELETE FROM parser_templates
           WHERE tenant_id IS NULL AND source = 'SYSTEM'
             AND source_filename LIKE 'huawei_yunshan_%'"""
    )
    conn.execute(
        """DELETE FROM platform_releases
           WHERE profile_id IN (
             SELECT id FROM platform_profiles
             WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = 'huawei_yunshan'
           )"""
    )
    conn.execute(
        """DELETE FROM platform_profiles
           WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = 'huawei_yunshan'"""
    )
    conn.execute("DELETE FROM schema_migrations WHERE version = 275")


def test_m0275_registers_scoped_templates_and_preserves_custom_profile(isolated_db) -> None:
    conn = isolated_db["module"].get_db_connection()
    now = "2026-10-06T00:00:00+00:00"
    try:
        _remove_system_yunshan_seed(conn)
        conn.execute(
            "UPDATE action_definitions SET name_en = ? WHERE action_code = ?",
            ("Preserved existing action", "get_version"),
        )
        conn.execute(
            """INSERT INTO platform_profiles
               (id, tenant_id, platform_code, name_zh, name_en, vendor,
                connection_driver, parser_platform, source, status, created_by,
                created_at, updated_at, lock_version)
               VALUES ('custom-yunshan-profile', 'tenant-yunshan', 'huawei_yunshan',
                       'Tenant-owned YunShan', 'Tenant-owned YunShan', 'Huawei',
                       'tenant-driver', 'tenant-parser', 'CUSTOM', 'ACTIVE',
                       'test', ?, ?, 1)""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO parser_templates
               (id, tenant_id, platform_profile_id, platform_code, template_code,
                source_filename, command, name, source, status, created_by,
                created_at, updated_at, lock_version)
               VALUES ('custom-yunshan-template', 'tenant-yunshan', 'custom-yunshan-profile',
                       'huawei_yunshan', 'CUSTOM_YUNSHAN_VERSION',
                       'huawei_yunshan_display_version.textfsm', 'custom command',
                       'Tenant-owned template', 'CUSTOM', 'ACTIVE', 'test', ?, ?, 1)""",
            (now, now),
        )
        conn.commit()

        recorded_versions = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        assert 274 in recorded_versions
        assert 275 not in recorded_versions

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        first_counts = (
            conn.execute(
                """SELECT COUNT(*) FROM platform_profiles
                   WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = 'huawei_yunshan'"""
            ).fetchone()[0],
            conn.execute(
                """SELECT COUNT(*) FROM parser_templates
                   WHERE tenant_id IS NULL AND source = 'SYSTEM'
                     AND platform_profile_id = 'system-profile-huawei_yunshan'"""
            ).fetchone()[0],
            conn.execute(
                """SELECT COUNT(*) FROM platform_release_actions a
                   JOIN platform_releases r ON r.id = a.release_id
                   WHERE r.profile_id = 'system-profile-huawei_yunshan'"""
            ).fetchone()[0],
        )

        migration.upgrade(conn.cursor(), use_pg=True)
        conn.commit()
        second_counts = (
            conn.execute(
                """SELECT COUNT(*) FROM platform_profiles
                   WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = 'huawei_yunshan'"""
            ).fetchone()[0],
            conn.execute(
                """SELECT COUNT(*) FROM parser_templates
                   WHERE tenant_id IS NULL AND source = 'SYSTEM'
                     AND platform_profile_id = 'system-profile-huawei_yunshan'"""
            ).fetchone()[0],
            conn.execute(
                """SELECT COUNT(*) FROM platform_release_actions a
                   JOIN platform_releases r ON r.id = a.release_id
                   WHERE r.profile_id = 'system-profile-huawei_yunshan'"""
            ).fetchone()[0],
        )
        assert first_counts == second_counts == (1, 6, 6)
        assert conn.execute(
            "SELECT name_en FROM action_definitions WHERE action_code = ?", ("get_version",),
        ).fetchone()[0] == "Preserved existing action"

        profile = conn.execute(
            """SELECT platform_code, vendor, connection_driver, parser_platform,
                      source, status, current_release_id
                 FROM platform_profiles
                WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = 'huawei_yunshan'"""
        ).fetchone()
        assert tuple(profile) == (
            "huawei_yunshan", "Huawei", "huawei_vrp", "huawei_yunshan",
            "SYSTEM", "ACTIVE", "system-release-huawei_yunshan-v1",
        )

        bindings = conn.execute(
            """SELECT a.action_code, a.command, v.status, t.platform_code,
                      t.platform_profile_id, t.tenant_id, t.source
                 FROM platform_release_actions a
                 JOIN platform_releases r ON r.id = a.release_id
                 JOIN parser_template_versions v ON v.id = a.parser_template_version_id
                 JOIN parser_templates t ON t.id = v.template_id
                WHERE r.profile_id = 'system-profile-huawei_yunshan'
                ORDER BY a.action_code"""
        ).fetchall()
        assert len(bindings) == 6
        assert {row[0] for row in bindings} == {action for action, _command in migration.TEMPLATES.values()}
        assert all(
            row[2] == "PUBLISHED"
            and row[3] == "huawei_yunshan"
            and row[4] == "system-profile-huawei_yunshan"
            and row[5] is None
            and row[6] == "SYSTEM"
            for row in bindings
        )
        identity_rules = conn.execute(
            """SELECT command, pattern, logic_group, confidence
                 FROM platform_identification_rules
                WHERE platform_profile_id = 'system-profile-huawei_yunshan'"""
        ).fetchall()
        assert len(identity_rules) == 1
        assert tuple(identity_rules[0]) == ("display version", "YunShan OS", "ANY", 0.99)

        custom_profile = conn.execute(
            """SELECT vendor, connection_driver, parser_platform, source
                 FROM platform_profiles WHERE id = 'custom-yunshan-profile'"""
        ).fetchone()
        assert tuple(custom_profile) == ("Huawei", "tenant-driver", "tenant-parser", "CUSTOM")
        custom_template = conn.execute(
            """SELECT command, source, platform_profile_id
                 FROM parser_templates WHERE id = 'custom-yunshan-template'"""
        ).fetchone()
        assert tuple(custom_template) == (
            "custom command", "CUSTOM", "custom-yunshan-profile",
        )
    finally:
        conn.close()
