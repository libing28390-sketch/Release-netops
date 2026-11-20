import pytest
from core.textfsm import list_template_suggestions, parse_with_textfsm
from services.normalizers.factory import NormalizerFactory
from services.normalizers.zte import ZTENormalizer


ZTE_SHOW_LLDP_NEIGHBOR = """show lldp neighbor 
The total neighbor number:17
Capability Codes: 
                  N - Other, r - Repeater, B - Bridge, W - WLAN Access Point,
                  R - Router, T - Telephone, D - DOCSIS Cable Device,
                  S - Station Only, C - C-VLAN Component of a VLAN Bridge,
                  s - S-VLAN Component of a VLAN Bridge,
                  t - Two-port MAC Relay (TPMR)
Interface         Dest-MAC ChassisID Holdtime Capability Platform                                peer-Port         hostname       
----------------------------------------------------------------------------------------------------------------------------------
xxvgei-0/1/1/40   Nearest  5cf796a1c 102      B R C      H3C Comware Platform Software, Software Ten-GigabitEthern yunwangba01
                  Bridge   5cc                            Version 7.1.070, Release 8108P24H3C S5 et1/0/51          
                                                         552S-EI-D-DP-GCopyright (c) 2004-2023 N                   
                                                         ew H3C Technologies Co., Ltd. All right                   
                                                         s reserved.                                               
cgei-0/1/1/55     Nearest  fc449f6ca 94       B R        5900 V6.00.04.20P01,ZXR10 5960 Software cgei-0/1/1/55     JXYC-YunWangBa-
                  Bridge   38c                                                                                     5960X-02
cgei-0/1/1/56     Nearest  fc449f6ca 94       B R        5900 V6.00.04.20P01,ZXR10 5960 Software cgei-0/1/1/56     JXYC-YunWangBa-
                  Bridge   38c                                                                                     5960X-02
smartgroup10      Nearest  ec7359002 101      B R        Cloudsky software, YTS3148, Version 7.4 eth-0-52          42821_A04_YT_S3
                  Bridge   7ec                           .10.r1  Copyright (C) Cloudsky.  All Ri                   148_ACC_D01
                                                         ghts Reserved.                                            
"""

ZTE_SHOW_VLAN = """show vlan 
VLAN     Name     PvidPorts           UntagPorts          TagPorts          
--------------------------------------------------------------------------------
1        vlan0001 smartgroup10-26                         
                  smartgroup100                           
                  cgei-0/1/1/49-54                        
                  cgei-0/1/1/56                           
                  xxvgei-0/1/1/1-38                       
                  xxvgei-0/1/1/40-47                      
2        vlan0002                                         xxvgei-0/1/1/47
3        vlan0003                                         xxvgei-0/1/1/47
4        vlan0004                                         xxvgei-0/1/1/47
5        vlan0005                                         xxvgei-0/1/1/47
6        vlan0006                                         xxvgei-0/1/1/47
"""

ZTE_SHOW_MAC_TABLE = """show mac table 
Total MAC address : 274     

Flags: Src--Source filter, Dst--Destination filter, *--Switch to peerlink,
       From:0,driver;1,config;2,VPN;3,802.1X;4,micro;5,DHCP;
            6,PBT;7,EVB;8,OTV;9,TRILL;10,ESADI;11,MC-LAG,
       Time--Day Hour:Min:Sec

MAC            VLAN Outgoing Information         Attribute      From Time
-------------- ---- ---------------------------- -------------- ---- --------------
5254.00fd.5621 103  smartgroup22                 Dynamic        0       0d 00:01:36
f4b0.ff2e.2e41 205  smartgroup26                 Dynamic        0       0d 00:01:50
0281.a4e1.df76 2201 smartgroup13                 Dynamic        0       0d 00:01:47
"""

ZTE_SHOW_ARP = """show arp 
Arp protect whole is disabled 
The count is 232
IP                       Hardware                    Exter  Inter  Sub
Address         Age      Address        Interface    VlanID VlanID Interface
--------------------------------------------------------------------------------
10.114.102.1    H        fc44.9f6c.a38d mgmt_eth     N/A    N/A    N/A
10.147.1.252    HB       fc44.9f6c.a390 vlan101      101    N/A    smartgroup100
10.147.1.253    H        fc44.9f6c.a38c vlan101      101    N/A    N/A
10.147.1.254    H        0000.5960.0101 vlan101      101    N/A    N/A
10.147.1.250    00:00:29 000c.2963.9387 vlan101      101    N/A    smartgroup26
"""

