from pathlib import Path

import services.ip_locator_service as ip_locator_service


DEVICE = {
    "id": "device-1",
    "hostname": "sw-01",
    "ip_address": "192.0.2.10",
}


def test_normalize_arp_record_accepts_textfsm_standard_fields():
    record = ip_locator_service._normalize_arp_record(
        {
            "IP_ADDRESS": "10.1.1.1",
            "MAC_ADDRESS": "02e0-f102-0023",
            "INTERFACE": "GE1/0/1",
        },
        DEVICE,
    )

    assert record == {
        "ip": "10.1.1.1",
        "mac": "02e0f1020023",
        "interface": "GE1/0/1",
        "source_device_id": "device-1",
        "source_device": "sw-01",
    }


def test_arp_output_fallback_accepts_common_cisco_and_huawei_mac_formats():
    output = """
Internet 10.1.1.2 0 aabb.ccdd.eeff ARPA GigabitEthernet1/0/2
10.1.1.3 00e0-fc41-0200  D  GE1/0/3
"""

    records = ip_locator_service._parse_arp_output_fallback(output, DEVICE)

    assert [(item["ip"], item["mac"], item["interface"]) for item in records] == [
        ("10.1.1.2", "aabbccddeeff", "GigabitEthernet1/0/2"),
        ("10.1.1.3", "00e0fc410200", "GE1/0/3"),
    ]


def test_full_arp_collection_uses_normalized_records_and_raw_fallback(monkeypatch):
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": True,
                    "commands": ["show arp"],
                    "parser": "ntc-templates",
                    "records": [
                        {
                            "IP_ADDRESS": "10.1.1.10",
                            "MAC_ADDRESS": "aabb.ccdd.0010",
                            "INTERFACE": "Gi1/0/10",
                        }
                    ],
                    "raw_outputs": [],
                }
            ]
        },
    )
    parsed = ip_locator_service._collect_full_arp_from_device(DEVICE)
    assert parsed[0]["ip"] == "10.1.1.10"
    assert parsed[0]["mac"] == "aabbccdd0010"

    fixture = Path(
        "backend/tests/fixtures/cli/h3c/h3c_comware/display_arp_all/comware_v7_s5130.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(
        ip_locator_service,
        "collect_operational_data",
        lambda *_args, **_kwargs: {
            "categories": [
                {
                    "key": "arp",
                    "success": True,
                    "commands": ["display arp all"],
                    "parser": "ntc-templates",
                    "records": [],
                    "raw_outputs": [{"output": fixture}],
                }
            ]
        },
    )
    assert len(ip_locator_service._collect_full_arp_from_device(DEVICE)) == 2
