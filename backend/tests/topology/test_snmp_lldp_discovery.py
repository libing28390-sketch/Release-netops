import asyncio
import pytest
from unittest.mock import patch, AsyncMock

from services.snmp_service import collect_snmp_lldp_neighbors
from services.topology_service import (
    _NeighborCollectionBatch,
    _collect_device_observations,
    _combine_protocol_observations,
)


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
        elif oid == '1.0.8802.1.1.2.1.4.1.1.5': # lldpRemChassisId
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
        assert n['chassis_id'] == '00:11:22:33:44:55'
        assert 'Huawei' in n['neighbor_platform']


def test_collect_snmp_lldp_returns_empty_when_lldp_is_unavailable():
    """SNMP collection stays LLDP-only so the caller can fall back to CLI LLDP."""
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
        assert neighbors == []


@pytest.mark.parametrize('platform', ['cisco_ios', 'huawei_vrp', 'h3c_comware'])
def test_topology_service_collects_snmp_first_without_cli_probe(platform):
    """A complete SNMP snapshot must not open or invoke the SSH collector."""
    device = {
        'id': 'dev-test-1',
        'hostname': 'Switch-A',
        'ip_address': '10.20.30.40',
        'platform': platform,
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
        'ssh': {'username': 'operator', 'password': 'test-only'},
        'snmp': {
            'configured': True,
            'server': '10.20.30.40',
            'community': 'asset-template-community',
            'port': 1161,
            'version': '2c',
        },
    }

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials) as mock_resolve:
        with patch('services.snmp_service.collect_snmp_lldp_neighbors', new=mock_collect):
            with patch('drivers.ssh_compat.is_ssh_port_open') as mock_ssh_check:
                with patch(
                    'services.topology_service._collect_neighbors_with_netmiko',
                    new=AsyncMock(),
                ) as mock_ssh_collection:
                    attempted_methods = []
                    batch, method = asyncio.run(
                        _collect_device_observations(device, attempted_methods=attempted_methods)
                    )

    assert method == 'snmp'
    assert len(batch) == 1
    assert batch.collection_status == 'success'
    obs = batch[0]
    assert obs['neighbor_name_raw'] == 'Switch-B'
    assert obs['source_port_raw'] == 'GigabitEthernet0/0/1'
    assert attempted_methods == ['snmp']
    assert batch.protocol_results['snmp'] == {
        'status': 'success',
        'detail': '',
        'observations_count': 1,
    }
    assert batch.protocol_results['ssh'] == {
        'status': 'not_attempted',
        'detail': 'SNMP LLDP complete; CLI fallback not needed',
        'observations_count': 0,
    }
    mock_ssh_check.assert_not_called()
    mock_ssh_collection.assert_not_awaited()

    mock_resolve.assert_called_once_with(device, ssh_role='normal')
    mock_collect.assert_awaited_once_with(
        '10.20.30.40',
        'asset-template-community',
        port=1161,
        version='2c',
        timeout=30.0,
        max_rows=None,
    )


def test_topology_service_returns_normal_empty_snmp_snapshot_without_cli():
    device = {
        'id': 'dev-empty-snmp',
        'hostname': 'Switch-empty',
        'ip_address': '10.20.30.40',
        'platform': 'huawei_vrp',
        'management_port': 22,
    }
    resolved_credentials = {
        'ssh': {'username': 'operator', 'password': 'test-only'},
        'snmp': {'configured': True, 'server': '10.20.30.40', 'community': 'test-only', 'port': 161, 'version': '2c'},
    }
    attempted_methods = []

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials):
        with patch('services.snmp_service.collect_snmp_lldp_neighbors', new=AsyncMock(return_value=[])):
            with patch('drivers.ssh_compat.is_ssh_port_open') as mock_ssh_check:
                with patch(
                    'services.topology_service._collect_neighbors_with_netmiko',
                    new=AsyncMock(),
                ) as mock_ssh_collection:
                    batch, method = asyncio.run(
                        _collect_device_observations(device, attempted_methods=attempted_methods)
                    )

    assert method == 'snmp'
    assert list(batch) == []
    assert batch.collection_status == 'no_neighbors'
    assert attempted_methods == ['snmp']
    assert batch.protocol_results['snmp']['status'] == 'no_neighbors'
    assert batch.protocol_results['ssh'] == {
        'status': 'not_attempted',
        'detail': 'SNMP LLDP complete; CLI fallback not needed',
        'observations_count': 0,
    }
    mock_ssh_check.assert_not_called()
    mock_ssh_collection.assert_not_awaited()