ZTE_SHOW_INTERFACE_BRIEF = """show interface brief
Interface               Attribute  Mode         BW    Admin Phy   Prot  Description                                               
cgei-0/1/1/49           optical    Duplex/full  100G  up    up    up                                                              
cgei-0/1/1/50           optical    Duplex/full  100G  up    up    up    To-yihuyilian                                             
cgei-0/1/1/51           optical    Duplex/full  100G  down  down  down                                                            
xxvgei-0/1/1/1          optical    Duplex/full  25G   up    up    up    To-suanliSW01-25GE0/51                                    
"""

ZTE_SHOW_IP_INTERFACE_BRIEF = """show ip interface brief 
Interface                       IP-Address      Mask            Admin Phy  Prot 
cgei-0/1/1/55                   unassigned      unassigned      up    up   up
mgmt_eth                        10.114.102.1    255.255.255.0   up    down down
vlan101                         10.147.1.254    255.255.255.0   up    up   up
"""

ZTE_SHOW_OPTICALINFO_BRIEF = """show opticalinfo brief
Interface         Type              Wavelength  RxPower(dBm)          TxPower(dBm)          Status            
xxvgei-0/1/1/1    25G-100m-SFP28    850nm       -1.4/[-10.3,2.4]      0.1/[-8.4,3.4]        Normal            
xxvgei-0/1/1/2    25G-100m-SFP28    850nm       -1.1/[-10.3,2.4]      -0.1/[-8.4,3.4]       Normal            
xxvgei-0/1/1/5    offline                                                                                
"""

ZTE_SHOW_IP_FORWARDING_ROUTE = """show ip forwarding route
Routes:  82           Route-paths:  86
IPv4 Routing Table:
Headers: Dest: Destination,  Gw: Gateway,  Pri: Priority;
Codes  : BROADC: Broadcast, USER-I: User-ipaddr, USER-S: User-special,
         MULTIC: Multicast, USER-N: User-network, DHCP-D: DHCP-DFT,
         ASBR-V: ASBR-VPN, STAT-V: Static-VRF, DHCP-S: DHCP-static,
         GW-FWD: PS-BUSI, NAT64: Stateless-NAT64, LDP-A: LDP-area,
         GW-UE: PS-USER, P-VRF: Per-VRF-label, TE: RSVP-TE, NAT-M : NAT-mask
         BP: BRAS-pool, HAGP: Hybrid-access-gateway-protocol;
Status codes: *valid, >best, R: Relay;
    Dest               Gw              Interface          Owner       Pri Metric
*>  0.0.0.0/0          120.203.217.117 smartgroup1        Static      1   0     
*>  10.147.1.0/24      10.147.1.253    vlan101            Direct      0   0     
"""

ZTE_SHOW_IP_OSPF_NEIGHBOR = """show ip ospf neighbor 
Codes: *: Multi-Area Interface

            OSPF Router with ID (10.147.39.253) (Process ID 1)

Neighbor ID     Pri State        DeadTime  Address         Interface
10.147.39.252   200 FULL/DR      00:00:31  10.147.39.252   vlan1003

            OSPF Router with ID (10.147.3.253) (Process ID 100)

Neighbor ID     Pri State        DeadTime  Address         Interface
10.147.3.187    1   FULL/DROTHER 00:00:36  10.147.3.187    vlan103
10.147.3.188    1   FULL/DROTHER 00:00:36  10.147.3.188    vlan103
"""

ZTE_SHOW_FAN = """show fan 
[shelf 0 LCC]:
Fan speed mini level: 4
Group 0: online
Fan speed mode: auto
Fan       name: UMBFS FAN
Fan  direction: out-direction
Index      Status      Speed
  0    work normally   40%

Group 1: online
Fan speed mode: auto
Fan       name: UMBFS FAN
Fan  direction: out-direction
Index      Status      Speed
  0    work normally   41%
"""

ZTE_SHOW_POWER = """show power 
[shelf 0 LCC]:
Total power capacity   : 1093.95W   Total used power    : 122.28W
Power type             : AC         Power group numbers : 2
Power modules per group: 1          Division numbers    : 1
Redundancy type        : N+N       
Power module number    : 2/2       

Group A power capacity : 547.65W
Group B power capacity : 546.30W
Used power             : 122.28W

Supply   Power  Power       Power       Phy      Power    Com      Run      Input
Division Module Name        Vendor      Status   Status   Status   Status   Type
0        A0     CRPS550N    Great Wall  online   normal   normal   normal   N/A,N/A
0        B0     CRPS550N    Great Wall  online   normal   normal   normal   N/A,N/A
"""

