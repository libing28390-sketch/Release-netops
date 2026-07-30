import pytest
from core.textfsm import smart_parse_cli


def test_dptech_show_lldp_neighbors():
    output = """
show lldp neighbors 

 Port name                         tengige5_0 
 TLV port ID                       tengige5_0 
 TLV port description              tengige5_0 
 LLDP packets received             3151678 
 LLDP packets sent                 3148145 

 Chassis ID                        78:17:BE:A0:E6:00 
 Port ID                           XGigabitEthernet3/0/41 
 TLV TTL                           120 s 
 Port description                  ZYYW-LX-null-null-N-EMISwaiwangchukou 
 System name                       JXYIC-MC-CMNET-SW01-S9300-SNL 
 System description                Huawei Switch S9300X-4
Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (S9300 V200R022C00SPC500)
Copyright (C) 2000-2022 HUAWEI TECH Co., Ltd. 
 Link id                           0 
 Link direction                    0 
 System capabilities               Bridge,Router 
 Management address                              1.1.1.1 
 Management address                not advertised 
"""
    result = smart_parse_cli(output, "show lldp neighbors", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["INTERFACE"] == "tengige5_0"
    assert result["data"][0]["CHASSIS_ID"] == "78:17:BE:A0:E6:00"
    assert result["data"][0]["NEIGHBOR_INTERFACE"] == "XGigabitEthernet3/0/41"
    assert result["data"][0]["NEIGHBOR"] == "JXYIC-MC-CMNET-SW01-S9300-SNL"
    assert result["data"][0]["MGMT_ADDRESS"] == "1.1.1.1"


def test_dptech_show_vlan():
    output = """
show vlan 
Total VLANs: 9
The VLANs include:
1(default),10,30,116,129,1008-1011
"""
    result = smart_parse_cli(output, "show vlan", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["TOTAL_VLANS"] == "9"
    assert "1(default),10,30,116,129,1008-1011" in result["data"][0]["VLAN_LIST"]


def test_dptech_show_mac_address_table():
    output = """
show mac-address-table 
The total counts is 92 ! 
ID    MAC Address          VLAN ID  Ports            Type       Action
1     240f-9bc0-4258       1011     tengige6_14      dynamic    normal
2     7054-f586-a1ac       116      tengige6_14      dynamic    normal
"""
    result = smart_parse_cli(output, "show mac-address-table", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["MAC_ADDRESS"] == "240f-9bc0-4258"
    assert result["data"][0]["VLAN_ID"] == "1011"
    assert result["data"][0]["INTERFACE"] == "tengige6_14"


def test_dptech_show_arp_all():
    output = """
show arp all
                Type: S-Static      D-Dynamic
Ip Address              Mac Address        Vlan ID     Interface       AGE(SEC)   Type
192.51.71.8          c4ca-d9b5-3900          116        tengige6_14      358       D
192.168.110.250      000c-2963-939b          1010       tengige6_14      773       D
"""
    result = smart_parse_cli(output, "show arp all", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["IP_ADDRESS"] == "192.51.71.8"
    assert result["data"][0]["MAC_ADDRESS"] == "c4ca-d9b5-3900"
    assert result["data"][0]["VLAN_ID"] == "116"


def test_dptech_show_interface_status():
    output = """
show interface status 

The number of ports: 41
port information:
port-name                speed    duplex   auto     state  VLAN     description
bond1                    2000M    full     disable  up     10       xintiao
tengige5_0               10000M   full     disable  up     129      tengige5_0
tengige6_1               10000M   full     disable  up     1008-1009tengige6_1
tengige6_14              1000M    full     disable  up     116,129,1008-101151715-g1/23
"""
    result = smart_parse_cli(output, "show interface status", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 4
    assert result["data"][0]["INTERFACE"] == "bond1"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][0]["SPEED"] == "2000M"
    assert result["data"][2]["INTERFACE"] == "tengige6_1"
    assert result["data"][2]["VLAN"] == "1008-1009"
    assert result["data"][2]["DESCRIPTION"] == "tengige6_1"


def test_dptech_show_ip_interface_brief():
    output = """
show ip interface brief
Interface     Physical   Protocol     IP Address           Description
vlan-if1      down       down         --                   vlan-if1                         
vlan-if10     up         up           1.1.1.1/30           vlan-if10                        
vlan-if30     up         up           10.178.40.249/29     TO_H3C-7606                      
"""
    result = smart_parse_cli(output, "show ip interface brief", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["INTERFACE"] == "vlan-if1"
    assert result["data"][1]["IP_ADDRESS"] == "1.1.1.1/30"


def test_dptech_show_ip_route():
    output = """
show ip route 
Codes: K - kernel route, C - connected, S - static, R - RIP, O - OSPF,
       I - ISIS, B - BGP, > - selected route, * - FIB route, G - GUARD, A - ARP

S>* 0.0.0.0/0 [1/0] fmap : 0x1 is directly connected, tunnel_ipsec255
C>* 1.1.1.0/30 fmap : 0x1 is directly connected, vlan-if10 weight 0
S>* 10.178.0.0/17 [1/0] fmap : 0x1 via 10.178.40.252, internel via 10.178.40.252 , vlan-if30
"""
    result = smart_parse_cli(output, "show ip route", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["NETWORK"] == "0.0.0.0/0"
    assert result["data"][0]["INTERFACE"] == "tunnel_ipsec255"
    assert result["data"][2]["NEXTHOP_IP"] == "10.178.40.252"
    assert result["data"][2]["INTERFACE"] == "vlan-if30"


def test_dptech_show_device():
    output = """
show device           
SlotID    BoardName                       Online      Status
- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
1         H10-MPU                         Present     Normal
2         H10-MPU                         Present     Normal
3                                         Offline     Forbidden
5         H10-16XGS4CQ-G                  Present     Normal
"""
    result = smart_parse_cli(output, "show device", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 4
    assert result["data"][0]["SLOT"] == "1"
    assert result["data"][0]["BOARD_NAME"] == "H10-MPU"
    assert result["data"][2]["SLOT"] == "3"
    assert result["data"][2]["ONLINE"] == "Offline"


def test_dptech_show_environment():
    output = """
show environment 

Temperature(Celsius):
- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -- - - - - - - - - - - - - - - -
Slot ID   Board Name            Board Temperature    CPU Temperature    Switch-chip Temperature       
- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -- - - - - - - - - - - - - - - -
1         H10-MPU               31                   35                 n/a                           
2         H10-MPU               30                   50                 30                            
"""
    result = smart_parse_cli(output, "show environment", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["SLOT"] == "1"
    assert result["data"][0]["BOARD_TEMP"] == "31"
    assert result["data"][0]["CPU_TEMP"] == "35"


def test_dptech_show_cpu_usage():
    output = """
show cpu-usage 
Slot 1(MAIN) CPU usage:
             1% in last 30 seconds
             1% in last 1  minute
             1% in last 5  minute
Slot 7(FW) CPU usage:
             2% in last 30 seconds
             2% in last 1  minute
             2% in last 5  minute
"""
    result = smart_parse_cli(output, "show cpu-usage", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["SLOT"] == "1(MAIN)"
    assert result["data"][0]["CPU_30SEC"] == "1"


def test_dptech_show_memory():
    output = """
show memory 
Slot 1(MAIN)
Total        Memory : 8332288 KB
Reserved     Memory : 1154620 KB
Available    Memory : 7177668 KB
Total  Used  Memory : 2958200 KB
Usage : 41%
"""
    result = smart_parse_cli(output, "show memory", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["SLOT"] == "1(MAIN)"
    assert result["data"][0]["TOTAL_MEMORY"] == "8332288"
    assert result["data"][0]["USAGE_PCT"] == "41"


def test_dptech_show_version():
    output = """
show version 
 Software Release S211C011D007P08
 Conplat Version is V100R004B01D007P08
 Compiled Tue, 11 Sep 2018 03:42:54 +0800

 FW1000-TS-C Uptime is 63 week(s), 4 day(s), 17 hour(s), 35 minute(s)
 Serial Number:          02050631N195000010
"""
    result = smart_parse_cli(output, "show version", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["SOFTWARE_VERSION"] == "S211C011D007P08"
    assert result["data"][0]["SERIAL_NUMBER"] == "02050631N195000010"


def test_dptech_show_logging_operlog_recent():
    output = """
show logging operlog recent 
| 2026-07-30 17:24:52  | ssh      | zhangqican | 10.160.23.250 | success | 访问最近[25]条操作日志。
| 2026-07-30 17:24:29  | ssh      | zhangqican | 10.160.23.250 | success | 用户 [zhangqican] 从IP: [10.160.23.250]登录。
"""
    result = smart_parse_cli(output, "show logging operlog recent", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["TIME"] == "2026-07-30 17:24:52"
    assert result["data"][0]["USER"] == "zhangqican"
    assert result["data"][0]["IP_ADDRESS"] == "10.160.23.250"


def test_dptech_show_interface_counters():
    output = """
show interface  counters 
The total input speed: 21 pps, 14880 bps
The total InPkts: 9535907083, InMcastpkts: 200638150, InBcastpkts: 448586811, InCrcErrPkts: 0
Interface     InPkts                 InMcastPkts            InBcastPkts            Inbps           Inpps           InCrcErrPkts
gige0_10      42157525               1467900                31903                  4336            5               0               
"""
    result = smart_parse_cli(output, "show interface counters", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["INTERFACE"] == "gige0_10"
    assert result["data"][0]["IN_PKTS"] == "42157525"


def test_dptech_show_clock():
    output = """
show clock 
Thu Jul 30 17:27:03 2026 GMT +8:00
"""
    result = smart_parse_cli(output, "show clock", platform="dptech_ios")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert "2026 GMT +8:00" in result["data"][0]["TIME"]
