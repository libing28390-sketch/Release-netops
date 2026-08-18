from __future__ import annotations

import ast
import unittest
from pathlib import Path

from services.normalizers.arista import AristaNormalizer
from services.normalizers.factory import NormalizerFactory
from services.normalizers.h3c import H3CNormalizer
from services.normalizers.juniper import JuniperNormalizer
from services.normalizers.ruijie import RuijieNormalizer
from services.normalizers.raisecom import RaisecomNormalizer


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cli"
DISCOVERY_SOURCE = Path(__file__).resolve().parents[2] / "services" / "discovery_service.py"


def _literal_assignment(name: str):
    tree = ast.parse(DISCOVERY_SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"Assignment {name} not found")


class NormalizerFactoryTests(unittest.TestCase):
    def test_supported_platform_aliases(self):
        expected = {
            "cisco_ios": "CiscoNormalizer",
            "huawei_vrpv8": "HuaweiNormalizer",
            "h3c_comware": "H3CNormalizer",
            "juniper_junos": "JuniperNormalizer",
            "arista_eos": "AristaNormalizer",
            "ruijie_os": "RuijieNormalizer",
            "raisecom_ros": "RaisecomNormalizer",
        }
        for platform, class_name in expected.items():
            with self.subTest(platform=platform):
                self.assertEqual(type(NormalizerFactory.get_normalizer(platform)).__name__, class_name)

    def test_unknown_platform_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported normalizer platform"):
            NormalizerFactory.get_normalizer("unknown_vendor")

    def test_discovery_profiles_enable_every_supported_vendor(self):
        profiles = _literal_assignment("COMMAND_PROFILES")
        expected = {
            "cisco_ios": "cisco_ios",
            "huawei_vrp": "huawei_vrp",
            "huawei_vrpv8": "huawei_vrp",
            "h3c_comware": "h3c_comware",
            "juniper_junos": "juniper_junos",
            "arista_eos": "arista_eos",
            "ruijie_rgos": "ruijie_rgos",
            "raisecom_ros": "raisecom_ros",
        }
        for platform, normalizer in expected.items():
            with self.subTest(platform=platform):
                self.assertEqual(profiles[platform]["normalizer"], normalizer)

    def test_vendor_aliases_do_not_fall_back_to_cisco(self):
        aliases = _literal_assignment("PLATFORM_ALIASES")
        expected = {
            "h3c": "h3c_comware",
            "comware": "h3c_comware",
            "juniper": "juniper_junos",
            "eos": "arista_eos",
            "ruijie_os": "ruijie_rgos",
            "raisecom": "raisecom_ros",
        }
        for alias, platform in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(aliases[alias], platform)

    def test_empty_output_is_safe_for_new_normalizers(self):
        normalizers = (H3CNormalizer(), JuniperNormalizer(), AristaNormalizer(), RuijieNormalizer(), RaisecomNormalizer())
        for normalizer in normalizers:
            with self.subTest(normalizer=type(normalizer).__name__):
                device = normalizer.parse_device_info("device-id", "")
                self.assertEqual(device.hostname, "device-id")
                self.assertEqual(normalizer.parse_interfaces("device-id", "", ""), [])
                self.assertEqual(normalizer.parse_neighbors("device-id", ""), [])


class H3CNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = H3CNormalizer()

    def test_real_version_fixture(self):
        raw = (FIXTURES / "h3c" / "h3c_comware" / "display_version" / "comware_v7_wx2880x.txt").read_text(
            encoding="utf-8"
        )
        device = self.normalizer.parse_device_info("dev-h3c", raw)
        self.assertEqual(device.hostname, "H3C")
        self.assertEqual(device.vendor, "H3C")
        self.assertEqual(device.platform, "h3c_comware")
        self.assertEqual(device.model, "WX2880X")
        self.assertIn("7.1.064", device.version)
        self.assertIn("4 weeks", device.uptime)

    def test_real_interface_brief_fixture(self):
        raw = (
            FIXTURES / "h3c" / "h3c_comware" / "display_interface_brief" / "comware_v7.txt"
        ).read_text(encoding="utf-8")
        interfaces = {item.name_display: item for item in self.normalizer.parse_interfaces("dev-h3c", "", raw)}
        self.assertEqual(len(interfaces), 3)
        self.assertEqual(interfaces["gi1/0/6"].oper_status, "down")
        self.assertEqual(interfaces["lo0"].primary_ip, "2.2.2.9")
        self.assertEqual(interfaces["vlan999"].interface_type, "svi")

    def test_real_lldp_list_fixture(self):
        raw = (
            FIXTURES
            / "h3c"
            / "h3c_comware"
            / "display_lldp_neighbor_information_list"
            / "comware_v7_s5130.txt"
        ).read_text(encoding="utf-8")
        neighbors = self.normalizer.parse_neighbors("dev-h3c", raw)
        self.assertEqual(len(neighbors), 3)
        self.assertEqual(neighbors[0].local_interface, "gi1/0/1")
        self.assertEqual(neighbors[0].remote_device, "System1")
        self.assertEqual(neighbors[0].remote_interface, "gi1/0/5")


class JuniperNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = JuniperNormalizer()

    def test_device_interfaces_and_lldp(self):
        version = """Hostname: edge-junos
Model: ex4300-48p
Junos: 21.4R3-S5.4
System Serial Number: AB1234
"""
        device = self.normalizer.parse_device_info("dev-junos", version)
        self.assertEqual((device.hostname, device.model, device.version), ("edge-junos", "ex4300-48p", "21.4R3-S5.4"))

        detail = """Physical interface: ge-0/0/0, Enabled, Physical link is Up
  Description: core uplink
  Link-level type: Ethernet, MTU: 1514, Speed: 1Gbps
  Current address: 00:11:22:33:44:55
"""
        terse = """Interface               Admin Link Proto    Local
ge-0/0/0               up    up
ge-0/0/0.0             up    up   inet     10.0.0.1/24
ge-0/0/0.1             up    up   eth-switch
"""
        interfaces = {item.name_display: item for item in self.normalizer.parse_interfaces("dev-junos", detail, terse)}
        self.assertEqual(interfaces["ge-0/0/0"].description, "core uplink")
        self.assertEqual(interfaces["ge-0/0/0"].speed, 1_000_000_000)
        self.assertEqual(interfaces["ge-0/0/0.0"].primary_ip, "10.0.0.1")
        self.assertFalse(interfaces["ge-0/0/0.1"].is_l3)

        lldp = """LLDP Neighbor Information:
Local Interface: ge-0/0/0
Chassis ID: aa:bb:cc:dd:ee:ff
Port ID: Ethernet1
System name: spine-01
System Capabilities: Bridge, Router
"""
        neighbors = self.normalizer.parse_neighbors("dev-junos", lldp)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].remote_device, "spine-01")
        self.assertEqual(neighbors[0].remote_interface, "eth1")


class AristaNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = AristaNormalizer()

    def test_device_interfaces_and_lldp(self):
        version = """leaf-01#show version
Arista DCS-7050SX3-48YC8
Hardware version: 12.05
Serial number: JPE12345678
Software image version: 4.29.2F
Uptime: 10 weeks, 2 days
"""
        device = self.normalizer.parse_device_info("dev-eos", version)
        self.assertEqual((device.hostname, device.model, device.version), ("leaf-01", "DCS-7050SX3-48YC8", "4.29.2F"))

        detail = """Ethernet1 is up, line protocol is up (connected)
  Description: spine uplink
  Hardware is Ethernet, address is 001c.73aa.bbcc
  MTU 9214 bytes, BW 100000000 kbit
  Full-duplex, 100Gb/s
"""
        brief = """Interface  IP Address       Status Protocol MTU
Ethernet1  unassigned       up     up       9214
Management1 10.10.10.2/24   up     up       1500
"""
        interfaces = {item.name_display: item for item in self.normalizer.parse_interfaces("dev-eos", detail, brief)}
        self.assertEqual(interfaces["eth1"].description, "spine uplink")
        self.assertEqual(interfaces["eth1"].speed, 100_000_000_000)
        self.assertEqual(interfaces["mgmt1"].primary_ip, "10.10.10.2")

        lldp = """Interface Ethernet1 detected 1 LLDP neighbors:
  Chassis ID: 001c.73ff.0001
  Port ID: Ethernet49/1
  System Name: spine-01
"""
        neighbors = self.normalizer.parse_neighbors("dev-eos", lldp)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].local_interface, "eth1")
        self.assertEqual(neighbors[0].remote_interface, "eth49/1")


class RuijieNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = RuijieNormalizer()

    def test_real_fixtures_and_lldp(self):
        version = (FIXTURES / "ruijie" / "ruijie_rgos" / "show_version" / "rgos_eg1000s.txt").read_text(
            encoding="utf-8"
        )
        device = self.normalizer.parse_device_info("dev-ruijie", version)
        self.assertEqual(device.hostname, "Ruijie")
        self.assertEqual(device.model, "EG1000S")
        self.assertIn("RGOS 10.3", device.version)

        brief = (
            FIXTURES / "ruijie" / "ruijie_rgos" / "show_ip_interface_brief" / "rgos_rsr.txt"
        ).read_text(encoding="utf-8")
        interfaces = {item.name_display: item for item in self.normalizer.parse_interfaces("dev-ruijie", "", brief)}
        self.assertEqual(interfaces["async1"].primary_ip, "10.10.0.2")
        self.assertEqual(interfaces["async1"].oper_status, "up")

        lldp = """Local Intf: GigabitEthernet 0/1
Chassis ID: 001a.a900.0001
Port ID: GigabitEthernet 0/24
System Name: access-02
"""
        neighbors = self.normalizer.parse_neighbors("dev-ruijie", lldp)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].local_interface, "gi0/1")
        self.assertEqual(neighbors[0].remote_interface, "gi0/24")


class RaisecomNormalizerTests(unittest.TestCase):
    def test_s5600_ros_version_output(self):
        raw = """Raisecom Operating System Software
Copyright (c) 2006-2021 Raisecom Science & Technology Development Co.,Ltd

Product Name: ISCOM S5600-28C-EI
Hardware Version: A.00
Software Version: 3.60.317(Compiled Apr 28 2020 12:42:15)
ROS Version: ROS_5.2.1_20200428
REAP Version:3.0
Bootrom Version: 1.4.9

System MAC Address:
Protocol MAC Address:
Serial number:
"""
        device = RaisecomNormalizer().parse_device_info("dev-raisecom", raw)
        self.assertEqual(device.vendor, "Raisecom")
        self.assertEqual(device.platform, "raisecom_ros")
        self.assertEqual(device.model, "ISCOM S5600-28C-EI")
        self.assertEqual(device.version, "3.60.317")
        self.assertEqual(device.hostname, "dev-raisecom")


if __name__ == "__main__":
    unittest.main()
