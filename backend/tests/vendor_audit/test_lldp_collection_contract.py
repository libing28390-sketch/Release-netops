import pytest

from services.neighbor_collection_contract import (
    NeighborCollectionContractError,
    assert_lldp_command,
    classify_lldp_status,
    normalize_neighbor_record,
)
from services.operational_data_service import _resolve_commands


def test_cisco_command_policy_rejects_cdp_before_send() -> None:
    with pytest.raises(NeighborCollectionContractError, match='cdp'):
        assert_lldp_command('cisco_ios', 'show cdp neighbors', scenario_id='neighbor_lldp')


def test_validated_vendor_commands_are_allowlisted() -> None:
    assert assert_lldp_command('cisco_ios', 'show lldp neighbors') == 'show lldp neighbors'
    assert assert_lldp_command('huawei_vrpv8', 'display lldp neighbor brief') == 'display lldp neighbor brief'
    assert assert_lldp_command('h3c_comware9', 'display lldp neighbor-information list') == 'display lldp neighbor-information list'


def test_operational_neighbor_catalog_is_lldp_only() -> None:
    for platform in ('cisco_ios', 'cisco_nxos', 'huawei_vrpv8', 'h3c_comware9'):
        commands = _resolve_commands(platform, ['neighbors'])['neighbors']
        assert commands
        assert all('cdp' not in command.lower() for command in commands)


def test_lldp_status_distinguishes_empty_disabled_and_parse_failure() -> None:
    assert classify_lldp_status(raw_output='') == 'no_neighbors'
    assert classify_lldp_status(raw_output='% LLDP is not enabled') == 'lldp_disabled'
    assert classify_lldp_status(raw_output='unexpected output') == 'parse_failed'
    assert classify_lldp_status(parsed_count=1, raw_output='neighbor') == 'success'


def test_common_playbook_neighbor_shape_is_stable() -> None:
    record = normalize_neighbor_record({
        'LOCAL_INTERFACE': 'Gi1/0/1',
        'NEIGHBOR_NAME': 'dist-01',
        'NEIGHBOR_PORT_ID': 'Gi1/0/48',
        'MGMT_ADDRESS': '192.0.2.10',
        'CAPABILITIES': 'bridge router',
    })
    assert record == {
        'local_interface': 'Gi1/0/1',
        'neighbor_name': 'dist-01',
        'neighbor_interface': 'Gi1/0/48',
        'neighbor_management_ip': '192.0.2.10',
        'neighbor_platform': '',
        'neighbor_capabilities': ['bridge', 'router'],
        'protocol': 'lldp',
    }
