from __future__ import annotations

import inspect

import pytest

from services import cmdb_cli_collection_service, interface_collection_service


def _device() -> dict:
    return {
        "id": "cmdb-cli-device",
        "hostname": "cmdb-cli-device",
        "ip_address": "192.0.2.19",
        "vendor": "h3c",
        "platform": "h3c_comware",
        "status": "online",
        "tenant_id": "tenant-default",
        "collection_policy_json": "{}",
    }


def _attempt(device_id: str, domain: str) -> dict:
    return {
        "device_id": device_id,
        "domain": domain,
        "generation": 1,
        "run_id": f"test-{domain}",
        "started_at": "2026-10-27T10:00:00+00:00",
    }


class _FakeActionSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _FakeNetworkLease:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return None


class _FakeNetworkLimiter:
    def ssh(self, _device, *, operation):
        assert operation == "cmdb_cli_inventory"
        return _FakeNetworkLease()


def _install_common(monkeypatch, *, interface: bool, vlan: bool) -> list[dict]:
    attempts: list[dict] = []
    monkeypatch.setattr(interface_collection_service, "_load_device", lambda _device_id: _device())
    monkeypatch.setattr(
        interface_collection_service,
        "_load_ip_inventory",
        lambda *_args, **_kwargs: pytest.fail("CMDB CLI snapshots must not read shared IP inventory"),
    )
    monkeypatch.setattr(
        "services.collection_plan_service.should_collect",
        lambda _device, category: (interface and category == "interface_status")
        or (vlan and category == "vlan"),
    )
    monkeypatch.setattr(
        "services.cmdb_snapshot_service.begin_snapshot_attempt",
        lambda device_id, domain: attempts.append(_attempt(device_id, domain)) or attempts[-1],
    )
    monkeypatch.setattr(
        "services.cmdb_snapshot_service.fail_snapshot_attempt",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.PlatformActionSession",
        lambda *_args, **_kwargs: _FakeActionSession(),
    )
    monkeypatch.setattr(
        "services.network_access_limiter.get_network_access_limiter",
        lambda: _FakeNetworkLimiter(),
    )
    monkeypatch.setattr(
        interface_collection_service,
        "_collect_snmp_interface_domains",
        lambda **_kwargs: pytest.fail("CMDB CLI collector must not invoke the SNMP collector"),
    )
    return attempts


def test_cmdb_vlan_job_uses_cli_projection_without_snmp(monkeypatch):
    attempts = _install_common(monkeypatch, interface=False, vlan=True)
    requested: list[str] = []
    persisted: list[dict] = []

    def collect(_device, *, categories, auth_role, _platform_action_session):
        requested.extend(categories)
        assert auth_role == "auto"
        assert isinstance(_platform_action_session, _FakeActionSession)
        return {
            "categories": [{
                "key": "vlan",
                "success": True,
                "parse_status": "matched",
                "records": [{"VLAN_ID": "219", "VLAN_NAME": "APP-219"}],
                "commands": ["display vlan brief"],
            }],
        }

    monkeypatch.setattr("services.read_only_collection_adapter.collect_read_only_evidence", collect)
    monkeypatch.setattr(
        cmdb_cli_collection_service,
        "_persist_vlan_snapshot",
        lambda device_id, records, attempt, **kwargs: persisted.append({
            "device_id": device_id, "records": records, "attempt": attempt, **kwargs,
        }) or {
            "vlans": 1, "interfaces": 0,
        },
    )

    result = cmdb_cli_collection_service.collect_cmdb_interface_status_target("cmdb-cli-device")

    assert requested == ["vlan"]
    assert persisted[0]["device_id"] == "cmdb-cli-device"
    assert persisted[0]["records"] == [{"VLAN_ID": "219", "VLAN_NAME": "APP-219"}]
    assert persisted[0]["attempt"] is attempts[0]
    assert persisted[0]["metadata"]["action_code"] == "get_vlan_table"
    assert result["transport_policy"] == "cmdb_cli_only"
    assert result["domains"]["vlans"]["vlans"] == 1
    assert attempts[0]["domain"] == "vlan_inventory"


def test_cmdb_interface_job_can_reuse_the_same_cli_flow_for_vlan_only(monkeypatch):
    attempts = _install_common(monkeypatch, interface=True, vlan=True)
    requested: list[str] = []

    def collect(_device, *, categories, auth_role, _platform_action_session):
        requested.extend(categories)
        return {
            "categories": [{
                "key": "vlan",
                "success": True,
                "parse_status": "matched",
                "records": [{"VLAN_ID": "219", "VLAN_NAME": "APP-219"}],
            }],
        }

    monkeypatch.setattr("services.read_only_collection_adapter.collect_read_only_evidence", collect)
    monkeypatch.setattr(
        cmdb_cli_collection_service,
        "_persist_vlan_snapshot",
        lambda *_args, **_kwargs: {"vlans": 1, "interfaces": 0},
    )

    result = cmdb_cli_collection_service.collect_cmdb_interface_status_target(
        "cmdb-cli-device", vlan_only=True,
    )

    assert requested == ["vlan"]
    assert attempts[0]["domain"] == "vlan_inventory"
    assert result["domains"]["vlans"] == {"vlans": 1, "interfaces": 0}


