import pytest

from api import monitoring


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self):
        self.closed = False

    def execute(self, statement, _params=()):
        if "FROM devices" in statement:
            return _Result({
                "id": "device-1",
                "hostname": "edge-1",
                "ip_address": "192.0.2.10",
                "platform": "h3c_comware7",
                "status": "online",
                "device_category": "switch",
            })
        raise AssertionError(f"unexpected query: {statement}")

    def close(self):
        self.closed = True


class _Provider:
    def range(self, *, metric_key, **_kwargs):
        if metric_key == "interface_rx_bps":
            return {"status": "error", "error": "victoriametrics unavailable", "data": []}
        return {"status": "success", "data": []}


def test_victoria_metrics_trend_surfaces_provider_error(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(monitoring, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring, "provider_from_environment", lambda mode: _Provider())

    result = monitoring.monitoring_device_trend(
        "device-1",
        range_hours=24,
        interface_name=None,
        resolution="auto",
        start_time=None,
        end_time=None,
        provider="victoriametrics",
        user={"role": "Administrator"},
    )

    assert result["provider"] == "victoriametrics"
    assert result["status"] == "error"
    assert "victoriametrics unavailable" in result["error"]
    assert connection.closed is True


def test_extract_instant_metric_value():
    from services.metric_provider import extract_instant_metric_value

    assert extract_instant_metric_value(None) is None
    assert extract_instant_metric_value([]) is None
    assert extract_instant_metric_value([{"value": [1700000000, "NaN"]}]) is None

    # Single value
    data_single = [{"metric": {"slot": "1"}, "value": [1700000000, "15.42"]}]
    assert extract_instant_metric_value(data_single) == 15.4

    # Multi-board max value
    data_multi = [
        {"metric": {"slot": "1"}, "value": [1700000000, "12.0"]},
        {"metric": {"slot": "2"}, "value": [1700000000, "34.8"]},
        {"metric": {"slot": "3"}, "value": [1700000000, "22.5"]},
    ]
    assert extract_instant_metric_value(data_multi) == 34.8


def test_victoria_metrics_selector_regex():
    from services.metric_provider import VictoriaMetricsMetricProvider

    # Hardware aliases resolve only to the normalized Nexora metric families.
    expected_families = {
        "cpu_usage_percent": "nexora_hw_cpu_usage_percent",
        "memory_usage_percent": "nexora_hw_memory_usage_percent",
        "temperature_celsius": "nexora_hw_temperature_celsius",
    }
    for alias, family in expected_families.items():
        assert VictoriaMetricsMetricProvider._selector(alias, "asset-123") == (
            f'{family}{{asset_id="asset-123",source_type=~"librenms_rule|librenms_os_rule|librenms_mib_rule"}}'
        )

    # Multi-ID union -> regex match, still restricted to the normalized family.
    sel_regex = VictoriaMetricsMetricProvider._selector("cpu_usage_percent", "asset-123|dev-456")
    assert sel_regex == (
        'nexora_hw_cpu_usage_percent{asset_id=~"asset-123|dev-456",'
        'source_type=~"librenms_rule|librenms_os_rule|librenms_mib_rule"}'
    )
    assert all(
        raw_name not in sel_regex
        for raw_name in (
            "cpmCPUTotal1minRev", "hh3cEntityExtCpuUsage", "hwEntityCpuUsage",
            "ruijieCpuCostRate", "hh3cEntityExtMemUsage", "hwEntityTemperature",
        )
    )
    for raw_vendor_metric in (
        "cpmCPUTotal1minRev", "hh3cEntityExtCpuUsage", "hwEntityMemUsage",
        "ruijieDeviceTemperature", "hwWlanCurJointApNum", "hh3cDot11CurrAssocUserNum",
    ):
        with pytest.raises(ValueError, match="Raw vendor hardware metrics"):
            VictoriaMetricsMetricProvider._selector(raw_vendor_metric, "asset-123")

    normalized_family = VictoriaMetricsMetricProvider._selector(
        "nexora_hw_fan_speed_rpm", "asset-123",
    )
    assert normalized_family == (
        'nexora_hw_fan_speed_rpm{asset_id="asset-123",'
        'source_type=~"librenms_rule|librenms_os_rule|librenms_mib_rule"}'
    )
    capability_selector = VictoriaMetricsMetricProvider._selector(
        "nexora_hw_capability_status", "asset-123",
    )
    assert capability_selector == (
        'nexora_hw_capability_status{asset_id="asset-123",'
        'source_type=~"librenms_rule|librenms_os_rule|librenms_mib_rule"}'
    )
    assert "librenms_adapter" not in capability_selector

    ap_selector = VictoriaMetricsMetricProvider._selector("wireless_ap_online_count", "wlc-1")
    assert 'nexora_wireless_sensor_value{asset_id="wlc-1"' in ap_selector
    assert 'component_class="wireless_controller"' in ap_selector
    assert 'sensor_class="ap-count"' in ap_selector
    assert 'source_type=~"librenms_rule|librenms_mib_rule"' in ap_selector
    assert all(
        raw_name not in ap_selector
        for raw_name in ("hh3cDot11", "ruijieApc", "cLApTotal", "wlsxSysExt", "ruckusZD", "hwWlan")
    )

    client_selector = VictoriaMetricsMetricProvider._selector("wireless_client_online_count", "wlc-1")
    assert 'nexora_wireless_sensor_value{asset_id="wlc-1"' in client_selector
    assert 'component_class="wireless_controller"' in client_selector
    assert 'component_class="wireless_ssid"' in client_selector
    assert 'component_class="wireless_radio"' in client_selector
    assert 'component_class="wireless_access_point"' in client_selector
    assert 'sensor_class="clients"' in client_selector
    assert 'source_type=~"librenms_rule|librenms_mib_rule"' in client_selector
    assert all(
        raw_name not in client_selector
        for raw_name in ("hwWlan", "hh3cDot11", "ruijieApc", "cLSysTotal", "wlsxSysExt", "ruckusZD")
    )

    # sysUpTime is SNMP TimeTicks (centiseconds); the public key is seconds.
    assert VictoriaMetricsMetricProvider._selector("device_uptime_seconds", "asset-123") == (
        '(last_over_time(sysUpTime{asset_id="asset-123"}[20m]) + '
        '(time() - timestamp(last_over_time(sysUpTime{asset_id="asset-123"}[20m]))) * 100) / 100'
    )
    assert VictoriaMetricsMetricProvider._selector("device_uptime_seconds", None) == (
        "(last_over_time(sysUpTime[20m]) + "
        "(time() - timestamp(last_over_time(sysUpTime[20m]))) * 100) / 100"
    )

    # Interface counter with regex inside rate()
    sel_rate = VictoriaMetricsMetricProvider._selector("interface_rx_bps", "asset-123|dev-456")
    assert 'ifHCInOctets{asset_id=~"asset-123|dev-456"}' in sel_rate


@pytest.mark.parametrize(
    ("selected_provider", "has_standard_samples"),
    [
        ("native", True),
        ("native", False),
        ("victoriametrics", True),
        ("shadow", True),
        ("victoriametrics", False),
        ("shadow", False),
    ],
)
def test_monitoring_device_realtime_uses_standard_metrics_without_snapshot_fallback(
    monkeypatch, selected_provider, has_standard_samples,
):
    class _RealtimeConn:
        def __init__(self):
            self.closed = False

        def execute(self, statement, _params=()):
            if "FROM devices" in statement:
                return _Result({
                    "id": "device-1",
                    "hostname": "edge-1",
                    "ip_address": "192.0.2.10",
                    "platform": "h3c_comware7",
                    "status": "online",
                    "device_category": "switch",
                    "sys_name": "Edge-1",
                    "cpu_usage": 91.0,
                    "memory_usage": 92.0,
                    "temp": 66.0,
                    "fan_status": "ok",
                    "psu_status": "ok",
                    "asset_id": "asset-1",
                })
            if "FROM interface_telemetry_raw" in statement:
                class _EmptyFetch:
                    def fetchall(self):
                        return []
                return _EmptyFetch()
            if "FROM snmp_interface_counter_samples" in statement:
                return _Result(None)
            raise AssertionError(f"unexpected query: {statement}")

        def close(self):
            self.closed = True

    class _InstantProvider:
        def __init__(self):
            self.queries = []

        def instant(self, *, query, asset_id=None, **_kwargs):
            self.queries.append(query)
            if not has_standard_samples:
                return {"status": "success", "data": []}
            if query == "cpu_usage_percent":
                return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "28.6"]}]}
            if query == "memory_usage_percent":
                return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "55.2"]}]}
            if query == "temperature_celsius":
                return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "36.0"]}]}
            if query == "device_uptime_seconds":
                return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "90061"]}]}
            return {"status": "success", "data": []}

    connection = _RealtimeConn()
    provider_instance = _InstantProvider()
    provider_modes = []
    monkeypatch.setattr(monitoring, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring, "fetch_interface_data", lambda conn, dev_id: [])
    monkeypatch.setattr(
        monitoring,
        "provider_from_environment",
        lambda mode: provider_modes.append(mode) or provider_instance,
    )
    from services import snmp_hardware_inventory_service
    monkeypatch.setattr(snmp_hardware_inventory_service, "list_hardware_sensors", lambda *_args, **_kwargs: [])

    payload = monitoring.monitoring_device_realtime(
        "device-1",
        window_minutes=15,
        limit=100,
        provider=selected_provider,
        user={"role": "Administrator"},
    )

    assert provider_instance.queries == [
        "cpu_usage_percent", "memory_usage_percent", "temperature_celsius", "device_uptime_seconds",
    ]
    assert provider_modes == ["victoriametrics" if selected_provider == "native" else selected_provider]
    if has_standard_samples:
        assert payload["device"]["cpu_usage"] == 28.6
        assert payload["device"]["memory_usage"] == 55.2
        assert payload["device"]["temp"] == 36.0
        assert payload["device"]["uptime_seconds"] == 90061.0
    else:
        assert payload["device"]["cpu_usage"] is None
        assert payload["device"]["memory_usage"] is None
        assert payload["device"]["temp"] is None
        assert payload["device"]["uptime_seconds"] is None
    assert payload["device"]["fan_status"] is None
    assert payload["device"]["psu_status"] is None
    assert connection.closed is True