def test_topology_service_falls_back_to_cli_after_snmp_exception():
    device = {
        'id': 'dev-snmp-error',
        'hostname': 'Switch-error',
        'ip_address': '10.20.30.40',
        'platform': 'huawei_vrp',
        'management_port': 22,
    }
    cli_batch = _NeighborCollectionBatch([{
        'source_port_raw': 'GigabitEthernet0/0/1',
        'neighbor_name_raw': 'Switch-B',
        'neighbor_ip_address': '10.20.30.41',
        'target_port_raw': 'GigabitEthernet0/0/2',
        'protocol': 'lldp',
    }], 'success')
    resolved_credentials = {
        'ssh': {'username': 'operator', 'password': 'test-only'},
        'snmp': {'configured': True, 'server': '10.20.30.40', 'community': 'test-only', 'port': 161, 'version': '2c'},
    }
    attempted_methods = []

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials):
        with patch(
            'services.snmp_service.collect_snmp_lldp_neighbors',
            new=AsyncMock(side_effect=RuntimeError('snmp_lldp_walk_failed: timeout')),
        ):
            with patch('drivers.ssh_compat.is_ssh_port_open', return_value=True) as mock_ssh_check:
                with patch(
                    'services.topology_service._collect_neighbors_with_netmiko',
                    new=AsyncMock(return_value=(cli_batch, 'netmiko')),
                ) as mock_ssh_collection:
                    batch, method = asyncio.run(
                        _collect_device_observations(device, attempted_methods=attempted_methods)
                    )

    assert method == 'netmiko'
    assert batch.collection_status == 'success'
    assert attempted_methods == ['snmp', 'ssh']
    assert batch.protocol_results['snmp']['status'] == 'failed'
    assert batch.protocol_results['ssh']['status'] == 'success'
    mock_ssh_check.assert_called_once_with('10.20.30.40', 22)
    mock_ssh_collection.assert_awaited_once()


def test_topology_service_falls_back_to_cli_for_unusable_snmp_records():
    device = {
        'id': 'dev-unusable-snmp',
        'hostname': 'Switch-unusable',
        'ip_address': '10.20.30.40',
        'platform': 'huawei_vrp',
        'management_port': 22,
    }
    cli_batch = _NeighborCollectionBatch([{
        'source_port_raw': 'GigabitEthernet0/0/1',
        'neighbor_name_raw': 'Switch-B',
        'neighbor_ip_address': '10.20.30.41',
        'target_port_raw': 'GigabitEthernet0/0/2',
        'protocol': 'lldp',
    }], 'success')
    resolved_credentials = {
        'ssh': {'username': 'operator', 'password': 'test-only'},
        'snmp': {'configured': True, 'server': '10.20.30.40', 'community': 'test-only', 'port': 161, 'version': '2c'},
    }
    attempted_methods = []
    unusable_snmp_records = [{
        'protocol': 'lldp',
        'local_interface': '',
        'neighbor_name': '',
        'neighbor_interface': '',
        'mgmt_address': '',
        'chassis_id': '',
    }]

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials):
        with patch(
            'services.snmp_service.collect_snmp_lldp_neighbors',
            new=AsyncMock(return_value=unusable_snmp_records),
        ):
            with patch('drivers.ssh_compat.is_ssh_port_open', return_value=True) as mock_ssh_check:
                with patch(
                    'services.topology_service._collect_neighbors_with_netmiko',
                    new=AsyncMock(return_value=(cli_batch, 'netmiko')),
                ) as mock_ssh_collection:
                    batch, method = asyncio.run(
                        _collect_device_observations(device, attempted_methods=attempted_methods)
                    )

    assert method == 'netmiko'
    assert batch.collection_status == 'success'
    assert attempted_methods == ['snmp', 'ssh']
    assert batch.protocol_results['snmp'] == {
        'status': 'no_neighbors',
        'detail': 'no_usable_neighbors',
        'observations_count': 0,
    }
    assert batch.protocol_results['ssh']['status'] == 'success'
    mock_ssh_check.assert_called_once_with('10.20.30.40', 22)
    mock_ssh_collection.assert_awaited_once()


