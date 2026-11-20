from __future__ import annotations

from database.migrations import m0186_repair_vendor_action_catalogs as migration


def _current_release(conn, platform_code: str) -> str:
    row = conn.execute(
        """SELECT current_release_id FROM platform_profiles
           WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = ?""",
        (platform_code,),
    ).fetchone()
    assert row and row[0]
    return str(row[0])


def test_repairs_persisted_system_commands_on_postgresql(isolated_db) -> None:
    database = isolated_db["module"]
    with database.get_db_connection() as conn:
        dptech_release = _current_release(conn, "dptech_fw_s211")
        huawei_release = _current_release(conn, "huawei_vrp")
        conn.execute(
            """UPDATE platform_release_actions SET command = 'display lldp neighbor brief'
               WHERE release_id = ? AND action_code = 'get_lldp_neighbors'""",
            (dptech_release,),
        )
        conn.execute(
            """UPDATE platform_release_actions SET command = 'display fan'
               WHERE release_id = ? AND action_code = 'get_fans'""",
            (huawei_release,),
        )

        migration.upgrade(conn.cursor(), True)
        migration.upgrade(conn.cursor(), True)

        dptech = conn.execute(
            """SELECT command FROM platform_release_actions
               WHERE release_id = ? AND action_code = 'get_lldp_neighbors'""",
            (dptech_release,),
        ).fetchone()
        huawei = conn.execute(
            """SELECT command FROM platform_release_actions
               WHERE release_id = ? AND action_code = 'get_fans'""",
            (huawei_release,),
        ).fetchone()
        assert dptech[0] == "show lldp neighbors"
        assert huawei[0] == "dis fan"
