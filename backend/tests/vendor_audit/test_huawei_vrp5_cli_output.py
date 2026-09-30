import pytest

from api.playbooks.builtin_scenarios import BUILTIN_SCENARIOS
from api.playbooks.scenarios import resolve_platform_phases
from core.textfsm import _find_template, smart_parse_cli
from services.operational_data_service import _resolve_commands
from services.topology_service import _extract_observation_fields, _parse_shared_lldp_output


VRP5_OUTPUTS = {
    "display interface brief": """<LSW6>display interface brief
PHY: Physical
*down: administratively down
(l): loopback
(s): spoofing
InUti/OutUti: input utility/output utility
Interface                   PHY   Protocol InUti OutUti   inErrors  outErrors
GigabitEthernet0/0/1        up    up          0%     0%          0          0
                                           LoopBack0                   up    up(s)       0%     0%          0          0
<LSW6""",
    "display arp all": """[display arp all]
IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE INTERFACE      VPN-INSTANCE
                                          VLAN
------------------------------------------------------------------------------
10.253.10.2     4c1f-ccbf-01b8            I -  Vlanif10
10.253.10.1     4c1f-cc81-7a43  14        D-0  GE0/0/4
                                          10
------------------------------------------------------------------------------
Total:2         Dynamic:1       Static:0     Interface:1""",
    "display lldp neighbor brief": """[display lldp neighbor brief]
Local Intf   Neighbor Dev             Neighbor Intf             Exptime
GE0/0/4      LSW4                     GE0/0/4                   115""",
    "display ntp-service status": """[display ntp-service status]
 clock status: unsynchronized
 clock stratum: 16
 reference clock ID: none
 nominal frequency: 64.0000 Hz
 actual frequency: 64.0000 Hz
 clock precision: 2^12
 clock offset: 0.0000 ms
 root delay: 0.00 ms
 root dispersion: 0.00 ms
 peer dispersion: 0.00 ms
 reference time: 00:00:00.000 UTC Jan 1 1900(00000000.00000000)""",
    "display environment": """<LSW6>dis environment
Environment information:
Temperature information:
SlotID   CurrentTemperature  LowLimit  HighLimit
             (deg c )        (deg c)   (deg c )
 0              0              0         70
<LSW6>""",
    "display version": """<LSW6>dis ver
<LSW6>dis version
Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.110 (S5700 V200R001C00)
Copyright (c) 2000-2011 HUAWEI TECH CO., LTD
Quidway S5700-28C-HI Routing Switch uptime is 0 week, 0 day, 3 hours, 57 minutes
<LSW6>""",
    "display fan": """<LSW6>display fan
Slot 0: Fan 0 is absent.
<LSW6>""",
    "display eth-trunk": """[LSW4-GigabitEthernet0/0/2]display eth-trunk
Eth-Trunk2's state information is:
Local:
LAG ID: 2                   WorkingMode: STATIC
Preempt Delay: Disabled     Hash arithmetic: According to SIP-XOR-DIP
System Priority: 32768      System ID: 4c1f-cc81-7a43
Least Active-linknumber: 1  Max Active-linknumber: 8
Operate status: up          Number Of Up Port In Trunk: 2
--------------------------------------------------------------------------------
ActorPortName          Status   PortType PortPri PortNo PortKey PortState Weight
GigabitEthernet0/0/2   Selected 1GE      32768   3      561     10111100  1
GigabitEthernet0/0/3   Selected 1GE      32768   4      561     10111100  1
Partner:
--------------------------------------------------------------------------------
ActorPortName          SysPri   SystemID        PortPri PortNo PortKey PortState
GigabitEthernet0/0/2   32768    4c1f-cc3c-7de1  32768   3      561     10111100""",
    "display transceiver verbose": """<LSW6>display transceiver verbose
GigabitEthernet0/0/23 transceiver information:
-------------------------------------------------------------
Common information:
  Transceiver Type               :1000_BASE_SX_SFP
  Connector Type                 :LC
  Wavelength(nm)                 :850
  Transfer Distance(m)           :275(OM1),550(OM2),1000(OM3)
  Digital Diagnostic Monitoring  :YES
  Vendor Name                    :HUAWEI
  Vendor Part Number             :02315204
  Ordering Name                  :
Manufacture information:
  Manu. Serial Number            :PRL0RV9
  Manufacturing Date             :2025-03-18
Alarm information:
Diagnostic information:
  Temperature(Celsius)                    :39.00
  Voltage(V)                              :3.32
  Bias Current(mA)                        :6.91
  Bias High Threshold(mA)                 :33.34
  Bias Low Threshold(mA)                  :1.67
  Current Rx Power(dBM)                   :-4.59
  Default Rx Power High Threshold(dBM)    :0.00
  Default Rx Power Low Threshold(dBM)     :-16.99
  Current Tx Power(dBM)                   :-5.10
  Default Tx Power High Threshold(dBM)    :0.00
  Default Tx Power Low Threshold(dBM)     :-12.50
  User Set Rx Power High Threshold(dBM)   :0.00
  User Set Rx Power Low Threshold(dBM)    :-16.99
  User Set Tx Power High Threshold(dBM)   :0.00
  User Set Tx Power Low Threshold(dBM)    :-12.50""",
}


@pytest.mark.parametrize("command", list(VRP5_OUTPUTS))
def test_vrp5_sample_commands_parse(command: str):
    result = smart_parse_cli(VRP5_OUTPUTS[command], command, platform="huawei_vrp")

    assert result["success"] is True
    assert result["matched_rows"] > 0
    assert result["data"]


