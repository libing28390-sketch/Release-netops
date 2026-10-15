from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from services import snmp_hardware_poller_service as poller


def test_older_hardware_discovery_version_is_refreshed(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(poller, "_latest_discovery", lambda _device_id: {
        "last_status": "success",
        "last_attempt_at": now,
        "discovery_version": "nexora-librenms-rules-hardware-v6",
    })

    assert poller._discovery_due("device-old-hardware-plan", now) is True


def test_active_sensor_loading_reuses_trust_checks_by_provenance(monkeypatch) -> None:
    from services import librenms_source_policy

    class Connection:
        def close(self) -> None:
            pass

    def sensor(sensor_key: str, rule_key: str, source_type: str = "librenms_mib_rule") -> dict:
        return {
            "sensor_key": sensor_key,
            "enabled": True,
            "metadata": {
                "collection_version": poller.DISCOVERY_VERSION,
                "source_type": source_type,
                "source_commit": "pinned-commit",
                "source_path": "includes/discovery/sensors.inc.php",
                "rule_key": rule_key,
                "mib_source_files": ["mibs/IF-MIB.mib"],
            },
        }

    rows = [
        sensor("sensor-a", "source-a"),
        sensor("sensor-b", "source-a"),
        sensor("sensor-c", "source-b"),
        sensor("sensor-d", "invalid-source", source_type="untrusted"),
        sensor("sensor-e", "invalid-source", source_type="untrusted"),
        sensor("sensor-disabled", "source-a") | {"enabled": False},
        sensor("sensor-old-version", "source-a") | {
            "metadata": {"collection_version": "old-version"},
        },
    ]
    trust_calls: list[str] = []
    monkeypatch.setattr(poller, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        poller,
        "list_hardware_sensors",
        lambda *_args, **_kwargs: rows,
    )

    def is_trusted(row: dict) -> bool:
        trust_calls.append(row["sensor_key"])
        return row["metadata"]["source_type"] == "librenms_mib_rule"

    monkeypatch.setattr(librenms_source_policy, "is_trusted_hardware_sensor", is_trusted)

    active = poller._load_active_sensors("device-1")

    assert [row["sensor_key"] for row in active] == ["sensor-a", "sensor-b", "sensor-c"]
    assert trust_calls == ["sensor-a", "sensor-c", "sensor-d"]


def test_device_sensor_poll_state_uses_current_version_and_sample_cutoff(monkeypatch) -> None:
    class Cursor:
        def fetchone(self):
            return {"has_active": True, "has_due": False}

    class Connection:
        def __init__(self) -> None:
            self.query = ""
            self.params = ()
            self.closed = False

        def execute(self, query, params):
            self.query = query
            self.params = params
            return Cursor()

        def close(self) -> None:
            self.closed = True

    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    connection = Connection()
    monkeypatch.setattr(poller, "get_db_connection", lambda: connection)
    monkeypatch.setattr(poller, "hardware_sample_interval_seconds", lambda: 60)

    assert poller._device_sensor_poll_state("device-1", now) == (True, False)
    assert "metadata_json->>'collection_version' = ?" in connection.query
    assert "BOOL_OR(last_sample_at IS NULL OR last_sample_at <= ?)" in connection.query
    assert connection.params == (
        now - timedelta(seconds=60),
        "device-1",
        poller.DISCOVERY_VERSION,
    )
    assert connection.closed is True


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


def test_scheduled_discovery_fails_closed_on_tied_librenms_rules(monkeypatch) -> None:
    from services import librenms_rule_service, librenms_source_policy, snmp_discovery_service

    class Connection:
        def close(self) -> None:
            pass

    rule = {
        "id": "comware-a",
        "os_key": "comware-a",
        "identity_match": {"conflicts": [{"os_key": "comware-b", "score": 100}]},
    }
    monkeypatch.setattr(poller, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        snmp_discovery_service,
        "resolve_snmp_vendor_identity",
        lambda *_args, **_kwargs: {"status": "identified", "vendor": "H3C"},
    )
    monkeypatch.setattr(librenms_rule_service, "resolve_rule", lambda *_args, **_kwargs: rule)
    monkeypatch.setattr(librenms_source_policy, "verify_bundled_rule", lambda _rule: True)

    identity, selected_rule = poller._resolve_identity_and_rule(
        device={"id": "device-tied", "vendor": "H3C", "platform": "h3c_comware"},
        sys_object_id="1.3.6.1.4.1.25506",
        sys_descr="H3C Comware",
        sys_name="switch-01",
    )

    assert selected_rule is None
    assert identity["status"] == "ambiguous"
    assert identity["reason_code"] == "ambiguous_librenms_rule"


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
        "discovery_version": poller.DISCOVERY_VERSION,
    })
    assert discovery_due("device-2", now) is False
    monkeypatch.setattr(poller, "_latest_discovery", lambda _device_id: {
        "last_status": "failed",
        "last_attempt_at": now - timedelta(minutes=16),
        "discovery_version": poller.DISCOVERY_VERSION,
    })
    assert discovery_due("device-2", now) is True