def test_interface_inventory_uses_cmdb_cli_snapshot_for_vlan(monkeypatch):
    device = _device()
    calls: dict = {}
    monkeypatch.setattr(interface_collection_service, "_load_device", lambda _device_id: device)
    monkeypatch.setattr(interface_collection_service, "_load_ip_inventory", lambda _device_id: {})
    monkeypatch.setattr(
        "services.collection_plan_service.should_collect",
        lambda _device, category: category in {"interface_status", "vlan"},
    )

    def collect_snmp(_device, *, collect_interfaces, collect_vlans):
        calls["snmp"] = {"interfaces": collect_interfaces, "vlans": collect_vlans}
        return {
            "interfaces": [{"name": "GigabitEthernet1/0/1", "status": "up", "admin_status": "up"}],
            "addresses": [],
            "complete": {
                "interface_status": True,
                "interface_description": True,
                "interface_mac": True,
                "interface_mtu": True,
                "interface_addresses": True,
                "vlan": False,
            },
            "persisted": {},
            "errors": {},
            "version": "2c",
        }

    monkeypatch.setattr(interface_collection_service, "_collect_snmp_interface_domains", collect_snmp)
    monkeypatch.setattr(interface_collection_service, "_upsert_snmp_interfaces", lambda *_args: 1)
    monkeypatch.setattr(interface_collection_service, "_build_interface_status_rows", lambda *_args, **_kwargs: ({}, []))
    monkeypatch.setattr(interface_collection_service, "_upsert_interfaces", lambda *_args: 0)
    monkeypatch.setattr(interface_collection_service, "_description_records", lambda *_args: {})
    monkeypatch.setattr("services.vlan_discovery_service.sync_observed_vlans", lambda: {"observed": 0, "created": 0, "updated": 0})
    monkeypatch.setattr("services.collection_status_service.record_collection_result", lambda *_args, **_kwargs: None)

    def collect_cli_vlan(device_id, *, vlan_only=False):
        calls["cli"] = {"device_id": device_id, "vlan_only": vlan_only}
        return {"success": True, "domains": {"vlans": {"vlans": 3, "interfaces": 12}}}

    monkeypatch.setattr(
        "services.cmdb_cli_collection_service.collect_cmdb_interface_status_target",
        collect_cli_vlan,
    )

    result = interface_collection_service._collect_interface_status_target(device["id"])

    assert calls["snmp"] == {"interfaces": True, "vlans": False}
    assert calls["cli"] == {"device_id": device["id"], "vlan_only": True}
    assert result["vlan_projection"] == {"vlans": 3, "interfaces": 12}
    assert result["snmp_domains"]["requested"]["vlans"] is False
    assert result["vlan_transport"] == "ssh"


@pytest.mark.parametrize("fail_evidence", [False, True])
def test_cmdb_session_acquires_device_ssh_gate_once_and_releases_it(monkeypatch, fail_evidence):
    from drivers.base import BaseDriver
    from services.network_access_limiter import NetworkAccessLimiter

    _install_common(monkeypatch, interface=False, vlan=True)
    limiter = NetworkAccessLimiter(
        ssh_global_limit=1, ssh_per_device_limit=1,
        acquire_timeout=0, ssh_lease_factory=None,
    )
    monkeypatch.setattr(
        "services.network_access_limiter.get_network_access_limiter", lambda: limiter,
    )
    events = []

    class Driver(BaseDriver):
        def connect(self):
            assert limiter.snapshot()["active_cmdb_ssh"] == 1
            assert limiter.snapshot()["active_ssh"] == 0
            events.append("connect")

        def disconnect(self):
            events.append("disconnect")

        def send_command(self, command):
            raise AssertionError("No real device command is used in this regression")

        def send_config(self, configs):
            raise AssertionError("Configuration is outside CMDB collection")

    class Session:
        def __enter__(self):
            self.driver = Driver({**_device(), "_ssh_capacity_class": "cmdb_cli"})
            self.driver.__enter__()
            return self

        def __exit__(self, *args):
            return self.driver.__exit__(*args)

    def session_factory(*args, **kwargs):
        assert kwargs["ssh_capacity_class"] == "cmdb_cli"
        return Session()

    monkeypatch.setattr("services.platform_registry_service.PlatformActionSession", session_factory)

    def evidence(*args, **kwargs):
        assert limiter.snapshot()["active_cmdb_ssh"] == 1
        assert limiter.snapshot()["active_ssh"] == 0
        if fail_evidence:
            raise RuntimeError("simulated evidence failure")
        return {"categories": [{
            "key": "vlan", "success": True, "parse_status": "matched",
            "records": [{"VLAN_ID": "219", "VLAN_NAME": "APP-219"}],
        }]}

    monkeypatch.setattr("services.read_only_collection_adapter.collect_read_only_evidence", evidence)
    monkeypatch.setattr(
        cmdb_cli_collection_service, "_persist_vlan_snapshot",
        lambda *args, **kwargs: {"vlans": 1, "interfaces": 0},
    )
    for _ in range(2):
        if fail_evidence:
            with pytest.raises(RuntimeError, match="simulated evidence failure"):
                cmdb_cli_collection_service.collect_cmdb_interface_status_target("cmdb-cli-device")
        else:
            assert cmdb_cli_collection_service.collect_cmdb_interface_status_target("cmdb-cli-device")["success"]
        assert limiter.snapshot()["active_ssh"] == 0
        assert limiter.snapshot()["active_cmdb_ssh"] == 0
    assert events == ["connect", "disconnect", "connect", "disconnect"]


