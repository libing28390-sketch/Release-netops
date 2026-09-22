import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from services.snmp_service import collect_snmp_lldp_neighbors
from services.topology_service import _collect_device_observations


def test_collect_snmp_lldp_requires_explicit_community():
    """LLDP must not silently fall back to the public community."""
    with pytest.raises(ValueError, match='SNMP community is required'):
        asyncio.run(collect_snmp_lldp_neighbors('10.10.10.1', ''))


def test_collect_snmp_lldp_neighbors_success():
    """Test IEEE 802.1AB LLDP-MIB walk parses local port, neighbor name, remote port, and mgmt IP."""
    async def mock_walk(ip, community, oid, port=161, timeout=4.0, version='2c'):
        if oid == '1.0.8802.1.1.2.1.4.1.1.9': # lldpRemSysName
            return [('0.1.1', 'SW-CORE-B.corp.local')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.7': # lldpRemPortId
            return [('0.1.1', 'GigabitEthernet0/0/24')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.8': # lldpRemPortDesc
            return [('0.1.1', 'Uplink to Core A')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.2': # lldpRemChassisId
            return [('0.1.1', '00:11:22:33:44:55')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.10': # lldpRemSysDesc
            return [('0.1.1', 'Huawei Versatile Routing Platform Software')]
        elif oid == '1.0.8802.1.1.2.1.4.2.1': # lldpRemManAddrTable
            return [('1.0.1.1.1.4.10.10.10.2', '1')]
        elif oid == '1.0.8802.1.1.2.1.3.7.1.3': # lldpLocPortId
            return [('1', 'GigabitEthernet0/0/1')]
        elif oid == '1.3.6.1.2.1.31.1.1.1.1': # ifName
            return [('1', 'GE0/0/1')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        neighbors = asyncio.run(collect_snmp_lldp_neighbors('10.10.10.1', 'public'))
        assert len(neighbors) == 1
        n = neighbors[0]
        assert n['protocol'] == 'lldp'
        assert n['local_interface'] == 'GigabitEthernet0/0/1'
        assert n['neighbor_name'] == 'SW-CORE-B'
        assert n['neighbor_interface'] == 'GigabitEthernet0/0/24'
        assert n['mgmt_address'] == '10.10.10.2'
        assert 'Huawei' in n['neighbor_platform']


def test_collect_snmp_cdp_fallback_when_lldp_empty():
    """Test fallback to CISCO-CDP-MIB when LLDP returns no entries."""
    async def mock_walk(ip, community, oid, port=161, timeout=4.0, version='2c'):
        if oid.startswith('1.0.8802.'):
            return []
        if oid == '1.3.6.1.4.1.9.9.23.1.2.1.1.6': # cdpCacheDeviceId
            return [('1.1', 'CISCO-CATALYST-3850')]
        elif oid == '1.3.6.1.4.1.9.9.23.1.2.1.1.7': # cdpCacheDevicePort
            return [('1.1', 'TenGigabitEthernet1/1/1')]
        elif oid == '1.3.6.1.4.1.9.9.23.1.2.1.1.8': # cdpCachePlatform
            return [('1.1', 'cisco WS-C3850-24T')]
        elif oid == '1.3.6.1.4.1.9.9.23.1.2.1.1.4': # cdpCacheAddress
            return [('1.1', '192.168.100.5')]
        elif oid == '1.3.6.1.2.1.31.1.1.1.1': # ifName
            return [('1', 'TenGigabitEthernet1/0/1')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        neighbors = asyncio.run(collect_snmp_lldp_neighbors('192.168.100.1', 'cisco-ro'))
        assert len(neighbors) == 1
        n = neighbors[0]
        assert n['protocol'] == 'cdp'
        assert n['local_interface'] == 'TenGigabitEthernet1/0/1'
        assert n['neighbor_name'] == 'CISCO-CATALYST-3850'
        assert n['neighbor_interface'] == 'TenGigabitEthernet1/1/1'
        assert n['mgmt_address'] == '192.168.100.5'
        assert 'cisco' in n['neighbor_platform'].lower()


def test_topology_service_collects_snmp_first():
    """Test _collect_device_observations uses SNMP and bypasses SSH when SNMP neighbors exist."""
    device = {
        'id': 'dev-test-1',
        'hostname': 'Switch-A',
        'ip_address': '10.20.30.40',
        'platform': 'huawei_vrp',
        'snmp_community': 'test-comm',
        'snmp_port': 161,
        'management_port': 22,
    }

    mock_snmp_neighbors = [{
        'protocol': 'lldp',
        'local_interface': 'GigabitEthernet0/0/1',
        'neighbor_name': 'Switch-B',
        'neighbor_interface': 'GigabitEthernet0/0/2',
        'mgmt_address': '10.20.30.41',
        'chassis_id': 'aa:bb:cc:dd:ee:ff',
        'neighbor_platform': 'Huawei',
    }]

    mock_collect = AsyncMock(return_value=mock_snmp_neighbors)
    resolved_credentials = {
        'ssh': {},
        'snmp': {
            'server': '10.20.30.40',
            'community': 'asset-template-community',
            'port': 1161,
            'version': '2c',
        },
    }

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials) as mock_resolve:
        with patch('services.snmp_service.collect_snmp_lldp_neighbors', new=mock_collect):
            with patch('drivers.ssh_compat.is_ssh_port_open') as mock_ssh_check:
                batch, method = asyncio.run(_collect_device_observations(device))
                assert method == 'snmp'
                assert len(batch) == 1
                assert batch.collection_status == 'success'
                obs = batch[0]
                assert obs['neighbor_name_raw'] == 'Switch-B'
                assert obs['source_port_raw'] == 'GigabitEthernet0/0/1'
                mock_ssh_check.assert_not_called()

    mock_resolve.assert_called_once_with(device, ssh_role='normal')
    mock_collect.assert_awaited_once_with(
        '10.20.30.40',
        'asset-template-community',
        port=1161,
        version='2c',
    )


def test_match_target_device_relaxed_delimiter():
    """Test _match_target_device_with_evidence matches S6850_1 to S6850-1."""
    from services.topology_service import _match_target_device_with_evidence
    from unittest.mock import MagicMock

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {'id': 'dev-1', 'hostname': 'S6850-1', 'ip_address': '10.254.0.1', 'sys_name': '', 'sn': '', 'model': 'S6850', 'site_id': 'site-1'}
    ]

    res = _match_target_device_with_evidence(mock_conn, 'S6850_1', '10.254.100.4', '')
    assert res['status'] == 'matched'
    assert res['method'] == 'system_name_relaxed'
    assert res['device']['id'] == 'dev-1'


def test_get_unmanaged_neighbors_filters_stale():
    """Test get_unmanaged_neighbors filters out stale observations when include_stale=False."""
    from services.topology_service import get_unmanaged_neighbors
    from unittest.mock import MagicMock

    with patch('services.topology_service.get_db_connection') as mock_get_conn:
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        get_unmanaged_neighbors(include_stale=False)
        called_sql = mock_conn.execute.call_args[0][0]
        assert "COALESCE(o.is_active, 1) = 1" in called_sql
        assert "COALESCE(o.status, 'active') <> 'stale'" in called_sql

        get_unmanaged_neighbors(include_stale=True)
        called_sql_stale = mock_conn.execute.call_args[0][0]
        assert "COALESCE(o.is_active, 1) = 1" not in called_sql_stale


def test_collect_snmp_lldp_prefers_port_id_over_description():
    """Verify that lldpRemPortId (e.g. GigabitEthernet1/0/1) is preferred over description (e.g. TO-S6850-4-GE1/0/1)."""
    from services.snmp_service import collect_snmp_lldp_neighbors

    async def mock_walk(ip, community, oid, port=161, timeout=4.0, version='2c'):
        if oid == '1.0.8802.1.1.2.1.3.7.1.3': # lldpLocPortId
            return [('1', 'GigabitEthernet1/0/1')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.9': # lldpRemSysName
            return [('0.1.1', 'S6850-4')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.7': # lldpRemPortId (Standard Port ID)
            return [('0.1.1', 'GigabitEthernet1/0/1')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.8': # lldpRemPortDesc (User description)
            return [('0.1.1', 'TO-S6850-4-GE1/0/1')]
        elif oid == '1.0.8802.1.1.2.1.4.1.1.2': # lldpRemChassisId
            return [('0.1.1', '8e44-40f8-0400')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        neighbors = asyncio.run(collect_snmp_lldp_neighbors('10.254.0.3', 'public'))
        assert len(neighbors) == 1
        neighbor = neighbors[0]
        # Must prefer the standard GigabitEthernet1/0/1 over TO-S6850-4-GE1/0/1
        assert neighbor['neighbor_interface'] == 'GigabitEthernet1/0/1'
        assert neighbor['neighbor_name'] == 'S6850-4'