def test_topology_service_keeps_snmp_neighbor_with_management_ip_but_no_name():
    device = {
        'id': 'dev-test-ip-only',
        'hostname': 'Switch-A',
        'ip_address': '10.20.30.40',
        'platform': 'huawei_vrp',
    }
    mock_collect = AsyncMock(return_value=[{
        'protocol': 'lldp',
        'local_interface': 'GigabitEthernet0/0/1',
        'neighbor_name': '',
        'neighbor_interface': 'GigabitEthernet0/0/2',
        'mgmt_address': '10.20.30.41',
        'chassis_id': '',
    }])
    resolved_credentials = {
        'ssh': {},
        'snmp': {'configured': True, 'server': '10.20.30.40', 'community': 'public', 'port': 161, 'version': '2c'},
    }

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials):
        with patch('services.snmp_service.collect_snmp_lldp_neighbors', new=mock_collect):
            with patch('drivers.ssh_compat.is_ssh_port_open') as mock_ssh_check:
                batch, method = asyncio.run(_collect_device_observations(device))

    assert method == 'snmp'
    assert len(batch) == 1
    assert batch[0]['neighbor_ip_address'] == '10.20.30.41'
    mock_ssh_check.assert_not_called()


def test_topology_service_combines_partial_snmp_with_complete_ssh_snapshot():
    device = {
        'id': 'dev-partial-snmp',
        'hostname': 'S6850-1',
        'ip_address': '10.254.0.1',
        'platform': 'h3c_comware',
        'management_port': 22,
    }
    partial_snmp = _NeighborCollectionBatch([{
        'source_port_raw': 'Ten-GigabitEthernet1/0/49',
        'neighbor_name_raw': 'S6850_2',
        'neighbor_ip_address': '10.254.100.5',
        'target_port_raw': 'Ten-GigabitEthernet1/0/49',
        'protocol': 'lldp',
    }], 'partial')
    complete_ssh = _NeighborCollectionBatch([{
        'source_port_raw': 'Ten-GigabitEthernet1/0/49',
        'neighbor_name_raw': 'S6850-2',
        'neighbor_ip_address': '',
        'target_port_raw': 'Ten-GigabitEthernet1/0/49',
        'protocol': 'lldp',
    }], 'success')
    resolved_credentials = {
        'ssh': {'username': 'operator', 'password': 'test-only'},
        'snmp': {'configured': True, 'server': '10.254.0.1', 'community': 'test-only', 'port': 161, 'version': '2c'},
    }
    attempted_methods = []

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials):
        with patch('services.snmp_service.collect_snmp_lldp_neighbors', new=AsyncMock(return_value=partial_snmp)):
            with patch('drivers.ssh_compat.is_ssh_port_open', return_value=True):
                with patch(
                    'services.topology_service._collect_neighbors_with_netmiko',
                    new=AsyncMock(return_value=(complete_ssh, 'netmiko')),
                ) as mock_ssh_collection:
                    batch, method = asyncio.run(
                        _collect_device_observations(device, attempted_methods=attempted_methods)
                    )

    assert method == 'hybrid'
    assert batch.collection_status == 'success'
    assert len(batch) == 1
    assert batch[0]['neighbor_name_raw'] == 'S6850-2'
    assert batch[0]['neighbor_ip_address'] == '10.254.100.5'
    assert batch[0]['collection_sources'] == ['snmp', 'ssh']
    assert batch.protocol_results['snmp']['status'] == 'partial'
    assert batch.protocol_results['snmp']['observations_count'] == 1
    assert batch.protocol_results['ssh']['status'] == 'success'
    assert batch.protocol_results['ssh']['observations_count'] == 1
    assert attempted_methods == ['snmp', 'ssh']
    mock_ssh_collection.assert_awaited_once()


def test_topology_service_keeps_conflicting_protocol_ips_as_separate_evidence():
    snmp_observation = {
        'source_port_raw': 'Ten-GigabitEthernet1/0/49',
        'source_port_normalized': 'tengige1/0/49',
        'neighbor_name_raw': 'S6850-2',
        'neighbor_name_normalized': 's6850-2',
        'neighbor_ip_address': '10.254.100.5',
        'target_port_raw': 'Ten-GigabitEthernet1/0/49',
        'target_port_normalized': 'tengige1/0/49',
        'protocol': 'lldp',
    }
    cli_observation = {
        **snmp_observation,
        'neighbor_ip_address': '10.254.0.2',
    }

    combined = _combine_protocol_observations([snmp_observation], [cli_observation])

    assert len(combined) == 2
    assert {item['neighbor_ip_address'] for item in combined} == {'10.254.100.5', '10.254.0.2'}