def test_cmdb_vlan_job_rejects_unmatched_parser_result(monkeypatch):
    attempts = _install_common(monkeypatch, interface=False, vlan=True)
    persisted = False
    failed: list[dict] = []

    def fail(attempt, **_kwargs):
        failed.append(attempt)

    monkeypatch.setattr("services.cmdb_snapshot_service.fail_snapshot_attempt", fail)
    monkeypatch.setattr(
        "services.read_only_collection_adapter.collect_read_only_evidence",
        lambda *_args, **_kwargs: {
            "categories": [{"key": "vlan", "success": True, "parse_status": "unmatched", "records": []}],
        },
    )

    def persist(*_args, **_kwargs):
        nonlocal persisted
        persisted = True

    monkeypatch.setattr(cmdb_cli_collection_service, "_persist_vlan_snapshot", persist)

    with pytest.raises(RuntimeError, match="get_vlan_table"):
        cmdb_cli_collection_service.collect_cmdb_interface_status_target("cmdb-cli-device")

    assert attempts[0]["domain"] == "vlan_inventory"
    assert failed
    assert not persisted


@pytest.mark.parametrize(
    ("description_category", "expected_unsupported"),
    [
        ({"key": "interface_description", "success": True, "parse_status": "matched", "records": []}, []),
        ({
            "key": "interface_description",
            "success": False,
            "parse_status": "unsupported_by_platform",
            "error_code": "UNSUPPORTED_ACTION",
            "records": [],
        }, ["interface_description"]),
    ],
)
def test_cmdb_interface_job_uses_one_cli_session_and_commits_snapshot(
    monkeypatch, description_category, expected_unsupported,
):
    attempts = _install_common(monkeypatch, interface=True, vlan=False)
    monkeypatch.setattr(
        "services.collection_plan_service.should_collect",
        lambda _device, category: category in {"interface_status", "prefix_projection"},
    )
    monkeypatch.setattr(
        "services.prefix_discovery_service.discover_prefixes_from_interface_snapshot",
        lambda *_args, **_kwargs: pytest.fail(
            "isolated CMDB interface observations must not project shared prefixes"
        ),
    )
    captured: dict = {}

    def collect(_device, *, categories, auth_role, _platform_action_session):
        assert categories == ["interfaces", "interface_description"]
        assert auth_role == "auto"
        captured["session"] = _platform_action_session
        return {
            "categories": [
                {
                    "key": "interfaces",
                    "success": True,
                    "parse_status": "matched",
                    "parser": "textfsm",
                    "records": [{"INTERFACE": "Vlan-interface219", "STATUS": "up"}],
                },
                description_category,
            ],
        }

    monkeypatch.setattr("services.read_only_collection_adapter.collect_read_only_evidence", collect)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda _device_id, _action, **kwargs: (
            pytest.fail("IP CLI action must share the read-only CLI session")
            if kwargs.get("_session") is not captured["session"]
            else {
                "success": True,
                "parse_status": "matched",
                "release_number": "test-release",
                "records": [{
                    "INTERFACE": "Vlan-interface219",
                    "IP_ADDRESS": "10.219.0.1",
                    "PREFIX_LENGTH": "24",
                }],
            }
        ),
    )
    monkeypatch.setattr(
        cmdb_cli_collection_service,
        "_persist_interface_snapshot",
        lambda device, rows, attempt, **kwargs: captured.update({
            "device": device, "rows": rows, "attempt": attempt, **kwargs,
        }) or 1,
    )
    monkeypatch.setattr(
        "services.collection_status_service.record_collection_result",
        lambda *_args, **_kwargs: pytest.fail("CMDB CLI collection must not write monitoring status"),
    )

    result = cmdb_cli_collection_service.collect_cmdb_interface_status_target("cmdb-cli-device")

    assert result["transport_policy"] == "cmdb_cli_only"
    assert result["domains"]["interfaces"]["record_count"] == 1
    assert captured["attempt"] == attempts[0]
    assert captured["metadata"]["action_code"] == "get_ip_interfaces"
    assert result["domains"]["interfaces"]["unsupported_fields"] == expected_unsupported
    assert result["prefix_sync"] == {
        "ok": True,
        "skipped": True,
        "reason": "cmdb_projection_isolated",
    }
    assert captured["metadata"]["unsupported_fields"] == expected_unsupported
    assert captured["rows"] == [{
        "interface_name": "Vlan-interface219",
        "description": None,
        "interface_ip": "10.219.0.1",
        "prefix_length": 24,
        "admin_status": "up",
        "oper_status": "up",
    }]


