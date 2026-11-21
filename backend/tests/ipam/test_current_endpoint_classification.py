"""Current ARP rows need evidence classes before they can be called hosts."""

from services.ipam_discovery_service import (
    _classify_current_endpoint_rows,
    _current_infrastructure_ip_keys,
)


def _arp(ip: str, mac: str, vlan: str = '7') -> dict:
    return {
        'ip': ip, 'mac': mac, 'vlan': vlan, 'tenant_id': 'tenant-default',
        'site_id': 'site-a', 'source_device_id': 'switch-a',
        'context_source': 'snmp', 'context_type': 'unknown', 'local_context_key': '',
        'evidence_status': 'recent', 'coverage_complete': True,
    }


def _fdb(mac: str, *, vlan: str = '7', path: str = 'access_edge') -> dict:
    return {
        'mac': mac, 'vlan': vlan, 'tenant_id': 'tenant-default',
        'site_id': 'site-a', 'source_device_id': 'switch-a',
        'context_source': 'snmp', 'context_type': 'unknown', 'local_context_key': '',
        'path_classification': path, 'path_ambiguity': False,
        'evidence_status': 'recent', 'coverage_complete': True,
        'switch_id': 'switch-a', 'switch_name': 'SW-A', 'switch_port': 'GE1/0/2',
    }


def test_current_arp_classification_requires_access_path_and_excludes_infrastructure():
    rows = [
        _arp('10.0.0.1', '02:00:00:00:00:01'),
        _arp('10.0.0.2', '02:00:00:00:00:02'),
        _arp('10.0.0.3', '00:00:5e:00:01:14'),
        _arp('10.0.0.4', '02:00:00:00:00:04'),
        _arp('10.0.0.5', '02:00:00:00:00:05'),
        _arp('10.0.0.6', '02:00:00:00:00:06'),
        _arp('10.0.0.7', '02:00:00:00:00:07'),
    ]
    fdb = [
        _fdb('00:00:5e:00:01:14'),
        _fdb('02:00:00:00:00:05'),
        _fdb('02:00:00:00:00:06', vlan='8'),
        _fdb('02:00:00:00:00:07', path='trunk_tagged_interface'),
    ]
    _classify_current_endpoint_rows(
        rows, fdb,
        {('tenant-default', 'site-a', '10.0.0.1')},
        {('tenant-default', 'site-a', '10.0.0.2')},
        {('tenant-default', '10.0.0.2'), ('tenant-default', '10.0.0.4')},
    )

    assert [item['endpoint_class'] for item in rows] == [
        'infrastructure', 'infrastructure', 'infrastructure', 'infrastructure',
        'access_host', 'candidate', 'candidate',
    ]
    assert rows[3]['endpoint_class_reason'] == 'managed_device_site_mismatch'
    assert rows[4]['switch_port'] == 'GE1/0/2'
    assert rows[4]['path_classification'] == 'access_edge'
    assert not rows[5].get('switch_port')


def test_infrastructure_catalog_respects_visible_sites(monkeypatch):
    monkeypatch.setattr(
        'services.ipam_service._current_cmdb_interface_ip_observations',
        lambda _conn: [],
    )

    class Connection:
        def execute(self, _sql):
            return self

        def fetchall(self):
            return [
                {'tenant_id': 'tenant-default', 'site_id': 'site-a', 'ip_address': '10.0.0.1'},
                {'tenant_id': 'tenant-default', 'site_id': 'site-b', 'ip_address': '10.0.0.2'},
            ]

    _, managed, managed_addresses = _current_infrastructure_ip_keys(
        Connection(), {('tenant-default', 'site-a')},
    )
    assert managed == {('tenant-default', 'site-a', '10.0.0.1')}
    assert managed_addresses == {('tenant-default', '10.0.0.1')}
