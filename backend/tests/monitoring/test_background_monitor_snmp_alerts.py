from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

from services import background_monitor_service as monitor


def _device(device_id: str = "snmp-alert-device") -> dict:
    return {
        "id": device_id,
        "hostname": "edge-test",
        "ip_address": "192.0.2.10",
        "status": "online",
        "cpu_history": "[]",
        "memory_history": "[]",
        "platform": "cisco_ios",
        "role": "access",
        "model": "",
        "version": "",
    }


def _mock_monitor_io(monkeypatch, *, probe: AsyncMock) -> None:
    monkeypatch.setattr(monitor, "_get_semaphore", lambda: asyncio.Semaphore(2))
    monkeypatch.setattr(monitor, "_should_collect", lambda *_args: False)
    monkeypatch.setattr(monitor, "_probe_device_reachability_snmp_first", probe)
    monkeypatch.setattr(monitor, "record_collection_result", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "resolve_alert_rule", lambda *_args, **_kwargs: {
        "id": "snmp-alert-test-rule",
        "metric_type": "snmp_unreachable",
        "severity": "major",
    })
    monkeypatch.setattr(monitor, "_db_quick", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(monitor, "_sync_device_status_tag", lambda *_args: None)
    monkeypatch.setattr(monitor, "_schedule_monitoring_target_sync", lambda *_args: None)
    monkeypatch.setattr(monitor, "_set_protocol_alerts_for_device_offline", lambda *_args: None)
    monkeypatch.setattr(monitor, "_set_device_reachability_alert", lambda *_args, **_kwargs: None)


def test_unconfigured_snmp_clears_failure_streak_without_opening_alert(monkeypatch) -> None:
    device = _device("unconfigured-snmp-device")
    probe = AsyncMock(return_value=(True, "icmp", {"snmp": {"configured": False}}, False))
    alert_calls: list[tuple[tuple, dict]] = []

    _mock_monitor_io(monkeypatch, probe=probe)
    monkeypatch.setattr(monitor, "snmp_failure_streak", {device["id"]: 4})
    monkeypatch.setattr(monitor, "open_alerts", {})
    monkeypatch.setattr(
        monitor,
        "set_alert_state",
        lambda *args, **kwargs: alert_calls.append((args, kwargs)),
    )

    asyncio.run(monitor._process_device_raw(device, cycle_tick=0))

    assert device["id"] not in monitor.snmp_failure_streak
    assert alert_calls == []
    probe.assert_awaited_once_with(device)


def test_configured_snmp_failure_alerts_after_two_consecutive_samples(monkeypatch) -> None:
    device = _device("configured-snmp-device")
    credentials = {"snmp": {"configured": True}}
    probe = AsyncMock(
        side_effect=[
            (True, "icmp", credentials, True),
            (True, "tcp", credentials, True),
        ]
    )
    alert_calls: list[tuple[tuple, dict]] = []

    _mock_monitor_io(monkeypatch, probe=probe)
    monkeypatch.setattr(monitor, "snmp_failure_streak", {})
    monkeypatch.setattr(monitor, "open_alerts", {})
    monkeypatch.setattr(
        monitor,
        "set_alert_state",
        lambda *args, **kwargs: alert_calls.append((args, kwargs)),
    )

    async def collect_two_samples() -> None:
        await monitor._process_device_raw(dict(device), cycle_tick=0)
        await monitor._process_device_raw(dict(device), cycle_tick=1)

    asyncio.run(collect_two_samples())

    snmp_calls = [
        (args, kwargs)
        for args, kwargs in alert_calls
        if args and args[0] == f"snmp_unreachable:{device['id']}"
    ]
    assert len(snmp_calls) == 2
    assert [args[1] for args, _kwargs in snmp_calls] == [False, True]
    assert snmp_calls[-1][1]["status"] == "active"
    assert monitor.snmp_failure_streak[device["id"]] == 2
    assert probe.await_count == 2


def _run_startup_with_legacy_snmp_rows(monkeypatch, rows: list[dict]) -> list[tuple[tuple, dict]]:
    def fake_db_quick(sql, *_args, **_kwargs):
        if "SELECT dedupe_key, created_at FROM alert_events" in sql:
            return []
        if "FROM protocol_peer_state" in sql:
            return []
        if "message LIKE '%凭据未配置%'" in sql:
            return rows
        raise AssertionError("unexpected database access during telemetry startup")

    alert_calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(monitor, "_db_quick", fake_db_quick)
    monkeypatch.setattr(monitor, "open_alerts", {})
    monkeypatch.setattr(monitor, "protocol_peer_cache", {})
    monkeypatch.setattr(monitor, "current_alert_rules_by_tenant", {})
    monkeypatch.setattr(monitor, "_refresh_runtime_alert_rules", lambda **_kwargs: [])
    monkeypatch.setattr(
        monitor,
        "resolve_alert_rule",
        Mock(return_value={"id": "legacy-snmp-rule", "severity": "major"}),
    )
    monkeypatch.setattr(
        monitor,
        "set_alert_state",
        lambda *args, **kwargs: alert_calls.append((args, kwargs)),
    )

    monitor._init_telemetry_state()
    return alert_calls


def test_startup_silently_resolves_duplicate_legacy_unconfigured_snmp_alerts(monkeypatch) -> None:
    duplicate = {
        "dedupe_key": "snmp_unreachable:legacy-device",
        "device_id": "legacy-device",
        "severity": "major",
        "title": "SNMP Unreachable",
    }

    alert_calls = _run_startup_with_legacy_snmp_rows(monkeypatch, [duplicate, dict(duplicate)])

    assert len(alert_calls) == 1
    args, kwargs = alert_calls[0]
    assert args[0:2] == ("snmp_unreachable:legacy-device", False)
    assert "凭据未配置" in args[4]
    assert kwargs["status"] == "resolved"
    assert kwargs["notify"] is False


def test_startup_with_no_legacy_snmp_alerts_does_not_emit_transitions(monkeypatch) -> None:
    alert_calls = _run_startup_with_legacy_snmp_rows(monkeypatch, [])

    assert alert_calls == []


def test_asset_link_or_ssh_credential_alone_does_not_schedule_snmp_target_sync(monkeypatch) -> None:
    from services import collector_sync_service

    scheduled: list[float] = []
    monkeypatch.setattr(
        collector_sync_service,
        "trigger_async_monitoring_sync",
        lambda *, delay_seconds: scheduled.append(delay_seconds),
    )

    monitor._schedule_monitoring_target_sync({"asset_id": "asset-without-snmp"})
    monitor._schedule_monitoring_target_sync({
        "asset_id": "asset-with-ssh",
        "credential_id": "ssh-credential",
    })

    assert scheduled == []


def test_snmp_credential_and_server_targets_still_schedule_sync(monkeypatch) -> None:
    from services import collector_sync_service

    scheduled: list[float] = []
    monkeypatch.setattr(
        collector_sync_service,
        "trigger_async_monitoring_sync",
        lambda *, delay_seconds: scheduled.append(delay_seconds),
    )

    monitor._schedule_monitoring_target_sync({"snmp_credential_id": "snmp-profile"})
    monitor._schedule_monitoring_target_sync({"role": "server", "asset_id": "server-asset"})

    assert scheduled == [15.0, 15.0]
