import sqlite3

from database.migrations.m0185_rack_summary_indexes import downgrade, upgrade


def _index_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA index_list('{table}')").fetchall()}


def test_rack_summary_indexes_upgrade_is_idempotent_and_downgrade_is_reversible() -> None:
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute(
            '''CREATE TABLE racks (
                id TEXT PRIMARY KEY, site_id TEXT, floor TEXT, room TEXT, row TEXT, status TEXT
            )'''
        )
        conn.execute(
            '''CREATE TABLE rack_devices (
                id TEXT PRIMARY KEY, rack_id TEXT, asset_id TEXT
            )'''
        )

        upgrade(conn.cursor(), use_pg=False)
        upgrade(conn.cursor(), use_pg=False)

        assert 'idx_racks_summary_scope' in _index_names(conn, 'racks')
        assert 'idx_rack_devices_rack_asset' in _index_names(conn, 'rack_devices')

        downgrade(conn.cursor(), use_pg=False)
        assert 'idx_racks_summary_scope' not in _index_names(conn, 'racks')
        assert 'idx_rack_devices_rack_asset' not in _index_names(conn, 'rack_devices')
    finally:
        conn.close()