def test_topology_service_preserves_partial_snmp_when_ssh_fallback_fails():
    device = {
        'id': 'dev-partial-snmp-ssh-failed',
        'hostname': 'S6850-1',
        'ip_address': '10.254.0.1',
        'platform': 'h3c_comware',
        'management_port': 22,
    }
    partial_snmp = _NeighborCollectionBatch([{
        'source_port_raw': 'Ten-GigabitEthernet1/0/49',
        'neighbor_name_raw': 'S6850-2',
        'neighbor_ip_address': '10.254.100.5',
        'target_port_raw': 'Ten-GigabitEthernet1/0/49',
        'protocol': 'lldp',
    }], 'partial')
    resolved_credentials = {
        'ssh': {'username': 'operator', 'password': 'test-only'},
        'snmp': {'configured': True, 'server': '10.254.0.1', 'community': 'test-only', 'port': 161, 'version': '2c'},
    }

    with patch('services.topology_service.resolve_collector_credentials', return_value=resolved_credentials):
        with patch('services.snmp_service.collect_snmp_lldp_neighbors', new=AsyncMock(return_value=partial_snmp)):
            with patch('drivers.ssh_compat.is_ssh_port_open', return_value=True):
                with patch(
                    'services.topology_service._collect_neighbors_with_netmiko',
                    new=AsyncMock(side_effect=RuntimeError('ssh_authentication_failed')),
                ):
                    batch, method = asyncio.run(_collect_device_observations(device))

    assert method == 'snmp'
    assert batch.collection_status == 'partial'
    assert len(batch) == 1
    assert batch[0]['neighbor_ip_address'] == '10.254.100.5'
    assert batch.protocol_results['snmp']['status'] == 'partial'
    assert batch.protocol_results['ssh']['status'] == 'failed'


def test_match_target_device_accepts_separator_variant_hostname():
    """A separator-only LLDP hostname variant resolves to the canonical device."""
    from services.topology_service import _match_target_device_with_evidence
    from unittest.mock import MagicMock

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        {'id': 'dev-1', 'device_hostname': 'S6850-1', 'asset_hostname': 'S6850-1', 'ip_address': '10.254.0.1', 'sys_name': '', 'sn': '', 'model': 'S6850', 'site_id': 'site-1'}
    ]

    res = _match_target_device_with_evidence(mock_conn, 'S6850_1', '', '')

    assert res['device']['id'] == 'dev-1'
    assert res['device']['ip_address'] == '10.254.0.1'
    assert res['status'] == 'matched'


@pytest.mark.parametrize('index', [1, 2, 3, 4])
def test_match_target_device_accepts_confirmed_hcl_underscore_aliases(index):
    """HCL LLDP names S6850_1..4 resolve to CMDB S6850-1..4 devices."""
    from services.topology_service import _match_target_device_with_evidence

    device_rows = [
        {
            'id': f'device-{device_index}',
            'hostname': f'S6850-{device_index}',
            'ip_address': f'10.254.0.{device_index}',
            'sn': '',
        }
        for device_index in range(1, 5)
    ]
    result = _match_target_device_with_evidence(
        None,
        f'S6850_{index}',
        '',
        device_rows=device_rows,
    )

    assert result['device']['id'] == f'device-{index}'
    assert result['device']['ip_address'] == f'10.254.0.{index}'
    assert result['status'] == 'matched'
    assert result['method'] == 'system_name_separator_normalized'


def test_match_target_device_rejects_ambiguous_separator_variant_hostname():
    """A separator-normalized collision must not select an arbitrary device."""
    from services.topology_service import _match_target_device_with_evidence

    res = _match_target_device_with_evidence(
        None,
        'S6850_1',
        '',
        device_rows=[
            {'id': 'dev-1', 'hostname': 'S6850-1', 'ip_address': '10.254.0.1', 'sn': ''},
            {'id': 'dev-2', 'hostname': 'S6850.1', 'ip_address': '10.254.0.2', 'sn': ''},
        ],
    )

    assert res['status'] == 'ambiguous'
    assert res['device'] is None


