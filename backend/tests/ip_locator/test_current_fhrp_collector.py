from __future__ import annotations

from database import get_db_connection
from services import ipam_current_fhrp_collection_service as collector
from services.ipam_current_fhrp_observation_service import (
    get_current_fhrp_collection_states,
    list_current_fhrp_observations,
)


HSRP_COMPLETE = """\
Interface Grp Prio P State Active addr Standby addr Group addr
Vlan10    1   100  P Active local       192.0.2.2    192.0.2.254
"""
HSRP_PARTIAL = """\
Interface Grp Prio P State Active addr Standby addr Group addr
Vlan10    1   100  P Active local       192.0.2.2
"""
VRRP_COMPLETE = """\
Interface Grp A-F  Pri Time Own Pre State  Master addr Group addr
Vlan10    1   IPv4 100 3609 N   Y   Master 192.0.2.1  192.0.2.254
"""
H3C_VRRP_IPV4 = """\
IPv4 Virtual Router Information:
  Running Mode : Standard
  Total number of virtual routers : 1
  Interface Vlan-interface10
    VRID : 10                      Adver Timer : 100
    Admin Status : Up              State : Master
    Config Pri : 120               Running Pri : 120
    Virtual IP : 192.0.2.254
    Virtual MAC : 0000-5e00-0101
    Master IP : 192.0.2.1
"""
H3C_VRRP_IPV6_EMPTY = """\
IPv6 Virtual Router Information:
  Running Mode : Standard
  Total number of virtual routers : 0
"""


def _seed_device(device_id: str, *, platform: str = "cisco_ios", vendor: str = "cisco") -> None:
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('tenant-default', 'Default') ON CONFLICT(id) DO NOTHING"
        )
        conn.execute(
            """INSERT INTO sites (id, site_code, site_name, tenant_id)
                 VALUES (?, ?, ?, 'tenant-default') ON CONFLICT(id) DO NOTHING""",
            (f"site-{device_id}", device_id.upper(), f"Site {device_id}"),
        )
        conn.execute(
            """INSERT INTO devices (id, hostname, ip_address, vendor, platform, status, site_id, tenant_id)
                 VALUES (?, ?, '192.0.2.10', ?, ?, 'online', ?, 'tenant-default')""",
            (device_id, device_id, vendor, platform, f"site-{device_id}"),
        )
        conn.commit()


def _seed_credentials(monkeypatch) -> None:
    monkeypatch.setattr(
        collector.vault_service,
        "resolve_collector_credentials",
        lambda _device: {
            "ssh": {
                "username": "test-user",
                "password": "test-password",
                "enable_password": "",
                "port": 22,
            },
        },
    )


def _read_current(device_id: str):
    with get_db_connection() as conn:
        rows = list_current_fhrp_observations(conn, device_id=device_id)
        states = get_current_fhrp_collection_states(conn, device_id=device_id)
    return rows, {row["protocol"]: row for row in states}


def test_fhrp_ssh_banner_and_algorithm_errors_are_classified_without_raw_details():
    assert collector._classify_collection_error(
        RuntimeError("Error reading SSH protocol banner [WinError 10054] Connection reset by peer")
    ) == ("failed", "ssh_banner_unavailable")
    assert collector._classify_collection_error(
        RuntimeError("No matching key exchange method found")
    ) == ("failed", "ssh_algorithm_mismatch")


def test_current_fhrp_collects_only_supported_cli_protocols_without_device_io(isolated_db, monkeypatch):
    del isolated_db
    device_id = "current-fhrp-cisco-device"
    _seed_device(device_id)
    _seed_credentials(monkeypatch)
    calls: list[tuple[str, ...]] = []

    def fake_outputs(_device, _credentials, protocols):
        calls.append(protocols)
        return {
            "hsrp": (HSRP_COMPLETE, ""),
            "vrrp": (VRRP_COMPLETE, ""),
        }

    monkeypatch.setattr(collector, "_collect_protocol_outputs", fake_outputs)
    result = collector.run_current_fhrp_collection(device_ids={device_id})

    rows, states = _read_current(device_id)
    assert result["status"] == "success"
    assert calls == [("hsrp", "vrrp")]
    assert {(row["protocol"], row["virtual_ip_key"]) for row in rows} == {
        ("hsrp", "192.0.2.254"),
        ("vrrp", "192.0.2.254"),
    }
    assert {protocol: state["latest_status"] for protocol, state in states.items()} == {
        "hsrp": "complete",
        "vrrp": "complete",
    }
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ip_addresses").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ipam_vips").fetchone()[0] == 0