def test_cmdb_ip_action_rejects_ambiguous_or_unparsed_data(monkeypatch):
    session = _FakeActionSession()
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "parse_status": "matched",
            "records": [{"INTERFACE": "Vlan-interface219", "IP_ADDRESS": "10.219.0.1/24"}],
        },
    )
    addresses, metadata = cmdb_cli_collection_service._collect_cli_ip_addresses(_device(), session)
    assert addresses == [{
        "interface": "Vlan-interface219", "ip_address": "10.219.0.1", "prefix_length": 24,
    }]
    assert metadata == {}

    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "parse_status": "matched",
            "records": [
                {"INTERFACE": "Vlan-interface219", "IP_ADDRESS": "10.219.0.1/24"},
                {"INTERFACE": "Vlan-interface219", "IP_ADDRESS": "10.219.0.2/24"},
            ],
        },
    )
    with pytest.raises(RuntimeError, match="多个地址"):
        cmdb_cli_collection_service._collect_cli_ip_addresses(_device(), session)

    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {"success": True, "parse_status": "unmatched", "records": []},
    )
    with pytest.raises(RuntimeError, match="接口IP CLI采集不完整"):
        cmdb_cli_collection_service._collect_cli_ip_addresses(_device(), session)


def test_cmdb_ip_action_explains_prefixless_brief_output(monkeypatch):
    raw_output = """Interface Physical Protocol IP Address Description
Vlan-interface1 up up 192.0.2.1 gateway
"""
    monkeypatch.setattr(
        cmdb_cli_collection_service,
        "_collect_cli_ip_action_result",
        lambda *_args: {
            "success": True,
            "parse_status": "unmatched",
            "raw_output": raw_output,
            "records": [],
        },
    )

    with pytest.raises(RuntimeError, match="没有掩码或前缀长度"):
        cmdb_cli_collection_service._collect_cli_ip_addresses(_device(), _FakeActionSession())


def test_prefixless_ip_brief_uses_published_detailed_action_for_matching_cidr(monkeypatch):
    from services import operational_data_service

    device = _device()
    session = _FakeActionSession()
    raw_brief = """Interface Physical Protocol IP Address Description
Vlan-interface1 up up 192.0.2.1 gateway
"""
    calls = []

    def execute(device_id, action_code, **kwargs):
        calls.append((device_id, action_code, kwargs.get("_session")))
        if action_code == "get_ip_interfaces":
            return {
                "success": True,
                "parse_status": "unmatched",
                "records": [],
                "command": "display ip interface brief",
                "raw_output": raw_brief,
            }
        assert action_code == "get_interfaces"
        return {
            "success": True,
            "parse_status": "matched",
            "records": [{"INTERFACE": "Vlan-interface1", "IP_ADDRESS": "192.0.2.1/24"}],
            "command": "display interface",
            "parser": "textfsm:h3c_comware_v7_display_interface.textfsm",
            "parser_platform": "h3c_comware_v7",
            "template": "h3c_comware_v7_display_interface.textfsm",
            "template_source": "custom",
            "raw_output": "sanitized detailed output",
        }

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", execute)
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        operational_data_service,
        "resolve_textfsm_template_for_command",
        lambda *_args, **_kwargs: {
            "textfsm_template": "h3c_comware_v7_display_ip_interface_brief.textfsm",
        },
    )
    monkeypatch.setattr(
        operational_data_service,
        "parse_device_cli_output",
        lambda *_args, **_kwargs: {"parse_status": "unmatched", "records": []},
    )

    addresses, metadata = cmdb_cli_collection_service._collect_cli_ip_addresses(device, session)

    assert calls == [
        (device["id"], "get_ip_interfaces", session),
        (device["id"], "get_interfaces", session),
    ]
    assert addresses == [{
        "interface": "Vlan-interface1",
        "ip_address": "192.0.2.1",
        "prefix_length": 24,
    }]
    assert metadata["source_action_code"] == "get_interfaces"
    assert metadata["ip_action_command"] == "display ip interface brief"


