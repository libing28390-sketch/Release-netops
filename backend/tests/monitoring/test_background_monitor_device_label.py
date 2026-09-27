from __future__ import annotations

import asyncio

from services import background_monitor_service as monitor


def test_online_health_collection_keeps_device_label_for_alert_messages(isolated_db, monkeypatch) -> None:
    device = {
        "id": "monitor-device-label",
        "hostname": "edge-01",
        "ip_address": "192.0.2.10",
        "status": "online",
        "platform": "cisco_ios",
        "asset_type": "network",
        "device_category": "network",
        "role": "core",
        "model": "",
        "version": "",
        "cpu_history": "[]",
        "memory_history": "[]",
    }
    recorded_alerts: list[tuple[tuple, dict]] = []
    metrics = {metric: None for metric in monitor.HEALTH_METRIC_KEYS}
    metrics.update({monitor.HEALTH_METRIC_KEYS[0]: 42.0, monitor.HEALTH_METRIC_KEYS[1]: 38.0})

    async def reachable(_ip: str, _port: int) -> tuple[bool, str]:
        return True, "test"

    async def collect_metrics(*_args, **_kwargs) -> dict:
        return {
            "cpu_usage": 42.0,
            "memory_usage": 38.0,
            "temp": None,
            "fan_status": None,
            "psu_status": None,
            "metric_details": {},
            "hardware_metrics": metrics,
        }

    monkeypatch.setattr(monitor, "_device_poll_profile", lambda _device: {"interface": 10, "info": 10, "protocol": 10})
    monkeypatch.setattr(monitor, "_should_collect", lambda _cycle, _interval: False)
    monkeypatch.setattr(monitor, "_probe_device_reachability", reachable)
    monkeypatch.setattr(monitor, "resolve_collector_credentials", lambda _device: {"snmp": {"server": "192.0.2.10", "community": "test-only", "port": 161}})
    monkeypatch.setattr(monitor, "load_discovery", lambda _device_id: {"status": "matched", "metrics": {}, "interface": {}})
    monkeypatch.setattr(monitor, "_discovery_is_stale", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(monitor, "resolve_health_metric_profiles", lambda _device: {"profile_status": "verified", "metrics": {"cpu": "1", "memory": "2"}, "profile_id": "test-profile"})
    monkeypatch.setattr(monitor, "collect_device_metrics", collect_metrics)
    monkeypatch.setattr(monitor, "resolve_alert_rule", lambda *_args, **_kwargs: {"threshold": 80, "severity": "major"})
    monkeypatch.setattr(monitor, "set_alert_state", lambda *args, **kwargs: recorded_alerts.append((args, kwargs)))
    monkeypatch.setattr(monitor, "record_collection_result", lambda *_args, **_kwargs: None)

    asyncio.run(monitor.process_device_slow(device, cycle_tick=1))

    messages = [str(args[4]) for args, _kwargs in recorded_alerts if len(args) > 4]
    assert any(message.startswith("edge-01 CPU ") for message in messages)
    assert any(message.startswith("edge-01 内存利用率") for message in messages)