def test_partial_fhrp_attempt_preserves_last_success_and_complete_empty_is_local(
    isolated_db, monkeypatch,
):
    del isolated_db
    device_id = "current-fhrp-preserve-device"
    _seed_device(device_id)
    _seed_credentials(monkeypatch)
    outputs = {"hsrp": (HSRP_COMPLETE, ""), "vrrp": (VRRP_COMPLETE, "")}
    monkeypatch.setattr(collector, "_collect_protocol_outputs", lambda *_args: outputs)
    collector.run_current_fhrp_collection(device_ids={device_id})

    outputs.update({"hsrp": (HSRP_PARTIAL, ""), "vrrp": ("Interface Grp A-F Pri Time Own Pre State Master addr Group addr\n", "")})
    result = collector.run_current_fhrp_collection(device_ids={device_id})

    rows, states = _read_current(device_id)
    assert result["status"] == "partial"
    assert [(row["protocol"], row["virtual_ip_key"]) for row in rows] == [("hsrp", "192.0.2.254")]
    assert states["hsrp"]["latest_status"] == "partial"
    assert states["hsrp"]["last_success_generation"] == 1
    assert states["vrrp"]["latest_status"] == "complete"
    assert states["vrrp"]["current_row_count"] == 0


def test_h3c_vrrp_collects_ipv4_and_ipv6_as_one_complete_protocol_snapshot(isolated_db, monkeypatch):
    del isolated_db
    device_id = "current-fhrp-h3c-vrrp-device"
    _seed_device(device_id, platform="h3c_comware", vendor="h3c")
    _seed_credentials(monkeypatch)
    calls: list[tuple[str, ...]] = []

    def fake_outputs(_device, _credentials, protocols):
        calls.append(protocols)
        return {
            "vrrp": (
                [
                    ("display vrrp verbose", H3C_VRRP_IPV4),
                    ("display vrrp ipv6 verbose", H3C_VRRP_IPV6_EMPTY),
                ],
                "",
            ),
        }

    monkeypatch.setattr(collector, "_collect_protocol_outputs", fake_outputs)
    result = collector.run_current_fhrp_collection(device_ids={device_id})

    rows, states = _read_current(device_id)
    assert result["status"] == "success"
    assert calls == [("vrrp",)]
    assert [(row["protocol"], row["address_family"], row["virtual_ip_key"]) for row in rows] == [
        ("vrrp", 4, "192.0.2.254"),
    ]
    assert states["vrrp"]["latest_status"] == "complete"
    assert states["vrrp"]["last_success_generation"] == 1


def test_h3c_family_specific_not_configured_output_persists_verified_empty_vrrp(isolated_db, monkeypatch):
    del isolated_db
    device_id = "current-fhrp-h3c-empty-device"
    _seed_device(device_id, platform="h3c_comware", vendor="h3c")
    _seed_credentials(monkeypatch)
    monkeypatch.setattr(
        collector,
        "_collect_protocol_outputs",
        lambda *_args: {
            "vrrp": (
                [
                    ("display vrrp verbose", "VRRP4 is not configured.\n"),
                    ("display vrrp ipv6 verbose", "VRRP6 is not configured.\n"),
                ],
                "",
            ),
        },
    )

    result = collector.run_current_fhrp_collection(device_ids={device_id})

    rows, states = _read_current(device_id)
    assert result["status"] == "success"
    assert rows == []
    assert states["vrrp"]["latest_status"] == "complete"
    assert states["vrrp"]["current_row_count"] == 0
    assert states["vrrp"]["last_success_generation"] == 1


def test_h3c_incomplete_address_family_preserves_last_complete_vrrp_snapshot(isolated_db, monkeypatch):
    del isolated_db
    device_id = "current-fhrp-h3c-preserve-device"
    _seed_device(device_id, platform="h3c_comware", vendor="h3c")
    _seed_credentials(monkeypatch)
    outputs = {
        "vrrp": (
            [
                ("display vrrp verbose", H3C_VRRP_IPV4),
                ("display vrrp ipv6 verbose", H3C_VRRP_IPV6_EMPTY),
            ],
            "",
        ),
    }
    monkeypatch.setattr(collector, "_collect_protocol_outputs", lambda *_args: outputs)
    collector.run_current_fhrp_collection(device_ids={device_id})

    outputs["vrrp"] = (
        [
            ("display vrrp verbose", H3C_VRRP_IPV4),
            ("display vrrp ipv6 verbose", "IPv6 Virtual Router Information:\n"),
        ],
        "",
    )
    result = collector.run_current_fhrp_collection(device_ids={device_id})

    rows, states = _read_current(device_id)
    assert result["status"] == "partial"
    assert [(row["address_family"], row["virtual_ip_key"]) for row in rows] == [
        (4, "192.0.2.254"),
    ]
    assert states["vrrp"]["latest_status"] == "partial"
    assert states["vrrp"]["last_success_generation"] == 1


def test_unsupported_platform_is_not_sent_device_commands(isolated_db, monkeypatch):
    del isolated_db
    device_id = "current-fhrp-linux-device"
    _seed_device(device_id, platform="linux", vendor="linux")
    monkeypatch.setattr(
        collector.vault_service,
        "resolve_collector_credentials",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unsupported device must not resolve CLI credentials")),
    )
    monkeypatch.setattr(
        collector,
        "_collect_protocol_outputs",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unsupported device must not open a session")),
    )

    result = collector.run_current_fhrp_collection(device_ids={device_id})
    rows, states = _read_current(device_id)

    assert result["device_results"][0]["status"] == "unsupported"
    assert rows == []
    assert {protocol: state["latest_status"] for protocol, state in states.items()} == {
        "hsrp": "unsupported",
        "vrrp": "unsupported",
    }