def test_prefixless_ip_brief_rejects_detailed_action_address_mismatch(monkeypatch):
    from services import operational_data_service

    device = _device()
    session = _FakeActionSession()
    raw_brief = """Interface Physical Protocol IP Address Description
Vlan-interface1 up up 192.0.2.1 gateway
"""

    def execute(_device_id, action_code, **_kwargs):
        if action_code == "get_ip_interfaces":
            return {
                "success": True,
                "parse_status": "unmatched",
                "records": [],
                "command": "display ip interface brief",
                "raw_output": raw_brief,
            }
        return {
            "success": True,
            "parse_status": "matched",
            "records": [{"INTERFACE": "Vlan-interface1", "IP_ADDRESS": "192.0.2.2/24"}],
            "command": "display interface",
            "raw_output": "sanitized detailed output",
        }

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", execute)
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        operational_data_service,
        "resolve_textfsm_template_for_command",
        lambda *_args, **_kwargs: {
            "textfsm_template": "h3c_comware_v7_display_ip_interface_brief.textfsm",
        },
    )
    monkeypatch.setattr(
        operational_data_service,
        "parse_device_cli_output",
        lambda *_args, **_kwargs: {"parse_status": "unmatched", "records": []},
    )

    with pytest.raises(RuntimeError, match="get_interfaces IP rows did not exactly match"):
        cmdb_cli_collection_service._collect_cli_ip_addresses(device, session)


def test_cmdb_ip_action_accepts_h3c_ragg_aggregate_interface(monkeypatch):
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        cmdb_cli_collection_service,
        "_collect_cli_ip_action_result",
        lambda *_args: {
            "success": True,
            "parse_status": "matched",
            "records": [{"INTERFACE": "RAGG34", "IP_ADDRESS": "192.0.2.1/24"}],
        },
    )

    addresses, _metadata = cmdb_cli_collection_service._collect_cli_ip_addresses(
        _device(), _FakeActionSession(),
    )

    assert addresses == [{
        "interface": "RAGG34",
        "ip_address": "192.0.2.1",
        "prefix_length": 24,
    }]


def test_cmdb_ip_action_unwraps_singleton_textfsm_list_fields(monkeypatch):
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "parse_status": "matched",
            "records": [{
                "interface": ["Vlan-interface219"],
                "ip_address": ["10.219.0.1/24"],
                "prefix_length": ["24"],
            }],
        },
    )

    addresses, _metadata = cmdb_cli_collection_service._collect_cli_ip_addresses(
        _device(), _FakeActionSession(),
    )

    assert addresses == [{
        "interface": "Vlan-interface219",
        "ip_address": "10.219.0.1",
        "prefix_length": 24,
    }]


def test_cmdb_ip_action_rejects_multiple_values_inside_a_textfsm_list(monkeypatch):
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "parse_status": "matched",
            "records": [{
                "INTERFACE": ["Vlan-interface219"],
                "IP_ADDRESS": ["10.219.0.1/24", "10.219.0.2/24"],
            }],
        },
    )

    with pytest.raises(RuntimeError, match="多个值"):
        cmdb_cli_collection_service._collect_cli_ip_addresses(
            _device(), _FakeActionSession(),
        )


def test_cmdb_ip_action_reparses_raw_output_only_with_an_exact_current_profile_template(monkeypatch):
    from services import operational_data_service

    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: {
            "success": True,
            "parse_status": "unmatched",
            "command": "show ip interface",
            "raw_output": "fixture output",
            "records": [],
        },
    )
    monkeypatch.setattr(
        operational_data_service,
        "resolve_textfsm_template_for_command",
        lambda *_args, **_kwargs: {
            "textfsm_template": "cisco_ios_show_ip_interface.textfsm",
            "textfsm_source": "common",
        },
    )
    parse_calls = []

    def parse_exact(_device, command, raw_output, *, template_filename):
        parse_calls.append((command, raw_output, template_filename))
        return {
            "parse_status": "matched",
            "records": [{
                "INTERFACE": "Vlan-interface219",
                "IP_ADDRESS": ["10.219.0.1/24"],
                "PREFIX_LENGTH": ["24"],
            }],
            "parser": f"textfsm:{template_filename}",
            "parser_platform": "cisco_ios",
            "template": template_filename,
            "template_source": "common",
        }

    monkeypatch.setattr(operational_data_service, "parse_device_cli_output", parse_exact)

    addresses, metadata = cmdb_cli_collection_service._collect_cli_ip_addresses(
        _device(), _FakeActionSession(),
    )

    assert addresses[0]["ip_address"] == "10.219.0.1"
    assert parse_calls == [(
        "show ip interface", "fixture output", "cisco_ios_show_ip_interface.textfsm",
    )]
    assert metadata["template"] == "cisco_ios_show_ip_interface.textfsm"


