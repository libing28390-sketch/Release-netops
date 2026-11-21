from database.migrations.m0185_rack_summary_indexes import downgrade, upgrade


def _index_names(conn, table: str) -> set[str]:
    rows = conn.execute(
        '''SELECT indexname
           FROM pg_indexes
           WHERE schemaname = current_schema() AND tablename = ?''',
        (table,),
    ).fetchall()
    return {str(row['indexname']) for row in rows}


def test_rack_summary_indexes_upgrade_is_idempotent_and_downgrade_is_reversible(isolated_db) -> None:
    conn = isolated_db['module'].get_db_connection()
    conn.execute('DROP INDEX IF EXISTS idx_racks_summary_scope')
    conn.execute('DROP INDEX IF EXISTS idx_rack_devices_rack_asset')

    upgrade(conn.cursor(), use_pg=True)
    upgrade(conn.cursor(), use_pg=True)

    assert 'idx_racks_summary_scope' in _index_names(conn, 'racks')
    assert 'idx_rack_devices_rack_asset' in _index_names(conn, 'rack_devices')

    downgrade(conn.cursor(), use_pg=True)
    assert 'idx_racks_summary_scope' not in _index_names(conn, 'racks')
    assert 'idx_rack_devices_rack_asset' not in _index_names(conn, 'rack_devices')
