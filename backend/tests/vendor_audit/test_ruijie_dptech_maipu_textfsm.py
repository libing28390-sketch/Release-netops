import pytest
from core.textfsm import smart_parse_cli, parse_with_textfsm

def test_ruijie_show_ip_interface_brief_switch():
    output = """
Interface                IP-Address      OK? Method Status                Protocol
GigabitEthernet 0/1      192.168.1.1     YES manual up                    up
GigabitEthernet 0/2      unassigned      YES unset  down                  down
GigabitEthernet 0/3      unassigned      YES unset  administratively down down
Vlan 1                   10.1.1.1        YES manual up                    up
"""
    result = smart_parse_cli(output, "show ip interface brief", platform="ruijie_rgos_v12")
    assert result["success"] is True
    assert len(result["data"]) == 4
    assert result["data"][0]["INTERFACE"] == "GigabitEthernet 0/1"
    assert result["data"][0]["IP_ADDRESS"] == "192.168.1.1"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][0]["PROTOCOL"] == "up"
    assert result["data"][2]["STATUS"] == "administratively down"


def test_ruijie_show_ip_interface_brief_router():
    output = """
Interface                IP-Address(Pri)         IP-Address(Sec)         Status      Protocol
GigabitEthernet 0/0      192.168.10.1/24         no address              up          up
GigabitEthernet 0/1      no address              no address              down        down
"""
    result = smart_parse_cli(output, "show ip interface brief", platform="ruijie_rgos_v12")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["INTERFACE"] == "GigabitEthernet 0/0"
    assert result["data"][0]["IP_ADDRESS"] == "192.168.10.1"
    assert result["data"][0]["PREFIX_LENGTH"] == "24"
    assert result["data"][0]["STATUS"] == "up"


def test_ruijie_show_interface_brief():
    output = """
Interface                Status   Protocol  Description
GigabitEthernet 0/1      up       up        Uplink_To_Core
GigabitEthernet 0/2      down     down      Unused_Port
"""
    result = smart_parse_cli(output, "show interface brief", platform="ruijie_rgos_v12")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["INTERFACE"] == "GigabitEthernet 0/1"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][0]["DESCRIPTION"] == "Uplink_To_Core"


def test_dptech_show_interface_brief():
    output = """
Interface                Link   Speed     Duplex   Type     PVID  Description
ge0/0                    up     1G        full     trunk    1     To_Core_SW
ge0/1                    down   auto      auto     access   10    LAN_Port
"""
    result = smart_parse_cli(output, "show interface brief", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["INTERFACE"] == "ge0/0"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][0]["SPEED"] == "1G"
    assert result["data"][0]["DUPLEX"] == "full"
    assert result["data"][0]["DESCRIPTION"] == "To_Core_SW"


def test_dptech_show_ip_interface_brief():
    output = """
Interface                IP Address        Physical Protocol Description
eth0/0                   192.168.1.1/24    up       up       WAN1_Port
eth0/1                   10.0.0.1/24       up       up       LAN1_Port
eth0/2                   unassigned        down     down     Backup_Port
"""
    result = smart_parse_cli(output, "show ip interface brief", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["INTERFACE"] == "eth0/0"
    assert result["data"][0]["IP_ADDRESS"] == "192.168.1.1/24"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][0]["DESCRIPTION"] == "WAN1_Port"


def test_maipu_show_ip_interface_brief():
    output = """
Interface                IP-Address      OK? Method Status                Protocol
GigabitEthernet0/1       192.168.1.1     YES manual up                    up
GigabitEthernet0/2       unassigned      YES unset  down                  down
Vlan1                    10.1.1.1        YES manual up                    up
"""
    result = smart_parse_cli(output, "show ip interface brief", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["INTERFACE"] == "GigabitEthernet0/1"
    assert result["data"][0]["IP_ADDRESS"] == "192.168.1.1"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][2]["INTERFACE"] == "Vlan1"


def test_maipu_show_interface_brief():
    output = """
Port                     Link  Speed    Duplex  Vlan  Type       Description
Gi0/1                    up    1G       full    1     Trunk      Uplink_Core
Gi0/2                    down  auto     auto    10    Access     User_Port
"""
    result = smart_parse_cli(output, "show interface brief", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["INTERFACE"] == "Gi0/1"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][0]["SPEED"] == "1G"
    assert result["data"][0]["DESCRIPTION"] == "Uplink_Core"