def test_cmdb_ip_action_uses_only_exact_textfsm_fallback_when_registry_action_is_missing(monkeypatch):
    from services import operational_data_service
    from services.platform_registry_service import PlatformRegistryError

    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)

    def missing_action(*_args, **_kwargs):
        raise PlatformRegistryError("UNSUPPORTED_ACTION", "no published action")

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", missing_action)
    fallback_plan = {
        "status": "supported",
        "commands": [{
            "command": "show ip interface",
            "command_source": "textfsm_action_metadata",
            "textfsm_template": "cisco_ios_show_ip_interface.textfsm",
            "textfsm_source": "common",
            "condition": "exact parser/action contract",
        }],
        "condition": None,
    }
    resolution_calls = []

    def resolve_fallback(device, *, operational_category, action_code):
        resolution_calls.append((device["id"], operational_category, action_code))
        return fallback_plan

    monkeypatch.setattr(operational_data_service, "resolve_textfsm_operation_fallback", resolve_fallback)
    fallback_calls = []

    def execute_fallback(device, fallback, *, user, platform_action_session):
        fallback_calls.append((device["id"], fallback["command"], user["role"], platform_action_session))
        return {
            "success": True,
            "parse_status": "matched",
            "command": fallback["command"],
            "command_source": fallback["command_source"],
            "raw_output": "fixture output",
            "records": [{
                "INTERFACE": "Vlan-interface219",
                "IP_ADDRESS": "10.219.0.1/24",
            }],
            "parser": "textfsm:cisco_ios_show_ip_interface.textfsm",
            "parser_platform": "cisco_ios",
            "template": fallback["textfsm_template"],
            "template_source": fallback["textfsm_source"],
            "fallback_condition": fallback["condition"],
        }

    monkeypatch.setattr(operational_data_service, "_execute_textfsm_operation_fallback", execute_fallback)
    session = _FakeActionSession()

    addresses, metadata = cmdb_cli_collection_service._collect_cli_ip_addresses(_device(), session)

    assert addresses[0]["prefix_length"] == 24
    assert resolution_calls == [("cmdb-cli-device", "ip_interfaces", "get_ip_interfaces")]
    assert fallback_calls == [("cmdb-cli-device", "show ip interface", "Operator", session)]
    assert metadata["command_source"] == "textfsm_action_metadata"
    assert metadata["template"] == "cisco_ios_show_ip_interface.textfsm"


def test_cmdb_ip_action_rejects_legacy_interface_brief_fallback(monkeypatch):
    from services import operational_data_service
    from services.platform_registry_service import PlatformRegistryError

    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PlatformRegistryError("UNSUPPORTED_ACTION", "no published action")
        ),
    )
    monkeypatch.setattr(
        operational_data_service,
        "resolve_textfsm_operation_fallback",
        lambda *_args, **_kwargs: {
            "status": "supported",
            "commands": [{
                "command": "show ip interface brief",
                "command_source": "legacy_catalog_textfsm",
                "textfsm_template": "cisco_ios_show_ip_interface_brief.textfsm",
                "textfsm_source": "common",
            }],
        },
    )
    monkeypatch.setattr(
        operational_data_service,
        "_execute_textfsm_operation_fallback",
        lambda *_args, **_kwargs: pytest.fail(
            "IP collection must not fall back to interface brief without a prefix contract"
        ),
    )

    with pytest.raises(RuntimeError, match="没有绑定get_ip_interfaces的精确模板"):
        cmdb_cli_collection_service._collect_cli_ip_action_result(
            _device(), _FakeActionSession(),
        )


def test_cmdb_ip_action_fails_closed_when_no_exact_template_fallback_exists(monkeypatch):
    from services.platform_registry_service import PlatformRegistryError

    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PlatformRegistryError("UNSUPPORTED_ACTION", "no published action")
        ),
    )
    monkeypatch.setattr(
        "services.operational_data_service.resolve_textfsm_operation_fallback",
        lambda *_args, **_kwargs: {
            "status": "unsupported",
            "commands": [],
            "condition": "no exact parser/version template",
        },
    )

    with pytest.raises(RuntimeError, match="no exact parser/version template"):
        cmdb_cli_collection_service._collect_cli_ip_addresses(_device(), _FakeActionSession())


def test_cmdb_ip_action_does_not_fallback_for_registry_transport_errors(monkeypatch):
    from services.platform_registry_service import PlatformRegistryError

    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    monkeypatch.setattr(
        "services.platform_registry_service.execute_platform_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PlatformRegistryError("CONNECTION_OR_COMMAND_FAILED", "query failed")
        ),
    )
    monkeypatch.setattr(
        "services.operational_data_service.resolve_textfsm_operation_fallback",
        lambda *_args, **_kwargs: pytest.fail("transport errors must not trigger a different command"),
    )

    with pytest.raises(PlatformRegistryError, match="query failed"):
        cmdb_cli_collection_service._collect_cli_ip_addresses(_device(), _FakeActionSession())


