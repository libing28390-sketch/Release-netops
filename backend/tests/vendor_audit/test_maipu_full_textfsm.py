import pytest
from core.textfsm import smart_parse_cli


def test_maipu_show_lldp_neighbors():
    output = """
show lldp neighbors 

26 neighbor entries in system
Capability codes:
        (R) Router, (B) Bridge, (T) Telephone, (C) DOCSIS Cable Device
        (W) WLAN Access Point, (P) Repeater, (S) Station, (O) Other

Index        Local Intf           Hold-time  Capability     Peer Intf                        Device ID          
1            gi0/4                120        B,R            gigabitethernet0/1               JXYIC-MAN-YQZ-MP-S3330
2            gi0/7                120        B,R            gei-1/6/0/2                      PTN6180-YZQ-donghuan
19           te0/28               120        B,R            GigabitEthernet0/1/3             JXYIC-NMS-CE01-HWNE8000-M8
"""
    result = smart_parse_cli(output, "show lldp neighbors", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["INTERFACE"] == "gi0/4"
    assert result["data"][0]["NEIGHBOR_INTERFACE"] == "gigabitethernet0/1"
    assert result["data"][0]["NEIGHBOR"] == "JXYIC-MAN-YQZ-MP-S3330"


def test_maipu_show_vlan():
    output = """
show vlan 
---- ---- -------------------------------- ------- --------- -----------------------------
NO.  VID  VLAN-Name                        Owner   Mode      Interface           
---- ---- -------------------------------- ------- --------- -----------------------------
1    1    DEFAULT                          static  Untagged  gi0/1  gi0/5  gi0/21  
2    15   VLAN0015                         static  Tagged    gi0/2  gi0/5  gi0/15  
"""
    result = smart_parse_cli(output, "show vlan", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["VLAN_ID"] == "1"
    assert result["data"][0]["VLAN_NAME"] == "DEFAULT"
    assert result["data"][1]["VLAN_ID"] == "15"


def test_maipu_show_mac_address_all():
    output = """
show mac-address all 
                                Mac Address Table
----------------------------------------------------------------------------------

 VLAN          MAC           TYPE          INTERFACE             STATE       FLAG 
 ----     --------------    -------     --------------------    --------    ------
 1997     240F.9BAE.6133    STATIC      gi0/2                     FWD        [NC]
 1999     240F.9BAE.5FF0    STATIC      gi0/19                    FWD        [NC]
"""
    result = smart_parse_cli(output, "show mac-address all", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["VLAN_ID"] == "1997"
    assert result["data"][0]["MAC_ADDRESS"] == "240F.9BAE.6133"
    assert result["data"][0]["INTERFACE"] == "gi0/2"


def test_maipu_show_arp():
    output = """
Protocol  Address          Age (min)  Hardware Addr   Type   Interface
Internet  10.1.12.1               -   aabb.cc00.1010  ARPA   Ethernet0/1
Internet  192.168.96.1            0   0050.56c0.0001  ARPA   Ethernet0/0
"""
    result = smart_parse_cli(output, "show arp", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["IP_ADDRESS"] == "10.1.12.1"
    assert result["data"][0]["MAC_ADDRESS"] == "aabb.cc00.1010"
    assert result["data"][0]["INTERFACE"] == "Ethernet0/1"


def test_maipu_show_interface_switchport_brief():
    output = """
show interface switchport brief 
 Interface            Status     Link                 ActSpeed   ActDuplex  VSL      Type     Pvid  Desc
 -------------------------------------------------------------------------------------------------
 gi0/1                Enabled    Down                 Unknown    Unknown             Nni      1     
 gi0/2                Enabled    Up                   1000       Full                Nni      4094  192.168.15.9
 gi0/3                Enabled    Up                   1000       Full                Nni      1     
"""
    result = smart_parse_cli(output, "show interface switchport brief", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["INTERFACE"] == "gi0/1"
    assert result["data"][0]["STATUS"] == "Enabled"
    assert result["data"][1]["SPEED"] == "1000"
    assert result["data"][1]["DESCRIPTION"] == "192.168.15.9"


def test_maipu_show_ip_interface_brief():
    output = """
show ip interface brief 
Interface                        IP-Address      Status                Protocol Description
loopback0                        12.1.1.1        up                    up      
gigabitethernet0/4               192.168.168.9   up                    up       yuanzhouqu
gigabitethernet0/6               192.168.168.37  up                    up       fengcheng
"""
    result = smart_parse_cli(output, "show ip interface brief", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["INTERFACE"] == "loopback0"
    assert result["data"][0]["IP_ADDRESS"] == "12.1.1.1"
    assert result["data"][1]["DESCRIPTION"] == "yuanzhouqu"


def test_maipu_show_optical_all():
    output = """
show optical all 
 Name                     VendorName       LaserWaveLen(nm) Temperature(C)   Voltage(V)   TxPower(dBm) RxPower(dBm)
 ---------------------------------------------------------------------------------------------------------------------------
 gi0/1                    Hisense          850              43.957031        3.254400     -2.248995    -40.000000  
 gi0/2                    WXZTE            1310             46.164063        3.205800     -6.027554    -6.409238   
"""
    result = smart_parse_cli(output, "show optical all", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["INTERFACE"] == "gi0/1"
    assert result["data"][0]["VENDOR_NAME"] == "Hisense"
    assert result["data"][0]["TEMPERATURE"] == "43.957031"
    assert result["data"][0]["RX_POWER"] == "-40.000000"


def test_maipu_show_ip_route():
    output = """
show ip route 
Codes: C - Connected, L - Local, S - static, R - RIP,  B - BGP, i-ISIS

S   0.0.0.0/0 [1/0] via 10.114.105.2, 40w5d:10:03:49, vlan2000
C   1.1.1.0/30 is directly connected, 40w5d:10:03:50, vlan2001
S   10.114.28.0/24 [1/0] via 192.168.168.34, 118w1d:14:32:33, gigabitethernet0/11
"""
    result = smart_parse_cli(output, "show ip route", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 3
    assert result["data"][0]["NETWORK"] == "0.0.0.0/0"
    assert result["data"][0]["NEXTHOP_IP"] == "10.114.105.2"
    assert result["data"][0]["INTERFACE"] == "vlan2000"


def test_maipu_show_ntp_status():
    output = """
show ntp status 
Current NTP status information
 NTP ipv4 is disabled
 NTP ipv6 is disabled
Clock is unsynchronized, stratum 16, no reference clock 
reference time is EE16107B.516872B0 (18:03:39.317 Thu Jul 30 2026)
"""
    result = smart_parse_cli(output, "show ntp status", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["SYNCHRONIZED"] == "unsynchronized"
    assert result["data"][0]["STRATUM"] == "16"


def test_maipu_show_environment():
    output = """
show environment 
        System switch temperature is 68 C
        System mainboard temperature is 38 C
"""
    result = smart_parse_cli(output, "show environment", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["SWITCH_TEMP"] == "68"
    assert result["data"][0]["MAINBOARD_TEMP"] == "38"


def test_maipu_show_system_fan():
    output = """
show system fan 
 System FAN Information(Fan 1 - ONLINE)
 ----------------------------------------------------------------
                  Status:   Normal
             Description:   N/A
              Speed Rate:   25%
"""
    result = smart_parse_cli(output, "show system fan", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["FAN_ID"] == "1"
    assert result["data"][0]["STATUS"] == "Normal"
    assert result["data"][0]["SPEED_RATE"] == "25%"


def test_maipu_show_system_power():
    output = """
show system power 
 System Power Information(Power 1 - ONLINE)
 ----------------------------------------------------------------
                  Status:   Normal
              Last-Alarm:   Normal
             Description:   

 System Power Information(Power 2 - ONLINE)
 ----------------------------------------------------------------
                  Status:   Normal
              Last-Alarm:   Normal
             Description:   
"""
    result = smart_parse_cli(output, "show system power", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["POWER_ID"] == "1"
    assert result["data"][0]["STATUS"] == "Normal"
    assert result["data"][1]["POWER_ID"] == "2"


def test_maipu_show_version():
    output = """
show version 
               MyPower (R) Operating System Software
MyPower S3330 system image file (flash0: /flash/sp35-g-9.7.1.25(R).pck), version 9.7.1.25(integrity), Compiled on Sep 30 2021, 15:38:21

MyPower S3330 Version Information
        System ID           : ccd81f40cf44
        Hardware Model      : MyPower S3330-28GXF(V1)
        Hardware Version    : 002(Hotswap Unsupported)
        Bootloader Version  : 9.6.0.20
        Software Version    : 9.7.1.25(integrity)
        Software Image File : flash0: /flash/sp35-g-9.7.1.25(R).pck

System Uptime is 118 weeks 1 day
"""
    result = smart_parse_cli(output, "show version", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["SYSTEM_ID"] == "ccd81f40cf44"
    assert result["data"][0]["HARDWARE_MODEL"] == "MyPower S3330-28GXF(V1)"
    assert result["data"][0]["SOFTWARE_VERSION"] == "9.7.1.25(integrity)"


def test_maipu_show_cpu_monitor():
    output = """
show cpu monitor 
CPU core 0 utilization for five seconds: 19%; one minute: 17%; five minutes: 16%
"""
    result = smart_parse_cli(output, "show cpu monitor", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["CPU_5SEC"] == "19"
    assert result["data"][0]["CPU_1MIN"] == "17"
    assert result["data"][0]["CPU_5MIN"] == "16"


def test_maipu_show_memory_utilization():
    output = """
show memory utilization 
 Total memory is 485363712(462M) bytes
 Total memory used is 325042176(309M) bytes
 Current memory using percentage is 66%
"""
    result = smart_parse_cli(output, "show memory utilization", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["TOTAL_MEMORY"] == "485363712"
    assert result["data"][0]["USED_MEMORY"] == "325042176"
    assert result["data"][0]["USAGE_PCT"] == "66"


def test_maipu_show_clock():
    output = """
show clock 

UTC Thu Jul 30 18:11:19 2026
"""
    result = smart_parse_cli(output, "show clock", platform="maipu")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert "Jul 30 18:11:19 2026" in result["data"][0]["TIME"]
