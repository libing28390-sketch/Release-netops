from core.interface_utils import interface_nominal_speed_mbps, normalize_interface_name
from services.topology_service import (
    _collapse_aggregation_groups,
    _group_link_observations,
    _interface_display_score,
    _prefer_lldp_rows,
)
from services.operational_data_service import _parse_aggregation_raw


def test_interface_aliases_are_canonical_for_cross_vendor_adjacencies() -> None:
    assert normalize_interface_name('Vlan7') == 'vlan7'
    assert normalize_interface_name('Vlan-interface7') == 'vlan7'
    assert normalize_interface_name('Vlanif7') == 'vlan7'
    assert normalize_interface_name('Et0/1') == 'eth0/1'
    assert normalize_interface_name('Ethernet0/1') == 'eth0/1'
    assert normalize_interface_name('GE2/0') == 'gi2/0'
    assert normalize_interface_name('GigabitEthernet2/0') == 'gi2/0'
    assert normalize_interface_name('GigabitEthernet3/0 Interface') == 'gi3/0'
    assert normalize_interface_name('XGE1/0/49') == 'te1/0/49'
    assert normalize_interface_name('Ten-GigabitEthernet1/0/49') == 'te1/0/49'
    assert normalize_interface_name('TenGigE1/0/49') == 'te1/0/49'
    assert normalize_interface_name('FGE1/0/54') == 'fo1/0/54'
    assert normalize_interface_name('40GE1/0/54') == 'fo1/0/54'
    assert normalize_interface_name('FortyGigE1/0/54') == 'fo1/0/54'
    assert normalize_interface_name('HGE1/0/1') == 'hu1/0/1'
    assert normalize_interface_name('100GE1/0/1') == 'hu1/0/1'
    assert normalize_interface_name('HundredGigE1/0/1') == 'hu1/0/1'
    assert interface_nominal_speed_mbps('XGE1/0/49') == 10_000
    assert interface_nominal_speed_mbps('FGE1/0/54') == 40_000
    assert interface_nominal_speed_mbps('100GE1/0/1') == 100_000


def test_interface_alias_with_real_rate_wins_over_zero_rate_placeholder() -> None:
    device_meta = {'vendor': 'h3c', 'platform': 'h3c_comware'}
    populated = {'interface_name': 'Ten-GigabitEthernet1/0/49', 'speed': 10_000_000_000}
    placeholder = {'interface_name': 'XGE1/0/49', 'speed': 0}
    assert _interface_display_score(populated, device_meta) > _interface_display_score(placeholder, device_meta)


def test_grouping_recomputes_normalized_key_from_raw_observation() -> None:
    rows = [
        {
            'source_device_id': 'dev-a', 'target_device_id': 'dev-b',
            'source_port_raw': 'Et0/1', 'source_port_normalized': 'et0/1',
            'target_port_raw': 'Ethernet0/1', 'target_port_normalized': 'eth0/1',
        },
        {
            'source_device_id': 'dev-b', 'target_device_id': 'dev-a',
            'source_port_raw': 'Ethernet0/1', 'source_port_normalized': 'eth0/1',
            'target_port_raw': 'Et0/1', 'target_port_normalized': 'et0/1',
        },
    ]
    assert len(_group_link_observations(rows)) == 1


def test_topology_rebuild_drops_cdp_rows_and_keeps_lldp_only() -> None:
    rows = [
        {'source_device_id': 'dev-a', 'target_device_id': 'dev-b', 'protocol': 'lldp'},
        {'source_device_id': 'dev-a', 'target_device_id': 'dev-b', 'protocol': 'cdp'},
        {'source_device_id': 'dev-b', 'target_device_id': 'dev-c', 'protocol': 'cdp'},
    ]
    filtered = _prefer_lldp_rows(rows)
    assert [(row['source_device_id'], row['target_device_id'], row['protocol']) for row in filtered] == [
        ('dev-a', 'dev-b', 'lldp'),
    ]


def test_reverse_h3c_short_and_long_interface_names_form_one_link() -> None:
    rows = [
        {
            'source_device_id': 'dev-a',
            'target_device_id': 'dev-b',
            'source_port_raw': 'GE2/0',
            'target_port_raw': 'GigabitEthernet2/0',
        },
        {
            'source_device_id': 'dev-b',
            'target_device_id': 'dev-a',
            'source_port_raw': 'GE2/0',
            'target_port_raw': 'GigabitEthernet2/0',
        },
    ]
    grouped = _group_link_observations(rows)
    assert len(grouped) == 1


def test_member_links_collapse_to_one_logical_aggregation_edge() -> None:
    rows = [
        {
            'source_device_id': 'dev-a', 'target_device_id': 'dev-b',
            'source_port_raw': 'Et0/1', 'source_port_normalized': 'eth0/1',
            'target_port_raw': 'GE1/0/1', 'target_port_normalized': 'gi1/0/1',
            'protocol': 'lldp',
        },
        {
            'source_device_id': 'dev-a', 'target_device_id': 'dev-b',
            'source_port_raw': 'Et0/2', 'source_port_normalized': 'eth0/2',
            'target_port_raw': 'GE1/0/2', 'target_port_normalized': 'gi1/0/2',
            'protocol': 'lldp',
        },
    ]
    grouped = _group_link_observations(rows)
    aggregation_map = {
        ('dev-a', 'eth0/1'): {'aggregation_id': 'po1-a', 'aggregation_name': 'Port-channel1', 'speed_mbps': 10_000, 'is_up': True},
        ('dev-a', 'eth0/2'): {'aggregation_id': 'po1-a', 'aggregation_name': 'Port-channel1', 'speed_mbps': 10_000, 'is_up': True},
        ('dev-b', 'gi1/0/1'): {'aggregation_id': 'ba1-b', 'aggregation_name': 'Bridge-Aggregation1', 'speed_mbps': 10_000, 'is_up': True},
        ('dev-b', 'gi1/0/2'): {'aggregation_id': 'ba1-b', 'aggregation_name': 'Bridge-Aggregation1', 'speed_mbps': 10_000, 'is_up': True},
    }

    collapsed = _collapse_aggregation_groups(grouped, aggregation_map)

    assert len(collapsed) == 1
    bundle = next(iter(collapsed.values()))
    contract = bundle['aggregation']
    assert contract['source_aggregation_name'] == 'Port-channel1'
    assert contract['target_aggregation_name'] == 'Bridge-Aggregation1'
    assert contract['member_count'] == 2
    assert contract['active_member_count'] == 2
    assert contract['bandwidth_mbps'] == 20_000


def test_cisco_etherchannel_raw_parser_keeps_parent_and_members() -> None:
    output = """
    Group Port-channel Protocol Ports
    1    Po1(SU)       LACP     Gi1/0/1(P) Gi1/0/2(P)
    """
    records = _parse_aggregation_raw(output, 'cisco_ios')
    assert [item['PORT_CHANNEL'] for item in records] == ['Port-channel1', 'Port-channel1']
    assert [item['INTERFACE'] for item in records] == ['Gi1/0/1', 'Gi1/0/2']