def test_interface_snapshot_writer_rolls_back_superseded_facts_and_commits_revision(isolated_db):
    from database import get_db_connection
    from services.cmdb_snapshot_service import begin_snapshot_attempt
    from services.cmdb_version_service import read_versions

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, status) VALUES (?, ?, ?, ?)",
            ("cmdb-writer-device", "cmdb-writer-device", "192.0.2.20", "online"),
        )
        conn.commit()
    finally:
        conn.close()

    device = {"id": "cmdb-writer-device"}
    rows = [{
        "interface_name": "Vlan-interface219",
        "description": "gateway",
        "interface_ip": "10.219.0.1",
        "prefix_length": 24,
        "admin_status": "up",
        "oper_status": "up",
    }]
    stale = begin_snapshot_attempt("cmdb-writer-device", "interface_inventory")
    current = begin_snapshot_attempt("cmdb-writer-device", "interface_inventory")

    with pytest.raises(RuntimeError, match="superseded"):
        cmdb_cli_collection_service._persist_interface_snapshot(
            device, rows, stale, observed_at="2026-10-27T10:00:00+00:00", metadata={},
        )

    conn = get_db_connection()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM cmdb_device_interface_observations WHERE device_id = ?",
            (device["id"],),
        ).fetchone()[0] == 0
    finally:
        conn.close()

    cmdb_cli_collection_service._persist_interface_snapshot(
        device, rows, current, observed_at="2026-10-27T10:01:00+00:00", metadata={"parser": "textfsm"},
    )

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT interface_name, ip_address, ip_prefix_length, admin_status, oper_status, "
            "interface_type, generation, run_id, metadata_json "
            "FROM cmdb_device_interface_observations WHERE device_id = ?",
            (device["id"],),
        ).fetchone()
        assert tuple(row[:7]) == (
            "Vlan-interface219", "10.219.0.1", 24, "up", "up", "svi", current["generation"],
        )
        assert row[7] == current["run_id"]
        assert '"parser":"textfsm"' in row[8]
        assert conn.execute(
            "SELECT COUNT(*) FROM interfaces WHERE device_id = ?", (device["id"],),
        ).fetchone()[0] == 0
        snapshot = conn.execute(
            "SELECT successful_generation, attempt_status, observed_at FROM cmdb_collection_snapshots "
            "WHERE device_id = ? AND domain = ?",
            (device["id"], "interface_inventory"),
        ).fetchone()
        assert tuple(snapshot) == (current["generation"], "success", "2026-10-27T10:01:00+00:00")
        assert read_versions(conn, ["interfaces"]) == {"interfaces": 1}
    finally:
        conn.close()


def test_unmatched_published_ip_action_reuses_raw_output_with_shared_template(monkeypatch):
    from pathlib import Path

    device = {**_device(), "version": "7.1.070"}
    sample = (
        Path(__file__).parents[1] / "fixtures" / "cli" / "h3c" / "h3c_comware"
        / "display_ip_interface_brief" / "comware_v7_cidr.txt"
    ).read_text(encoding="utf-8")
    session = _FakeActionSession()
    calls = []

    def execute(device_id, action_code, **kwargs):
        calls.append((device_id, action_code, kwargs.get("_session")))
        return {
            "success": True, "parse_status": "unmatched", "records": [],
            "raw_output": sample, "command": "display ip interface brief",
            "platform_release_id": "published-h3c-v7", "command_checksum": "original-checksum",
        }

    monkeypatch.setattr("services.platform_registry_service.execute_platform_action", execute)
    monkeypatch.setattr(
        "services.operational_data_service._execute_textfsm_operation_fallback",
        lambda *args, **kwargs: pytest.fail("Same-output recovery must not issue another command"),
    )
    monkeypatch.setattr(cmdb_cli_collection_service, "_action_record_limit", lambda _action: 2000)
    addresses, metadata = cmdb_cli_collection_service._collect_cli_ip_addresses(device, session)

    assert {(row["ip_address"], row["prefix_length"]) for row in addresses} == {
        ("192.0.2.1", 32), ("198.51.100.1", 30), ("203.0.113.1", 24),
    }
    assert len(addresses) == 3
    assert calls == [(device["id"], "get_ip_interfaces", session)]
    assert metadata["platform_release_id"] == "published-h3c-v7"
    assert metadata["command_checksum"] == "original-checksum"
    assert metadata["template"] == "h3c_comware_v7_display_ip_interface_brief.textfsm"
    assert metadata["template_source"] in {"custom", "packaged", "builtin"}
    assert metadata["template_action_code"] == "get_ip_interfaces"