def test_rule_probe_exception_is_persisted(monkeypatch) -> None:
    from services import librenms_rule_service, snmp_hardware_probe_service, snmp_service

    persisted: list[dict[str, Any]] = []
    identity_values = {
        snmp_service.SYS_NAME: "AC_11",
        snmp_service.SYS_DESCR: "H3C Comware wireless controller",
        snmp_service.SYS_OBJECT_ID: "1.3.6.1.4.1.25506.1.1",
    }

    async def get_identity(_ip, _community, oid, _port, _version):
        return identity_values[oid]

    async def fail_rule_probe(*_args, **_kwargs):
        raise RuntimeError("pinned rule probe failure")

    monkeypatch.setattr(librenms_rule_service, "ensure_rules_available", lambda: None)
    monkeypatch.setattr(snmp_service, "_snmp_get_versioned", get_identity)
    monkeypatch.setattr(poller, "_resolve_identity_and_rule", lambda **_kwargs: (
        {"vendor": "H3C", "model": "H3C WX5540H", "role": "network_device"},
        {
            "id": "h3c-comware",
            "vendor": "H3C",
            "os_key": "comware",
            "source_path": "resources/definitions/os_discovery/comware.yaml",
        },
    ))
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


def test_discovery_only_run_never_samples_hardware(monkeypatch) -> None:
    from services import snmp_hardware_probe_service, vault_service

    discoveries: list[dict] = []
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {"server": "192.0.2.40", "community": "test-community", "port": 161, "version": "2c"},
    })
    monkeypatch.setattr(poller, "_discovery_due", lambda *_args: True)

    async def discover(**kwargs):
        discoveries.append(kwargs)
        return {"status": "success", "sensor_count": 1}

    async def unexpected_sample(*_args, **_kwargs):
        raise AssertionError("discovery loop must not sample")

    monkeypatch.setattr(poller, "_discover_device", discover)
    monkeypatch.setattr(snmp_hardware_probe_service, "poll_hardware_inventory", unexpected_sample)

    result = asyncio.run(poller.collect_device_hardware(
        {"id": "device-discovery", "ip_address": "192.0.2.40", "platform": "comware"},
        discovery_only=True,
    ))

    assert result["status"] == "discovered"
    assert discoveries and discoveries[0]["device"]["id"] == "device-discovery"


def test_poll_only_run_skips_discovery_and_samples_due_inventory(monkeypatch) -> None:
    from services import snmp_hardware_probe_service, vault_service

    sensor = {
        "sensor_key": "cpu-0",
        "last_sample_at": datetime.now(timezone.utc) - timedelta(minutes=2),
        "enabled": True,
    }
    sample_calls: list[tuple] = []
    monkeypatch.setattr(poller, "_device_sensor_poll_state", lambda *_args: (True, True))
    monkeypatch.setattr(vault_service, "resolve_collector_credentials", lambda _device: {
        "snmp": {"server": "192.0.2.41", "community": "test-community", "port": 161, "version": "2c"},
    })
    monkeypatch.setattr(poller, "_discover_device", lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("poll loop must not discover")
    ))
    monkeypatch.setattr(poller, "_load_active_sensors", lambda _device_id: [sensor])

    async def sample(*args):
        sample_calls.append(args)
        return {"good": 1, "missing": 0, "invalid": 0, "unsupported_mapping": 0}

    monkeypatch.setattr(snmp_hardware_probe_service, "poll_hardware_inventory", sample)

    result = asyncio.run(poller.collect_device_hardware(
        {"id": "device-sample", "ip_address": "192.0.2.41", "platform": "comware"},
        poll_only=True,
    ))

    assert result["status"] == "collected"
    assert len(sample_calls) == 1
    assert sample_calls[0][-1] == [sensor]


def test_poll_only_run_skips_sensor_decode_and_credentials_until_due(monkeypatch) -> None:
    from services import vault_service

    monkeypatch.setattr(poller, "_device_sensor_poll_state", lambda *_args: (True, False))
    monkeypatch.setattr(
        vault_service,
        "resolve_collector_credentials",
        lambda _device: (_ for _ in ()).throw(AssertionError("credentials should not be resolved before poll due")),
    )
    monkeypatch.setattr(
        poller,
        "_load_active_sensors",
        lambda _device_id: (_ for _ in ()).throw(AssertionError("sensor JSON should not be loaded before poll due")),
    )

    result = asyncio.run(poller.collect_device_hardware(
        {"id": "device-not-due", "ip_address": "192.0.2.42", "platform": "comware"},
        poll_only=True,
    ))

    assert result == {
        "status": "idle",
        "discovery": None,
        "sample": {"good": 0, "missing": 0, "invalid": 0, "unsupported_mapping": 0},
    }


def test_staleness_threshold_covers_three_configured_poll_intervals(monkeypatch) -> None:
    monkeypatch.setenv("SNMP_HARDWARE_SAMPLE_INTERVAL_SECONDS", "60")
    monkeypatch.delenv("SNMP_HARDWARE_STALE_SECONDS", raising=False)

    assert poller.hardware_stale_after_seconds({"metadata": {"poll_interval_seconds": 300}}) == 900


def test_snapshot_only_inventory_metrics_stay_fresh_until_next_discovery(monkeypatch) -> None:
    monkeypatch.setenv("SNMP_HARDWARE_SAMPLE_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("SNMP_HARDWARE_STALE_SECONDS", "180")

    threshold = poller.hardware_stale_after_seconds({
        "metadata": {"poll_plan": {"kind": "snapshot_only"}},
    })

    assert threshold == poller.DISCOVERY_INTERVAL_SECONDS + poller.PARTIAL_DISCOVERY_RETRY_SECONDS