@pytest.mark.parametrize('index', [1, 2, 3, 4])
def test_match_target_device_resolves_confirmed_s6850_aliases_when_lldp_ip_is_absent(index):
    """A confirmed hostname alias remains usable when LLDP reports no IP."""
    from services.topology_service import _match_target_device_with_evidence

    device_rows = [
        {
            'id': f'device-{index}',
            'hostname': f'S6850-{index}',
            'ip_address': f'10.254.0.{index}',
            'sn': '',
        }
        for index in range(1, 5)
    ]

    result = _match_target_device_with_evidence(
        None,
        f'S6850-{index}',
        '',
        device_rows=device_rows,
    )

    assert result['device']['id'] == f'device-{index}'
    assert result['device']['ip_address'] == f'10.254.0.{index}'
    assert result['method'] == 'system_name'
    assert result['status'] == 'matched'


def test_match_target_device_does_not_fall_back_to_hostname_when_reported_ip_conflicts():
    """A LLDP name cannot override a reported IP that matches no CMDB management IP."""
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        'S6850-2',
        '10.254.100.5',
        device_rows=[
            {'id': 'device-2', 'hostname': 'S6850-2', 'ip_address': '10.254.0.2', 'sn': 'SERIAL-2'},
        ],
    )

    assert result['device'] is None
    assert result['status'] == 'unmatched'
    assert result['method'] == 'management_ip_not_found'
    assert result['reason_code'] == 'reported_management_ip_not_found_in_cmdb'


def test_match_target_device_does_not_fall_back_to_serial_when_reported_ip_conflicts():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        'S6850-2',
        '10.254.100.5',
        'SERIAL-2',
        device_rows=[
            {'id': 'device-2', 'hostname': 'S6850-2', 'ip_address': '10.254.0.2', 'sn': 'SERIAL-2'},
        ],
    )

    assert result['device'] is None
    assert result['method'] == 'management_ip_not_found'
    assert result['reason_code'] == 'reported_management_ip_not_found_in_cmdb'


def test_cli_match_uses_unique_asset_hostname_and_ignores_reported_ip_or_chassis():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        'S6850-4',
        '10.254.100.5',
        'CHASSIS-OF-OTHER-DEVICE',
        device_rows=[
            {
                'id': 'asset-s6850-4', 'hostname': 'legacy-device-value',
                'asset_hostname': 'S6850-4', 'ip_address': '10.254.0.4', 'sn': 'CHASSIS-4',
            },
            {
                'id': 'ip-owner', 'hostname': 'IP-OWNER',
                'asset_hostname': 'IP-OWNER', 'ip_address': '10.254.100.5', 'sn': 'CHASSIS-OF-OTHER-DEVICE',
            },
        ],
        cli_hostname_only=True,
    )

    assert result['device']['id'] == 'asset-s6850-4'
    assert result['status'] == 'matched'
    assert result['method'] == 'cli_system_name_exact_asset_hostname'


def test_cli_match_does_not_use_ip_or_separator_alias_when_asset_hostname_is_not_exact():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        'S6850_4',
        '10.254.0.4',
        'CHASSIS-4',
        device_rows=[{
            'id': 'asset-s6850-4', 'hostname': 'S6850-4',
            'asset_hostname': 'S6850-4', 'ip_address': '10.254.0.4', 'sn': 'CHASSIS-4',
        }],
        cli_hostname_only=True,
    )

    assert result['device'] is None
    assert result['status'] == 'unmatched'
    assert result['method'] == 'cli_system_name_not_found'
    assert result['reason_code'] == 'cli_system_name_not_found_in_cmdb'


def test_cli_match_rejects_duplicate_asset_hostnames_as_ambiguous():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        'S6850-4',
        '10.254.0.4',
        device_rows=[
            {'id': 'asset-1', 'hostname': 'S6850-4', 'asset_hostname': 'S6850-4', 'ip_address': '10.254.0.4'},
            {'id': 'asset-2', 'hostname': 'S6850-4-copy', 'asset_hostname': 'S6850-4', 'ip_address': '10.254.0.44'},
        ],
        cli_hostname_only=True,
    )

    assert result['device'] is None
    assert result['status'] == 'ambiguous'
    assert result['method'] == 'cli_system_name_duplicate_asset_hostname'


def test_cli_match_does_not_use_legacy_device_hostname_without_current_asset_name():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None, 'LEGACY-NAME', '192.0.2.10',
        device_rows=[{'id': 'device-a', 'hostname': 'LEGACY-NAME', 'ip_address': '192.0.2.10'}],
        cli_hostname_only=True,
    )

    assert result['device'] is None
    assert result['reason_code'] == 'cli_system_name_not_found_in_cmdb'


