import asyncio
import sqlite3

from services import collection_diagnostics_service as diagnostics
from services import interface_collection_service as interfaces


class _ConnectionProxy:
    def __init__(self, connection):
        self._connection = connection

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        # Keep the in-memory connection available for assertions.
        return None


def test_interface_snapshot_clears_missing_current_rows(monkeypatch):
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE interfaces (
            id TEXT PRIMARY KEY, device_id TEXT, interface_name TEXT, description TEXT,
            admin_status TEXT, oper_status TEXT, primary_ip TEXT,
            ip_address TEXT, ip_prefix_length INTEGER, is_l3 INTEGER,
            ip_enabled INTEGER, switchport_mode TEXT, interface_type TEXT,
            last_seen TEXT
        );
        INSERT INTO interfaces VALUES
            ('old', 'dev-1', 'Ethernet0/2', '', 'up', 'up', '10.0.0.2', '10.0.0.2', 24, 1, 1, 'routed', 'physical', NULL),
            ('current', 'dev-1', 'LoopBack0', '', 'down', 'down', '10.0.0.9', '10.0.0.9', 32, 1, 1, 'routed', 'physical', NULL);
        """
    )
    monkeypatch.setattr(interfaces, 'get_db_connection', lambda: _ConnectionProxy(connection))

    updated = interfaces._upsert_interfaces(
        {'id': 'dev-1'},
        [{
            'interface_name': 'Loop0',
            'interface_ip': '10.0.0.10',
            'prefix_length': 32,
            'admin_status': 'up',
            'oper_status': 'up',
        }],
    )

    assert updated == 1
    stale = dict(connection.execute("SELECT * FROM interfaces WHERE id = 'old'").fetchone())
    assert stale['primary_ip'] == ''
    assert stale['ip_enabled'] == 0
    assert stale['oper_status'] == 'unknown'
    current = dict(connection.execute("SELECT * FROM interfaces WHERE id = 'current'").fetchone())
    assert current['interface_name'] == 'LoopBack0'
    assert current['primary_ip'] == '10.0.0.10'
    assert current['last_seen']


def test_device_ip_output_supersedes_legacy_inventory_rows():
    records = [
        {'interface': 'GE1/0/1', 'main_ip': '10.0.0.1', 'link': 'UP', 'protocol': 'UP'},
        {'interface': 'GE1/0/2', 'main_ip': '--', 'link': 'DOWN', 'protocol': 'DOWN'},
    ]
    inventory = {'gi1/0/1': {'ip': '10.0.0.1'}, 'gi1/0/2': {'ip': '10.0.0.2'}}

    direct_ip_keys = set()
    for record in records:
        interface_name, direct_ip, _, _ = interfaces._status_record(record, {})
        key = interfaces.normalize_interface_name(interface_name)
        if direct_ip:
            direct_ip_keys.add(key)

    assert direct_ip_keys == {'gi1/0/1'}
    assert 'gi1/0/2' not in direct_ip_keys


def test_interface_description_uses_dedicated_textfsm_field_and_rejects_mtu_text():
    assert interfaces._interface_description({
        'INTERFACE': 'Vlanif10',
        'DESCRIPTION': 'Finance gateway',
    }) == 'Finance gateway'
    assert interfaces._interface_description({
        'INTERFACE': 'Vlanif10',
        'DESCRIPTION': 'Route Port,The Maximum Transmit Unit is 1500',
    }) == ''


def test_diagnostics_uses_management_port_column(monkeypatch):
    query = ''

    class Cursor:
        def fetchone(self):
            return {
                'id': 'dev-1', 'hostname': 'R1', 'ip_address': '192.0.2.1',
                'management_port': 22, 'snmp_port': 161, 'username': '',
                'password': '', 'credential_id': '', 'credential_source': '',
                'asset_id': '', 'snmp_community': 'public',
            }

    class Connection:
        def execute(self, sql, params):
            nonlocal query
            query = sql
            return Cursor()

        def close(self):
            return None

    async def fake_tcp(host, port, timeout):
        return 'success', '1'

    async def fake_snmp(host, community, oid, port, timeout):
        return 'uptime'

    monkeypatch.setattr(diagnostics, 'get_db_connection', lambda: Connection())
    monkeypatch.setattr(diagnostics, 'resolve_collector_credentials', lambda device, ssh_role='normal': {
        'ssh': {'port': 22, 'username': 'admin', 'password': 'secret'},
        'snmp': {'port': 161, 'community': 'public'},
    })
    monkeypatch.setattr(diagnostics, '_dns_probe', lambda host: {'status': 'success'})
    monkeypatch.setattr(diagnostics, '_tcp_probe', fake_tcp)
    monkeypatch.setattr(diagnostics, '_snmp_get', fake_snmp)
    monkeypatch.setattr(diagnostics, 'record_collection_result', lambda *args, **kwargs: None)

    result = asyncio.run(diagnostics.diagnose_device_collection('dev-1'))

    assert result['status'] == 'success'
    assert 'management_port, port' not in query
    assert 'management_port, snmp_port' in query