ZTE_SHOW_TEMPERATURE_DETAIL = """show temperature detail 
[shelf 0, slot 1]
BoardType I2C Addr Description   Status  Minor Major Fatal Overheat Temper
--------------------------------------------------------------------------
MPU        1   4   cpu           Normal   85    90    95     110     33
MPU        1   87  mb remote     Normal   80    81    85     85      33

[shelf 0, environment]
Type   Status   High-threshold   Low-threshold    Temper
--------------------------------------------------------
ENV    Normal         80           -25              31  
"""

ZTE_SHOW_VERSION = """show version 
ZXR10 5960
ZTE ZXR10 Software, Version: 5900 V6.00.04.20P01, Release software
Copyright (c) 2024 by ZTE Corporation
Built on 2024/08/07 23:31:22
System image file is <sysdisk0: verset/5960X_ZX222081_V6.00.04.20P01.set>, file size is 739,003,936 Bytes
System image is loaded from local
System uptime is 485 day(s), 2 hour(s), 56 minute(s)

[MPU(M), shelf 0, panel 1]:
Board Name        : 5960X-56QU-HF
Board Type        : MPU
System BaudRate   : 9,600 bps
MPU-0/1/0, MSC:
Main Processor  :  ZX222081
Bootrom Version :  V3.01
Creation Date   :  2024/03/28 23:30:00
System Nvram    :  8,192 bytes
System Memory   :  8,192 Mbytes
CPU Core Num    :  8 Cores
Uptime is 485 day(s), 2 hour(s), 56 minute(s)
"""

ZTE_SHOW_CLOCK = """show clock 
16:03:15 Beijing Fri Jul 31 2026
"""

ZTE_SHOW_LOGGING = """show logging buffer almlog 
Log acceptance: on
Log matched: 69106353
Log in buffer: 521
Buffer occupied: 78.33%
Log total size: 160412 Byte
Log file path: /datadisk0/LOG/ALARM/ 

LogID:69325034 2026-07-31 15:56:38.581 Class:Alarm  [A notification 50104 ID 69100517 level 6 occurred at 15:56:38 07-31-2026 sent by JXYC-YunWangBa-5960X-02 MPU-0/
1/0
%MAC% MAC address port moved.  MAC 9c71.3ab1.e21c VLAN 2026 has moved from smartgroup25 to smartgroup26(BMACOld:N/A;BMACNew:N/A).]
"""


def test_zte_show_lldp_neighbor():
    records = parse_with_textfsm("zte_zxros", "show lldp neighbor", ZTE_SHOW_LLDP_NEIGHBOR)
    assert len(records) >= 3
    assert records[0]["INTERFACE"] == "xxvgei-0/1/1/40"
    assert records[0]["HOLDTIME"] == "102"
    assert records[1]["INTERFACE"] == "cgei-0/1/1/55"


def test_zte_lldp_suggestions_expose_only_the_canonical_command():
    suggestions = list_template_suggestions("zte_zxros", "show lldp", 8)
    assert [item["command"] for item in suggestions] == ["show lldp neighbor"]


def test_zte_show_vlan():
    records = parse_with_textfsm("zte_zxros", "show vlan", ZTE_SHOW_VLAN)
    assert len(records) >= 6
    assert records[0]["VLAN_ID"] == "1"
    assert records[0]["NAME"] == "vlan0001"


def test_zte_show_mac_table():
    records = parse_with_textfsm("zte_zxros", "show mac table", ZTE_SHOW_MAC_TABLE)
    assert len(records) == 3
    assert records[0]["MAC_ADDRESS"] == "5254.00fd.5621"
    assert records[0]["VLAN"] == "103"
    assert records[0]["DESTINATION_PORT"] == "smartgroup22"


def test_zte_show_arp():
    records = parse_with_textfsm("zte_zxros", "show arp", ZTE_SHOW_ARP)
    assert len(records) == 5
    assert records[0]["IP_ADDRESS"] == "10.114.102.1"
    assert records[0]["MAC_ADDRESS"] == "fc44.9f6c.a38d"
    assert records[0]["INTERFACE"] == "mgmt_eth"


