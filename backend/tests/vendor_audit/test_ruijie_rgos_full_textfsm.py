import pytest
from core.textfsm import smart_parse_cli


def test_ruijie_show_lldp_neighbors():
    output = """
show lldp neighbors 
Capability codes:
    (R) Router, (B) Bridge, (T) Telephone, (C) DOCSIS Cable Device
    (W) WLAN Access Point, (P) Repeater, (S) Station, (O) Other
System Name                 Local Intf          Port ID                          Capability   Aging-time
JXYCH-ZSY-P19F26-NET-VGW-S6 Te0/1               TenGigabitEthernet 0/6           P, B, R      1minutes 46seconds 
250-1                       
JXYCH-ZSY-P19F26-NET-VGW-S6 Te0/2               TenGigabitEthernet 0/6           P, B, R      1minutes 48seconds 
250-2                       
JXYCH-ZSY-P19F26-KHZX-JR-S6 Te0/11              Te0/11                           B, R         1minutes 53seconds 
231-1                       
PTN6180-YZQ-yunshujuzhongxi Te0/39              gei-1/8/0/7                      B, R         1minutes 48seconds
"""
    result = smart_parse_cli(output, "show lldp neighbors", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 4
    assert result["data"][0]["NEIGHBOR"] == "JXYCH-ZSY-P19F26-NET-VGW-S6"
    assert result["data"][0]["INTERFACE"] == "Te0/1"
    assert result["data"][0]["NEIGHBOR_INTERFACE"] == "TenGigabitEthernet 0/6"


def test_ruijie_show_vlan():
    output = """
show vlan 
VLAN       Name                             Status    Ports
---------- -------------------------------- --------- -----------------------------------
         1 VLAN0001                         STATIC    Gi1/0/1, Gi1/0/2, Gi1/0/3, Gi1/0/4    
                                                      Gi1/0/5, Gi1/0/6, Gi1/0/7, Gi1/0/8    
      3499 vpn                              STATIC    Te2/0/49, Te2/0/50
"""
    result = smart_parse_cli(output, "show vlan", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["VLAN_ID"] == "1"
    assert result["data"][0]["VLAN_NAME"] == "VLAN0001"
    assert result["data"][1]["VLAN_ID"] == "3499"


def test_ruijie_show_arp():
    output = """
show arp
Protocol  Address          Age(min)  Hardware        Type   Interface               
Internet  223.82.202.65    0         ccbb.fe1a.2104  arpa   AggregatePort 1.1       
Internet  223.82.202.66    2         ccbb.fe1a.2104  arpa   AggregatePort 1.1       
Internet  223.82.202.67    18        ccbb.fe1a.2104  arpa   AggregatePort 1.1       
Internet  223.82.202.69    57        ccbb.fe1a.2104  arpa   AggregatePort 1.1
"""
    result = smart_parse_cli(output, "show arp", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 4
    assert result["data"][0]["IP_ADDRESS"] == "223.82.202.65"
    assert result["data"][0]["MAC_ADDRESS"] == "ccbb.fe1a.2104"
    assert result["data"][0]["INTERFACE"] == "AggregatePort 1.1"


def test_ruijie_show_interfaces_status():
    output = """
show interfaces  status 
Interface                                Status    Vlan   Duplex   Speed     Type  
---------------------------------------- --------  ----   -------  --------- ------
GigabitEthernet 1/0/1                    down      1      Unknown  Unknown   copper
GigabitEthernet 1/0/47                   down      routed Unknown  Unknown   copper
GigabitEthernet 1/0/48                   up        routed Full     1000M     copper
TenGigabitEthernet 1/0/51                up               Full     10G       fiber
"""
    result = smart_parse_cli(output, "show interfaces status", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 4
    assert result["data"][0]["INTERFACE"] == "GigabitEthernet 1/0/1"
    assert result["data"][0]["STATUS"] == "down"
    assert result["data"][2]["VLAN"] == "routed"
    assert result["data"][2]["SPEED"] == "1000M"
    assert result["data"][3]["INTERFACE"] == "TenGigabitEthernet 1/0/51"


def test_ruijie_show_interfaces_transceiver():
    output = """
show interfaces transceiver 

========Interface TenGigabitEthernet 1/0/49========
Transceiver Type    :  10GBASE-LR-SFP+
Connector Type      :  LC
Wavelength(nm)      :  1310
Digital Diagnostic Monitoring  : YES
Vendor Serial Number           : G1SPARK055550   

Current diagnostic parameters[AP:Average Power]:
Temp(Celsius)   Voltage(V)      Bias(mA)            RX power(dBm)       TX power(dBm)
26(OK)          3.28(OK)        0.00(OK)            -40.00(alarm)[AP]   -40.00(OK)

Transceiver current alarm information:
RX power low alarm
RX power low warn
RX loss of signal
Interface TenGigabitEthernet 1/0/49 alarm detect.
"""
    result = smart_parse_cli(output, "show interfaces transceiver", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["INTERFACE"] == "TenGigabitEthernet 1/0/49"
    assert result["data"][0]["SERIAL_NUMBER"] == "G1SPARK055550"
    assert result["data"][0]["TEMPERATURE"] == "26(OK)"
    assert result["data"][0]["RX_POWER"] == "-40.00(alarm)[AP]"


def test_ruijie_show_ip_route():
    output = """
show ip route 

Codes:  C - Connected, L - Local, S - Static
        R - RIP, O - OSPF, B - BGP, I - IS-IS, V - Overflow route

Gateway of last resort is no set
C     10.88.1.0/24 is directly connected, VLAN 3499
C     10.88.1.251/32 is local host.
"""
    result = smart_parse_cli(output, "show ip route", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["NETWORK"] == "10.88.1.0/24"
    assert result["data"][0]["INTERFACE"] == "VLAN 3499"


def test_ruijie_show_ntp_status():
    output = """
show ntp status
Clock is synchronized, stratum 4, reference is 10.88.11.137
nominal freq is 250.000 Hz, actual freq is 250.000 Hz, precision is 2**23
reference time is EE158146.19337799 (15:52:38.000 UTC Thu, Jul 30, 2026)
clock offset is -0.00036 sec, root delay is 0.04226 sec
root dispersion is 0.01201 msec, peer dispersion is 0.00371 msec
"""
    result = smart_parse_cli(output, "show ntp status", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["SYNCHRONIZED"] == "synchronized"
    assert result["data"][0]["STRATUM"] == "4"
    assert result["data"][0]["REFERENCE"] == "10.88.11.137"


def test_ruijie_show_fan():
    output = """
show  fan 
Fan id Type             Status     Hardware Version Serial Number  
------ ---------------- ---------- ---------------- ---------------
1      M1EFAN III-F     ok         1.20             G1T311H003743  
2      M1EFAN III-F     ok         1.20             G1T311H003764  
"""
    result = smart_parse_cli(output, "show fan", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["FAN_ID"] == "1"
    assert result["data"][0]["STATUS"] == "ok"
    assert result["data"][0]["SERIAL_NUMBER"] == "G1T311H003743"


def test_ruijie_show_power():
    output = """
show power
Power-id Power-type           Status     Attribute Coexist  Hardware-Version Serial                          Supply(W) Exception
-------- -------------------- ---------- --------- -------- ---------------- ------------------------------- --------- --------------------
1        RG-PA550I-F          ok         N/A       no       21               R407A6A211910                   550       N/A
2        RG-PA550I-F          ok         N/A       no       21               R407A65210927                   550       N/A
"""
    result = smart_parse_cli(output, "show power", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["POWER_ID"] == "1"
    assert result["data"][0]["MODEL"] == "RG-PA550I-F"
    assert result["data"][0]["STATUS"] == "ok"


def test_ruijie_show_temperature():
    output = """
show temperature
Temperature:
------------------------------------------------------------------------------------------------------------
Slot    Card_type                        Temp_name     Warning         Shutdown       Current       Status
                                                      (Celsius)        (Celsius)     (Celsius)
------------------------------------------------------------------------------------------------------------
0       RG-S6231-48XS8CQ                 air_inlet       50              60              19           ok
0       RG-S6231-48XS8CQ                 air_outlet      65              75              26           ok
"""
    result = smart_parse_cli(output, "show temperature", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["SLOT"] == "0"
    assert result["data"][0]["TEMP_NAME"] == "air_inlet"
    assert result["data"][0]["CURRENT_TEMP"] == "19"


def test_ruijie_show_interfaces_description():
    output = """
show interfaces description
Interface                                Status   Administrative Description
---------------------------------------- -------- -------------- -----------
TenGigabitEthernet 0/1                   up       up             dT:[JXYCH-ZSY-P19F26-NET-VGW-S6250-1]-10GE0/6-10G
TenGigabitEthernet 0/3                   down     down           NO USE
"""
    result = smart_parse_cli(output, "show interfaces description", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["INTERFACE"] == "TenGigabitEthernet 0/1"
    assert result["data"][0]["STATUS"] == "up"
    assert result["data"][0]["DESCRIPTION"] == "dT:[JXYCH-ZSY-P19F26-NET-VGW-S6250-1]-10GE0/6-10G"


def test_ruijie_show_cpu():
    output = """
show cpu
===============================================
[Slot 0: RG-S6231-48XS8CQ]
CPU Using Rate Information
CPU utilization in five seconds:   1.10%
CPU utilization in one minute:     0.80%
CPU utilization in five minutes:   0.70%
"""
    result = smart_parse_cli(output, "show cpu", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["CPU_5SEC"] == "1.10"
    assert result["data"][0]["CPU_1MIN"] == "0.80"
    assert result["data"][0]["CPU_5MIN"] == "0.70"


def test_ruijie_show_memory():
    output = """
show memory
System Memory: 3962904KB total, 1015668KB used, 2947236KB free, 3739815KB available, 21.3% used rate
Swap: 1981448KB total, 1981448KB free
"""
    result = smart_parse_cli(output, "show memory", platform="ruijie_os")
    assert result["success"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["TOTAL_MEMORY"] == "3962904"
    assert result["data"][0]["USED_MEMORY"] == "1015668"
    assert result["data"][0]["FREE_MEMORY"] == "2947236"
    assert result["data"][0]["USED_PCT"] == "21.3"
