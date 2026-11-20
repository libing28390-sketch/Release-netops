from __future__ import annotations

from database.migrations.m0094_repair_huawei_eth_trunk_command import _checksum, upgrade


def test_huawei_eth_trunk_command_migration_is_idempotent_and_rechecksums_release(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """UPDATE platform_release_actions
               SET command = ?, command_checksum = ?
               WHERE release_id = 'system-release-huawei_vrp-v1'
                 AND action_code = 'get_link_aggregation'""",
            ("dis eth-trunk", _checksum("dis eth-trunk")),
        )
        conn.commit()
        cursor = conn.cursor()
        upgrade(cursor, True)
        conn.commit()
        first = conn.execute(
            """SELECT a.command, a.command_checksum, r.checksum
               FROM platform_release_actions a
               JOIN platform_releases r ON r.id = a.release_id
               WHERE a.release_id = 'system-release-huawei_vrp-v1'
                 AND a.action_code = 'get_link_aggregation'"""
        ).fetchone()
        upgrade(cursor, True)
        conn.commit()
        second = conn.execute(
            """SELECT a.command, a.command_checksum, r.checksum
               FROM platform_release_actions a
               JOIN platform_releases r ON r.id = a.release_id
               WHERE a.release_id = 'system-release-huawei_vrp-v1'
                 AND a.action_code = 'get_link_aggregation'"""
        ).fetchone()
    finally:
        conn.close()

    assert dict(first) == dict(second)
    assert first[0] == "display eth-trunk"
    assert first[1] == _checksum("display eth-trunk")