def test_shared_interface_collection_signature_is_unchanged():
    target = inspect.signature(interface_collection_service.collect_interface_status_target)
    batch = inspect.signature(interface_collection_service.collect_interface_status_for_online_devices)
    assert tuple(target.parameters) == ("device_id", "require_online_network_device")
    assert tuple(batch.parameters) == ("target_device_ids",)


def test_job_worker_routes_only_cmdb_scoped_jobs_to_the_cmdb_service(monkeypatch):
    from services import job_worker

    cmdb_calls: list[str] = []
    legacy_calls: list[dict] = []
    monkeypatch.setattr(
        cmdb_cli_collection_service,
        "collect_cmdb_interface_status_target",
        lambda device_id: cmdb_calls.append(device_id) or {"success": True},
    )
    monkeypatch.setattr(
        interface_collection_service,
        "collect_interface_status_target",
        lambda device_id, **kwargs: legacy_calls.append({"device_id": device_id, **kwargs}) or {"success": True},
    )

    job_worker._execute_target(
        {"job_type": "interface_collection", "scope_json": '{"cmdb_cli_only": true}'},
        {"target_id": "cmdb-device"},
    )
    job_worker._execute_target(
        {"job_type": "interface_collection", "scope_json": "{}"},
        {"target_id": "legacy-device"},
    )

    assert cmdb_calls == ["cmdb-device"]
    assert legacy_calls == [{"device_id": "legacy-device", "require_online_network_device": True}]


def test_cmdb_sync_reuses_only_an_active_cmdb_cli_job():
    from api.cmdb import _find_active_cmdb_interface_job

    class _Rows:
        def execute(self, query):
            assert "scope_json" in query
            return self

        def fetchall(self):
            return [
                {"id": "legacy-active", "scope_json": "{}"},
                {"id": "cmdb-active", "scope_json": '{"cmdb_cli_only": true}'},
            ]

    active = _find_active_cmdb_interface_job(_Rows())
    assert active["id"] == "cmdb-active"


def test_read_only_evidence_adapter_forwards_shared_cli_session(monkeypatch):
    from services.read_only_collection_adapter import collect_read_only_evidence

    session = object()
    captured: dict = {}
    monkeypatch.setattr(
        "services.read_only_collection_adapter.collect_operational_data",
        lambda _device, **kwargs: captured.update(kwargs) or {
            "categories": [], "device": {}, "collected_at": "2026-10-27T10:00:00+00:00",
        },
    )

    result = collect_read_only_evidence(
        _device(), categories=["interfaces"], _platform_action_session=session,
    )

    assert captured["_platform_action_session"] is session
    assert result["contract_version"] == "read-only-evidence-v1"


def test_cached_projection_metadata_exposes_revision_cache_and_collection_time():
    from datetime import datetime, timezone

    from api.cmdb import _cmdb_projection_meta

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

    class _Connection:
        def execute(self, query, params=()):
            if "MAX(last_success_at)" in query:
                assert tuple(params) == ("interface_inventory", "tenant-a", "site-a", "site-b")
                assert "d.site_id IN" in query
                return _Result([{"domain": "interface_inventory", "last_success_at": "2026-10-27T10:00:00+00:00"}])
            assert "transaction_timestamp()" in query
            return _Result([{"snapshot_at": datetime(2026, 10, 27, 10, 1, tzinfo=timezone.utc)}])

    meta = _cmdb_projection_meta(
        _Connection(),
        {"cmdb": {"interfaces": 7}, "external_bucket": 12},
        "hit",
        ("interface_inventory",),
        tenant_id="tenant-a",
        site_ids=("site-a", "site-b"),
    )

    assert meta["inventory_revision"] == {"interfaces": 7}
    assert meta["cache_state"] == "hit"
    assert meta["last_success_at"] == {"interface_inventory": "2026-10-27T10:00:00+00:00"}
    assert meta["snapshot_at"] == "2026-10-27T10:01:00+00:00"
    assert meta["dependency_watermark"] is None


@pytest.mark.parametrize("resource", ["interfaces", "vlans", "vlan_details"])
def test_unversioned_projection_reads_current_source_without_redis(monkeypatch, resource):
    from api import cmdb as cmdb_api

    def reject_cache_access():
        pytest.fail("Unversioned observations must not consult Redis")

    monkeypatch.setattr(cmdb_api, "get_cmdb_query_cache", reject_cache_access)
    source = {"count": 1}
    generation = {"cmdb": {"interfaces": 7}}
    first, first_state = cmdb_api._cached_cmdb_projection(
        resource, generation, {}, {}, lambda: dict(source),
    )
    source["count"] = 2
    second, second_state = cmdb_api._cached_cmdb_projection(
        resource, generation, {}, {}, lambda: dict(source),
    )

    assert first == {"count": 1}
    assert second == {"count": 2}
    assert first_state == second_state == "bypass"