def test_vrp5_sample_has_expected_records_and_alias_lookup():
    interface = smart_parse_cli(VRP5_OUTPUTS["display interface brief"], "display interface brief", "huawei_vrp")
    assert {row["INTERFACE"] for row in interface["data"]} == {
        "GigabitEthernet0/0/1",
        "LoopBack0",
    }

    arp = smart_parse_cli(VRP5_OUTPUTS["display arp all"], "display arp all", "huawei_vrp")
    assert {row["IP_ADDRESS"] for row in arp["data"]} == {"10.253.10.1", "10.253.10.2"}
    arp_by_ip = {row["IP_ADDRESS"]: row for row in arp["data"]}
    assert arp_by_ip["10.253.10.1"]["VLAN_ID"] == "10"

    lldp = smart_parse_cli(VRP5_OUTPUTS["display lldp neighbor brief"], "display lldp neighbor brief", "huawei_vrp")
    assert lldp["data"][0]["NEIGHBOR_NAME"] == "LSW4"

    version = smart_parse_cli(VRP5_OUTPUTS["display version"], "display version", "huawei_vrp")
    assert version["data"][0]["VRP_VERSION"] == "5.110"
    assert "S5700-28C-HI" in version["data"][0]["MODEL"]

    eth = smart_parse_cli(VRP5_OUTPUTS["display eth-trunk"], "display eth-trunk", "huawei_vrp")
    assert {row["INTERFACE"] for row in eth["data"]} == {
        "GigabitEthernet0/0/2",
        "GigabitEthernet0/0/3",
    }

    transceiver = smart_parse_cli(
        VRP5_OUTPUTS["display transceiver verbose"],
        "display transceiver verbose",
        "huawei_vrp",
    )
    assert transceiver["data"][0]["CURRENT_RX_POWER"] == "-4.59"
    assert _find_template("huawei_vrp", "display transceiver verbose").name == (
        "huawei_vrp_display_transceiver_interface.textfsm"
    )


def test_vrp5_abbreviated_commands_and_export_wrappers_parse():
    fan = smart_parse_cli(
        """--- LSW4 ---
<LSW4>dis fan
Slot 0: Fan 0 is absent.
<LSW4>
""",
        "dis fan",
        "huawei_vrp",
    )
    eth = smart_parse_cli(
        """--- LSW4 ---
<LSW4>dis eth-trunk
Eth-Trunk2's state information is:
Local:
GigabitEthernet0/0/2 Selected 1GE 32768 3 561 10111100 1
GigabitEthernet0/0/3 Selected 1GE 32768 4 561 10111100 1
--- LSW4 ---
""",
        "dis eth-trunk",
        "huawei_vrp",
    )
    assert fan["success"] and fan["data"][0]["STATUS"] == "absent"
    assert eth["success"] and {row["INTERFACE"] for row in eth["data"]} == {
        "GigabitEthernet0/0/2",
        "GigabitEthernet0/0/3",
    }


def test_vrp5_interface_description_is_structured():
    result = smart_parse_cli(
        """<LSW4>dis interface description
PHY: Physical
*down: administratively down
(l): loopback
Interface                   PHY   Protocol Description
GigabitEthernet0/0/2        up    up       uplink-to-core
LoopBack0                   up    up(s)
<LSW4>
""",
        "display interface description",
        "huawei_vrp",
    )
    assert result["success"] is True
    assert result["data"][0]["DESCRIPTION"] == "uplink-to-core"
    assert result["data"][1]["INTERFACE"] == "LoopBack0"


def test_vrp5_lldp_reaches_topology_with_both_huawei_table_layouts():
    outputs = (
        """[display lldp neighbor brief]
Local Intf Neighbor Dev Neighbor Intf Exptime
GE0/0/4 LSW4 GE0/0/4 115
""",
        """<LSW4>DIS lldp neighbor brief
Local Interface Exptime(s) Neighbor Interface Neighbor Device
GE1/0/1 105 GigabitEthernet3/0 acc-h3c-sw2
<LSW4>
""",
        """local interface exptime(s) neighbor interface neighbor device
ge0/0/2 105 ge0/0/3 lsw4
""",
    )
    for output in outputs:
        parsed = _parse_shared_lldp_output("huawei_vrp", "display lldp neighbor brief", output)
        observation = _extract_observation_fields(parsed[0])
        assert observation["neighbor_name"]
        assert observation["source_port_normalized"]
        assert observation["target_port_normalized"]


def test_vrp5_command_catalog_uses_device_compatible_spellings(isolated_db):
    commands = _resolve_commands("huawei_vrp", ["fan", "eth_trunk", "neighbors"])
    assert commands["fan"] == ["dis fan"]
    assert commands["eth_trunk"] == ["display eth-trunk"]
    assert commands["neighbors"] == ["display lldp neighbor brief"]


def test_all_huawei_playbooks_resolve_for_vrp5_and_vrp8_aliases():
    for scenario in BUILTIN_SCENARIOS:
        if "huawei_vrp" not in scenario.get("supported_platforms", []):
            continue
        phases, resolved = resolve_platform_phases(scenario["platform_phases"], "huawei_vrp")
        assert resolved == "huawei_vrp"
        assert isinstance(phases, dict)
        phases_v8, resolved_v8 = resolve_platform_phases(scenario["platform_phases"], "huawei_vrpv8")
        assert resolved_v8 in {"huawei_vrpv8", "huawei_vrp"}
        assert isinstance(phases_v8, dict)
