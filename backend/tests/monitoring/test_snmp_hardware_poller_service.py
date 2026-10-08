from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from services import snmp_hardware_poller_service as poller


def test_collect_device_hardware_runs_due_discovery_and_sample(monkeypatch) -> None:
    from services import snmp_hardware_probe_service, vault_service

    discovery_calls: list[dict] = []
    sample_calls: list[tuple] = []
    sensor = {
        "sensor_key": "cpu-0",
        "last_sample_at": datetime.now(timezone.utc) - timedelta(minutes=10),
        "enabled": True,
    }

    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {"server": "192.0.2.10", "community": "test-community", "port": 1161, "version": "2c"},
    })
    monkeypatch.setattr(poller, "_discovery_due", lambda *_args: True)

    async def discover(**kwargs):
        discovery_calls.append(kwargs)
        return {"status": "success", "sensor_count": 1}

    monkeypatch.setattr(poller, "_discover_device", discover)
    monkeypatch.setattr(poller, "_load_active_sensors", lambda _device_id: [sensor])

    async def sample(*args):
        sample_calls.append(args)
        return {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}

    monkeypatch.setattr(snmp_hardware_probe_service, "poll_hardware_inventory", sample)

    result = asyncio.run(poller.collect_device_hardware({
        "id": "device-1", "ip_address": "192.0.2.10", "platform": "h3c_comware",
    }))

    assert result["status"] == "collected"
    assert discovery_calls[0]["device"]["id"] == "device-1"
    assert discovery_calls[0]["version"] == "2c"
    assert discovery_calls[0]["port"] == 1161
    assert sample_calls[0] == (
        "192.0.2.10", "test-community", 1161, "2c", [sensor],
    )


def test_server_assets_are_skipped_before_snmp_credentials_are_read(monkeypatch) -> None:
    from services import vault_service

    monkeypatch.setattr(
        vault_service,
        "resolve_collector_credentials",
        lambda _device: (_ for _ in ()).throw(AssertionError("server credentials must not be loaded")),
    )

    result = asyncio.run(poller.collect_device_hardware({
        "id": "server-1", "asset_type": "server", "ip_address": "192.0.2.11",
    }))

    assert result == {"status": "skipped"}


def test_failed_discovery_is_persisted_and_uses_retry_backoff(monkeypatch) -> None:
    from services import vault_service

    observed: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    discovery_due = poller._discovery_due

    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {"server": "192.0.2.12", "community": "test-community", "port": 161, "version": "2c"},
    })
    monkeypatch.setattr(poller, "_discovery_due", lambda *_args: True)

    async def fail_discovery(**_kwargs):
        raise TimeoutError("SNMP timeout")

    monkeypatch.setattr(poller, "_discover_device", fail_discovery)
    monkeypatch.setattr(poller, "_load_active_sensors", lambda _device_id: [])
    monkeypatch.setattr(poller, "_persist_discovery", lambda **kwargs: observed.append(kwargs) or {})

    result = asyncio.run(poller.collect_device_hardware({
        "id": "device-2", "ip_address": "192.0.2.12", "platform": "h3c_comware",
    }))

    assert result["status"] == "discovery_failed"
    assert result["discovery"]["failure_persisted"] is True
    assert observed[0]["category_results"][0]["status"] == "failed"
    assert observed[0]["category_results"][0]["reason_code"] == "snmp_discovery_error"

    monkeypatch.setattr(poller, "_latest_discovery", lambda _device_id: {
        "last_status": "failed",
        "last_attempt_at": now - timedelta(minutes=5),
    })
    assert discovery_due("device-2", now) is False
    monkeypatch.setattr(poller, "_latest_discovery", lambda _device_id: {
        "last_status": "failed",
        "last_attempt_at": now - timedelta(minutes=16),
    })
    assert discovery_due("device-2", now) is True