def test_hardware_component_status_uses_fresh_trusted_librenms_state_codes(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from api.monitoring import _summarize_hardware_component_statuses
    from services.snmp_hardware_poller_service import DISCOVERY_VERSION

    now = datetime(2026, 10, 9, 4, 0, tzinfo=timezone.utc)
    source = {
        "source_type": "librenms_rule",
        "source_commit": "6c26b4fe4a40f7b392c19c36a44257212736e38c",
        "source_path": "resources/definitions/os_discovery/comware.yaml",
    }

    def sensor(component_class, state, *, age=timedelta(seconds=20), provenance=None):
        return {
            **source,
            **(provenance or {}),
            "component_class": component_class,
            "measurement_type": "component_state",
            "last_value": state,
            "last_quality": "good",
            "last_success": now - age,
            "lifecycle_status": "active",
            "enabled": True,
            "metadata": {
                **source,
                "collection_version": DISCOVERY_VERSION,
                "poll_interval_seconds": 60,
            },
        }

    sensors = [
        sensor("fan_state", 0),  # LibreNMS generic 0 is healthy.
        sensor("fan_state", 2, age=timedelta(minutes=10)),  # stale critical must be ignored.
        sensor("power_supply_state", 1),  # warning remains distinguishable from failure.
        sensor("power_supply_state", 2, provenance={"source_type": "h3c_wireless"}),
    ]

    assert _summarize_hardware_component_statuses(sensors, now=now) == {
        "fan_status": "ok",
        "psu_status": "warning",
    }
    assert _summarize_hardware_component_statuses(
        [sensor("fan_state", 2)], now=now,
    )["fan_status"] == "failed"
    assert _summarize_hardware_component_statuses(
        [sensor("fan_state", 2, age=timedelta(minutes=10))], now=now,
    )["fan_status"] is None


def test_native_provider_does_not_read_unverified_device_hardware_snapshots():
    from datetime import datetime, timezone

    from services.metric_provider import NativeMetricProvider

    def fail_if_connected():
        raise AssertionError("Native hardware metrics must not read device snapshot columns")

    provider = NativeMetricProvider(connection_factory=fail_if_connected)
    for metric_key in ("cpu_usage_percent", "memory_usage_percent", "temperature_celsius", "device_uptime_seconds"):
        assert provider.latest(asset_id="device-1", metric_key=metric_key)["data"] == []
        assert provider.range(
            query=metric_key,
            asset_id="device-1",
            metric_key=metric_key,
            start=datetime(2026, 10, 8, tzinfo=timezone.utc),
            end=datetime(2026, 10, 8, 1, tzinfo=timezone.utc),
            step_seconds=60,
        )["data"] == []


def test_shadow_provider_uses_normalized_metrics_for_hardware_and_wireless():
    from datetime import datetime, timezone

    from services.metric_provider import ShadowMetricProvider

    class _Native:
        def instant(self, **_kwargs):
            raise AssertionError("Shadow mode must not consult native hardware snapshots")

        def range(self, **_kwargs):
            raise AssertionError("Shadow mode must not consult native hardware snapshots")

    class _VictoriaMetrics:
        def __init__(self):
            self.instant_calls = []
            self.range_calls = []

        def instant(self, *, query, asset_id=None, metric_key=None):
            self.instant_calls.append((query, asset_id, metric_key))
            return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "18.5"]}]}

        def range(self, *, query, start, end, step_seconds, asset_id=None, metric_key=None):
            self.range_calls.append((query, asset_id, metric_key))
            return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "values": [[1700000000, "18.5"]]}]}

    vm = _VictoriaMetrics()
    provider = ShadowMetricProvider(_Native(), vm)
    instant = provider.latest(asset_id="asset-1", metric_key="cpu_usage_percent")
    ranged = provider.range(
        query="wireless_ap_online_count",
        asset_id="asset-1",
        metric_key="wireless_ap_online_count",
        start=datetime(2026, 10, 8, tzinfo=timezone.utc),
        end=datetime(2026, 10, 8, 1, tzinfo=timezone.utc),
        step_seconds=60,
    )

    assert instant["provider"] == "shadow"
    assert instant["data"][0]["value"][1] == "18.5"
    assert "shadow" not in instant
    assert ranged["provider"] == "shadow"
    assert ranged["data"]
    assert "shadow" not in ranged
    assert vm.instant_calls == [("cpu_usage_percent", "asset-1", "cpu_usage_percent")]
    assert vm.range_calls == [("wireless_ap_online_count", "asset-1", "wireless_ap_online_count")]