def test_topology_hostname_uses_current_cmdb_value_even_when_legacy_device_name_differs():
    from services.topology_service import _canonical_device_hostname

    assert _canonical_device_hostname('CMDB-NAME', 'OLD-DEVICE-NAME') == 'CMDB-NAME'
    assert _canonical_device_hostname('10.0.0.1', 'OLD-DEVICE-NAME') == '10.0.0.1'
    assert _canonical_device_hostname('', 'UNLINKED-DEVICE') == 'UNLINKED-DEVICE'


def test_match_target_device_prefers_unique_management_ip_and_flags_name_mismatch():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        'old-switch-name',
        '192.0.2.10',
        device_rows=[
            {'id': 'device-a', 'hostname': 'core-a', 'ip_address': '192.0.2.10', 'sn': 'SERIAL-A'},
            {'id': 'device-b', 'hostname': 'old-switch-name', 'ip_address': '192.0.2.11', 'sn': 'SERIAL-B'},
        ],
    )

    assert result['device']['id'] == 'device-a'
    assert result['method'] == 'management_ip'
    assert result['status'] == 'hostname_mismatch'


def test_match_target_device_case_only_hostname_variant_does_not_create_duplicate_peer():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        'CORE-SW-01',
        '',
        device_rows=[{'id': 'device-a', 'hostname': 'core-sw-01', 'ip_address': '', 'sn': ''}],
    )

    assert result['device']['id'] == 'device-a'
    assert result['method'] == 'system_name_casefold'
    assert result['status'] == 'matched'


def test_match_target_device_normalizes_serial_separators():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        '',
        '',
        '00:11-AA.22',
        device_rows=[{'id': 'device-a', 'hostname': '', 'ip_address': '', 'sn': '0011aa22'}],
    )

    assert result['device']['id'] == 'device-a'
    assert result['method'] == 'serial_number'


def test_match_target_device_marks_management_ip_and_serial_conflict_ambiguous():
    from services.topology_service import _match_target_device_with_evidence

    result = _match_target_device_with_evidence(
        None,
        '',
        '192.0.2.10',
        'SERIAL-B',
        device_rows=[
            {'id': 'device-a', 'hostname': 'core-a', 'ip_address': '192.0.2.10', 'sn': 'SERIAL-A'},
            {'id': 'device-b', 'hostname': 'core-b', 'ip_address': '192.0.2.11', 'sn': 'SERIAL-B'},
        ],
    )

    assert result['device'] is None
    assert result['status'] == 'ambiguous'
    assert result['method'] == 'management_ip_serial_conflict'


def test_target_identity_rows_are_scoped_to_the_source_tenant():
    from services.topology_service import _load_target_device_identity_rows
    from unittest.mock import MagicMock

    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {'id': 'tenant-a-device', 'device_hostname': 'old-device-name', 'asset_hostname': 'switch-a', 'tenant_id': 'tenant-a'},
    ]

    rows = _load_target_device_identity_rows(conn, tenant_id='tenant-a')

    sql, params = conn.execute.call_args.args
    assert "COALESCE(NULLIF(d.tenant_id, ''), 'tenant-default') = ?" in sql
    assert params == ('tenant-a',)
    assert rows == [{
        'id': 'tenant-a-device', 'hostname': 'switch-a', 'device_hostname': 'old-device-name',
        'asset_hostname': 'switch-a', 'tenant_id': 'tenant-a',
    }]


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
        assert "o.neighbor_ip_address" in called_sql
        assert "o.raw_payload_json" in called_sql

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
        elif oid == '1.0.8802.1.1.2.1.4.1.1.5': # lldpRemChassisId
            return [('0.1.1', '8e44-40f8-0400')]
        return []

    with patch('services.snmp_service._snmp_walk', side_effect=mock_walk):
        neighbors = asyncio.run(collect_snmp_lldp_neighbors('10.254.0.3', 'public'))
        assert len(neighbors) == 1
        neighbor = neighbors[0]
        # Must prefer the standard GigabitEthernet1/0/1 over TO-S6850-4-GE1/0/1
        assert neighbor['neighbor_interface'] == 'GigabitEthernet1/0/1'
        assert neighbor['neighbor_name'] == 'S6850-4'
        assert neighbor['chassis_id'] == '8e44-40f8-0400'