def test_rule_probe_exception_is_persisted_even_when_standard_probe_returned_categories(monkeypatch) -> None:
    from services import librenms_rule_service, snmp_hardware_probe_service, snmp_service

    persisted: list[dict[str, Any]] = []
    identity_values = {
        snmp_service.SYS_NAME: "AC_11",
        snmp_service.SYS_DESCR: "H3C Comware wireless controller",
        snmp_service.SYS_OBJECT_ID: "1.3.6.1.4.1.25506.1.1",
    }

    async def get_identity(_ip, _community, oid, _port, _version):
        return identity_values[oid]

    async def standard_probe(*_args, **_kwargs):
        return {"sensors": [], "category_results": [{
            "source_type": "standard_mib",
            "component_class": "processor",
            "status": "not_found",
            "coverage_complete": True,
        }]}

    async def fail_rule_probe(*_args, **_kwargs):
        raise RuntimeError("adapter failure")

    monkeypatch.setattr(librenms_rule_service, "ensure_rules_available", lambda: None)
    monkeypatch.setattr(snmp_service, "_snmp_get_versioned", get_identity)
    monkeypatch.setattr(poller, "_resolve_identity_and_rule", lambda **_kwargs: (
        {"vendor": "H3C", "model": "H3C WX5540H", "role": "network_device"},
        {"id": "h3c-comware", "vendor": "H3C", "os_key": "comware", "source_path": "Comware.php"},
    ))
    monkeypatch.setattr(snmp_hardware_probe_service, "probe_standard_hardware", standard_probe)
    monkeypatch.setattr(snmp_hardware_probe_service, "probe_librenms_hardware", fail_rule_probe)
    monkeypatch.setattr(poller, "_persist_discovery", lambda **kwargs: (
        persisted.append(kwargs) or {"results": kwargs["category_results"]}
    ))

    result = asyncio.run(poller._discover_device(
        device={"id": "device-3"},
        ip="192.0.2.13",
        community="test-community",
        port=161,
        version="2c",
    ))

    assert result["status"] == "failed"
    assert any(
        item["component_class"] == "rule_hardware"
        and item["status"] == "failed"
        and item["reason_code"] == "rule_hardware_probe_error"
        for item in persisted[0]["category_results"]
    )


def test_collect_device_hardware_uses_bound_snmpv3_profile_without_community(monkeypatch) -> None:
    from services import snmp_hardware_probe_service, vault_service

    profile = {
        "version": "3",
        "server": "192.0.2.30",
        "port": 1161,
        "community": "",
        "username": "poller-user",
        "security_level": "authPriv",
        "auth_protocol": "SHA",
        "auth_password": "test-auth-key",
        "priv_protocol": "AES",
        "priv_password": "test-privacy-key",
        "context_name": "",
        "configured": True,
        "configuration_error": "",
    }
    discovery_calls: list[dict[str, Any]] = []
    sample_calls: list[tuple] = []
    sensor = {
        "sensor_key": "cpu-0",
        "last_sample_at": datetime.now(timezone.utc) - timedelta(minutes=10),
        "enabled": True,
    }

    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {"snmp": profile})
    monkeypatch.setattr(poller, "_discovery_due", lambda *_args: True)

    async def discover(**kwargs):
        discovery_calls.append(kwargs)
        return {"status": "success", "sensor_count": 1}

    monkeypatch.setattr(poller, "_discover_device", discover)
    monkeypatch.setattr(poller, "_load_active_sensors", lambda _device_id: [sensor])

    async def sample(*args):
        sample_calls.append(args)
        return {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}

    monkeypatch.setattr(snmp_hardware_probe_service, "poll_hardware_inventory", sample)

    result = asyncio.run(poller.collect_device_hardware({
        "id": "device-v3", "ip_address": "192.0.2.30", "platform": "h3c_comware",
    }))

    assert result["status"] == "collected"
    assert discovery_calls[0]["version"] == "3"
    assert discovery_calls[0]["community"] is profile
    assert sample_calls[0] == ("192.0.2.30", profile, 1161, "3", [sensor])
    assert "auth_password" not in result and "priv_password" not in result
