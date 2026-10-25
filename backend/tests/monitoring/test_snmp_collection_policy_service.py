from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from services.snmp_collection_policy_service import is_snmp_collection_enabled


@pytest.mark.parametrize("device", [{}, {"snmp_collection_enabled": None}, {"snmp_collection_enabled": True}, {"snmp_collection_enabled": 1}])
def test_snmp_collection_defaults_to_enabled(device):
    assert is_snmp_collection_enabled(device) is True


@pytest.mark.parametrize("value", [False, 0, "false", "off", "disabled", " NO "])
def test_snmp_collection_switch_accepts_disabled_values(value):
    assert is_snmp_collection_enabled({"snmp_collection_enabled": value}) is False


def test_hardware_poller_skips_disabled_device_before_credential_lookup(monkeypatch):
    from services import snmp_hardware_poller_service as poller

    def unexpected_credentials(_device):
        raise AssertionError("disabled device must not resolve or use SNMP credentials")

    monkeypatch.setattr("services.vault_service.resolve_collector_credentials", unexpected_credentials)

    result = asyncio.run(poller.collect_device_hardware({
        "id": "disabled-device",
        "snmp_collection_enabled": False,
    }))

    assert result == {"status": "skipped", "reason": "snmp_collection_disabled"}


def test_interface_snmp_fallback_returns_none_when_disabled(monkeypatch):
    from services.interface_collection_service import _collect_snmp_interfaces

    monkeypatch.setattr(
        "services.vault_service.resolve_collector_credentials",
        lambda _device: (_ for _ in ()).throw(AssertionError("must not resolve SNMP credentials")),
    )

    assert _collect_snmp_interfaces({"id": "disabled-device", "snmp_collection_enabled": False}) is None


def test_reachability_uses_icmp_tcp_without_snmp_when_disabled(monkeypatch):
    from services import background_monitor_service as monitor

    device = {
        "id": "disabled-device",
        "ip_address": "192.0.2.10",
        "snmp_credential_id": "snmp-profile",
        "snmp_collection_enabled": False,
    }
    probe_calls: list[tuple[str, int]] = []

    async def fallback_probe(host, port):
        probe_calls.append((host, port))
        return True, "icmp"

    class ProbeLimiter:
        @asynccontextmanager
        async def async_probe(self):
            yield

    monkeypatch.setattr(monitor, "_probe_device_reachability", fallback_probe)
    monkeypatch.setattr(monitor, "get_network_access_limiter", lambda: ProbeLimiter())
    monkeypatch.setattr(
        monitor,
        "resolve_collector_credentials",
        lambda _device: (_ for _ in ()).throw(AssertionError("disabled device must skip SNMP credential lookup")),
    )

    result = asyncio.run(monitor._probe_device_reachability_snmp_first(device))

    assert result == (True, "icmp", None, False)
    assert probe_calls == [("192.0.2.10", 22)]
