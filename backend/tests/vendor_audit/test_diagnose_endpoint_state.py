import asyncio
import sqlite3

from services import diagnose_service


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE network_endpoints (
            ip TEXT, mac TEXT, hostname TEXT, switch_id TEXT, switch_port TEXT,
            last_seen TEXT, is_active INTEGER
        );
        CREATE TABLE devices (
            id TEXT PRIMARY KEY, hostname TEXT, ip_address TEXT, platform TEXT
        );
        CREATE TABLE interfaces (
            device_id TEXT, interface_name TEXT, admin_status TEXT,
            oper_status TEXT, last_seen TEXT
        );
        CREATE TABLE interface_telemetry_raw (
            device_id TEXT, interface_name TEXT, status TEXT, ts TEXT
        );
        """
    )


def test_persisted_endpoint_port_down_wins_over_aliases() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _schema(conn)
    conn.execute("INSERT INTO devices VALUES ('sw6', 'LSW6', '10.0.0.6', 'huawei_vrp')")
    conn.execute("INSERT INTO interfaces VALUES ('sw6', 'GigabitEthernet0/0/1', 'down', 'down', '2026-07-27T10:00:00+08:00')")
    conn.execute("INSERT INTO network_endpoints VALUES ('10.253.10.10', 'aabb.ccdd.eeff', '', 'sw6', 'GE0/0/1', '2026-07-27T09:00:00+08:00', 1)")

    state = diagnose_service._persisted_interface_state(conn, 'sw6', 'GE0/0/1')

    assert state['state'] == 'down'
    assert state['interface_name'] == 'GigabitEthernet0/0/1'


def test_live_down_snapshot_overrides_historical_endpoint(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _schema(conn)
    conn.execute("INSERT INTO devices VALUES ('sw6', 'LSW6', '10.0.0.6', 'huawei_vrp')")
    conn.execute("INSERT INTO interfaces VALUES ('sw6', 'GE0/0/1', 'up', 'up', '2026-07-27T09:00:00+08:00')")
    conn.execute("INSERT INTO network_endpoints VALUES ('10.253.10.10', 'aabb.ccdd.eeff', '', 'sw6', 'GE0/0/1', '2026-07-27T09:00:00+08:00', 1)")

    async def fake_refresh(endpoint):
        return {
            'state': 'down',
            'source': 'live_textfsm',
            'device_id': 'sw6',
            'device_name': 'LSW6',
            'interface_name': 'GigabitEthernet0/0/1',
            'admin_status': 'down',
            'oper_status': 'down',
        }

    monkeypatch.setattr(diagnose_service, '_refresh_endpoint_interface_state', fake_refresh)
    state = asyncio.run(diagnose_service._evaluate_endpoint_attachment(conn, '10.253.10.10'))

    assert state['state'] == 'down'
    assert state['source'] == 'live_textfsm'
    assert state['device_name'] == 'LSW6'
