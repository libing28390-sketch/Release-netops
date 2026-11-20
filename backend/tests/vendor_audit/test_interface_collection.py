from core.interface_utils import normalize_interface_name
from services.scheduler_service import (
    normalize_collected_interface_status,
    parse_cisco_ip_interface_brief,
)


IOS_INTERFACE_BRIEF = """\
Interface              IP-Address      OK? Method Status                Protocol
Ethernet0/0            10.1.35.5       YES manual up                    up
Ethernet0/1            192.168.18.205  YES manual up                    up
Ethernet0/2            unassigned      YES unset  administratively down down
Ethernet0/3            unassigned      YES unset  administratively down down
"""


def test_cisco_interface_brief_keeps_interface_ip_separate_from_device_ip() -> None:
    records = {
        normalize_interface_name(row['interface']): row
        for row in parse_cisco_ip_interface_brief(IOS_INTERFACE_BRIEF)
    }

    assert records['eth0/0']['ip_address'] == '10.1.35.5'
    assert records['eth0/1']['ip_address'] == '192.168.18.205'
    assert records['eth0/2']['ip_address'] == ''
    assert records['eth0/3']['ip_address'] == ''
    assert records['eth0/2']['admin_status'] == 'down'
    assert records['eth0/2']['oper_status'] == 'down'


def test_interface_status_normalization_uses_cmdb_values() -> None:
    assert normalize_collected_interface_status('administratively down') == 'down'
    assert normalize_collected_interface_status('up') == 'up'
    assert normalize_collected_interface_status('') == 'unknown'
