from services.interface_collection_service import _status_record
from services.scheduler_service import normalize_collected_interface_rate


def test_ntc_lowercase_loopback_record_is_collected_with_status() -> None:
    interface_name, ip_address, admin_status, oper_status = _status_record(
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


def test_interface_rate_text_is_normalized_before_numeric_db_write() -> None:
    assert normalize_collected_interface_rate('10000 Kbit') == 10_000_000.0
    assert normalize_collected_interface_rate('10 Gbps') == 10_000_000_000.0
    assert normalize_collected_interface_rate(1_000_000) == 1_000_000.0
