from core.interface_utils import normalize_interface_name
from services.interface_collection_service import _build_interface_status_rows, _looks_like_interface_name, _status_record
from services.scheduler_service import normalize_collected_interface_rate


def test_ntc_lowercase_loopback_record_is_collected_with_status() -> None:
    interface_name, ip_address, prefix_len, admin_status, oper_status = _status_record(
        {
            'interface': 'Loopback0',
            'ip_address': '5.5.5.5',
            'status': 'up',
            'proto': 'up',
        },
        {'lo0': '5.5.5.5'},
    )

    assert interface_name == 'Loopback0'
    assert ip_address == '5.5.5.5'
    assert admin_status == 'up'
    assert oper_status == 'up'


def test_interface_status_snapshot_keeps_ip_bearing_interfaces_only() -> None:
    parsed, rows = _build_interface_status_rows(
        [
            {'interface': 'GigabitEthernet0/0/4', 'ip_address': 'unassigned', 'status': 'up', 'proto': 'up'},
            {'interface': 'Vlanif20', 'ip_address': '10.253.20.2', 'status': 'up', 'proto': 'up'},
        ],
        {},
        {},
    )

    assert set(parsed) == {'vlan20'}
    by_key = {normalize_interface_name(row['interface_name']): row for row in rows}
    assert by_key['vlan20']['interface_ip'] == '10.253.20.2'
    assert 'gi0/0/4' not in by_key


def test_interface_status_snapshot_ignores_parser_header_fragments() -> None:
    assert _looks_like_interface_name('The') is False
    _, rows = _build_interface_status_rows(
        [{'interface': 'The', 'status': 'up', 'proto': 'up'}],
        {},
        {},
    )
    assert rows == []


def test_interface_rate_text_is_normalized_before_numeric_db_write() -> None:
    assert normalize_collected_interface_rate('10000 Kbit') == 10_000_000.0
    assert normalize_collected_interface_rate('10 Gbps') == 10_000_000_000.0
    assert normalize_collected_interface_rate(1_000_000) == 1_000_000.0