def test_zte_show_interface_brief():
    records = parse_with_textfsm("zte_zxros", "show interface brief", ZTE_SHOW_INTERFACE_BRIEF)
    assert len(records) == 4
    assert records[0]["INTERFACE"] == "cgei-0/1/1/49"
    assert records[0]["ADMIN_STATUS"] == "up"
    assert records[1]["DESCRIPTION"] == "To-yihuyilian"


def test_zte_show_ip_interface_brief():
    records = parse_with_textfsm("zte_zxros", "show ip interface brief", ZTE_SHOW_IP_INTERFACE_BRIEF)
    assert len(records) == 3
    assert records[1]["INTERFACE"] == "mgmt_eth"
    assert records[1]["IP_ADDRESS"] == "10.114.102.1"


def test_zte_show_opticalinfo_brief():
    records = parse_with_textfsm("zte_zxros", "show opticalinfo brief", ZTE_SHOW_OPTICALINFO_BRIEF)
    assert len(records) == 3
    assert records[0]["INTERFACE"] == "xxvgei-0/1/1/1"
    assert records[0]["STATUS"] == "Normal"


def test_zte_show_ip_forwarding_route():
    records = parse_with_textfsm("zte_zxros", "show ip forwarding route", ZTE_SHOW_IP_FORWARDING_ROUTE)
    assert len(records) == 2
    assert records[0]["NETWORK"] == "0.0.0.0/0"
    assert records[0]["NEXTHOP"] == "120.203.217.117"


def test_zte_show_ip_ospf_neighbor():
    records = parse_with_textfsm("zte_zxros", "show ip ospf neighbor", ZTE_SHOW_IP_OSPF_NEIGHBOR)
    assert len(records) == 3
    assert records[0]["NEIGHBOR_ID"] == "10.147.39.252"
    assert records[0]["STATUS"] == "FULL/DR"


def test_zte_show_fan():
    records = parse_with_textfsm("zte_zxros", "show fan", ZTE_SHOW_FAN)
    assert len(records) == 2
    assert records[0]["INDEX"] == "0"
    assert records[0]["SPEED"] == "40%"


def test_zte_show_power():
    records = parse_with_textfsm("zte_zxros", "show power", ZTE_SHOW_POWER)
    assert len(records) == 2
    assert records[0]["MODULE"] == "A0"
    assert records[0]["PHY_STATUS"] == "online"


def test_zte_show_temperature_detail():
    records = parse_with_textfsm("zte_zxros", "show temperature detail", ZTE_SHOW_TEMPERATURE_DETAIL)
    assert len(records) >= 2
    assert records[0]["BOARD_TYPE"] == "MPU"
    assert records[0]["TEMPERATURE"] == "33"


def test_zte_show_version():
    records = parse_with_textfsm("zte_zxros", "show version", ZTE_SHOW_VERSION)
    assert len(records) == 1
    assert records[0]["MODEL"] == "5960"
    assert records[0]["VERSION"] == "5900 V6.00.04.20P01"


def test_zte_show_clock():
    records = parse_with_textfsm("zte_zxros", "show clock", ZTE_SHOW_CLOCK)
    assert len(records) == 1
    assert records[0]["TIME"] == "16:03:15"


def test_zte_show_logging_buffer_almlog():
    records = parse_with_textfsm("zte_zxros", "show logging buffer almlog", ZTE_SHOW_LOGGING)
    assert len(records) == 1
    assert records[0]["LOG_ID"] == "69325034"


def test_zte_normalizer_factory():
    norm = NormalizerFactory.get_normalizer("zte_zxros")
    assert isinstance(norm, ZTENormalizer)
    
    dev = norm.parse_device_info("zte-sw-01", ZTE_SHOW_VERSION)
    assert dev.vendor == "ZTE"
    assert dev.platform == "zte_zxros"
    assert dev.model == "5960"
    assert dev.version == "5900 V6.00.04.20P01"

    intfs = norm.parse_interfaces("zte-sw-01", ZTE_SHOW_INTERFACE_BRIEF, ZTE_SHOW_IP_INTERFACE_BRIEF)
    assert len(intfs) >= 4
    
    neighbors = norm.parse_neighbors("zte-sw-01", ZTE_SHOW_LLDP_NEIGHBOR)
    assert len(neighbors) >= 3
