from __future__ import annotations

from unittest.mock import MagicMock, patch

from database import get_db_connection


def test_discovery_history_reset_deletes_source_observations_and_refreshes_projection():
    from services.topology_service import _clear_lldp_observation_history_for_run

    conn = MagicMock()
    conn.execute.return_value.rowcount = 3

    with patch('services.topology_service.get_db_connection', return_value=conn):
        with patch('services.topology_service.rebuild_links_from_observations') as rebuild:
            deleted = _clear_lldp_observation_history_for_run(
                ['device-b', 'device-a', 'device-b']
            )

    assert deleted == 3
    statements = [call.args[0] for call in conn.execute.call_args_list]
    assert len(statements) == 5  # optional evidence-table savepoint + reset statements
    assert 'DELETE FROM topology_observations' in statements[0]
    assert "COALESCE(protocol, 'lldp') = 'lldp'" in statements[0]
    assert 'DELETE FROM topology_links' in statements[1]
    assert "LIKE '%lldp%'" in statements[1]
    assert 'DELETE FROM topology_protocol_observations' in statements[3]
    assert conn.execute.call_args_list[0].args[1] == ('device-a', 'device-b')
    assert conn.execute.call_args_list[1].args[1] == (
        'device-a', 'device-b', 'device-a', 'device-b'
    )
    conn.commit.assert_called_once()
    rebuild.assert_called_once_with()


def test_discovery_history_reset_removes_only_selected_source_lldp_rows(isolated_db):
    from services.topology_service import _clear_lldp_observation_history_for_run

    conn = get_db_connection()
    try:
        for device_id, hostname in (
            ('device-a', 'S6850-1'),
            ('device-b', 'S6850-2'),
            ('device-c', 'S6850-3'),
        ):
            conn.execute(
                """INSERT INTO devices (id, hostname, ip_address, platform, status)
                   VALUES (?, ?, ?, 'hp_comware', 'online')""",
                (device_id, hostname, f'10.254.0.{device_id[-1]}'),
            )
        for source_id, neighbor in (('device-a', 'S6850-2'), ('device-b', 'S6850-3')):
            conn.execute(
                """INSERT INTO topology_observations (
                       id, source_device_id, neighbor_name_raw, neighbor_name_normalized,
                       protocol, collected_at, updated_at, is_active
                   ) VALUES (?, ?, ?, ?, 'lldp', '2026-10-01T00:00:00+00:00',
                             '2026-10-01T00:00:00+00:00', 1)""",
                (f'observation-{source_id}', source_id, neighbor, neighbor.lower()),
            )
            conn.execute(
                """INSERT INTO topology_protocol_observations (
                       id, source_device_id, protocol, first_seen, last_seen,
                       created_at, updated_at
                   ) VALUES (?, ?, 'lldp', '2026-10-01T00:00:00+00:00',
                             '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00',
                             '2026-10-01T00:00:00+00:00')""",
                (f'protocol-{source_id}', source_id),
            )
        conn.execute(
            """INSERT INTO topology_links (
                   id, link_key, source_device_id, source_hostname, target_device_id,
                   target_hostname, discovery_source
               ) VALUES ('link-a-b', 'key-a-b', 'device-a', 'S6850-1',
                         'device-b', 'S6850-2', 'lldp')"""
        )
        conn.execute(
            """INSERT INTO topology_links (
                   id, link_key, source_device_id, source_hostname, target_device_id,
                   target_hostname, discovery_source
               ) VALUES ('link-b-c', 'key-b-c', 'device-b', 'S6850-2',
                         'device-c', 'S6850-3', 'lldp')"""
        )
        conn.commit()
    finally:
        conn.close()

    with patch('services.topology_service.rebuild_links_from_observations'):
        _clear_lldp_observation_history_for_run(['device-a'])

    conn = get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM topology_observations WHERE source_device_id = 'device-a'"
        ).fetchone()['n'] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM topology_observations WHERE source_device_id = 'device-b'"
        ).fetchone()['n'] == 1
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM topology_protocol_observations WHERE source_device_id = 'device-a'"
        ).fetchone()['n'] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM topology_protocol_observations WHERE source_device_id = 'device-b'"
        ).fetchone()['n'] == 1
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM topology_links WHERE id = 'link-a-b'"
        ).fetchone()['n'] == 0
        assert conn.execute(
            "SELECT COUNT(*) AS n FROM topology_links WHERE id = 'link-b-c'"
        ).fetchone()['n'] == 1
    finally:
        conn.close()
