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
        if statement.startswith("SELECT id, hostname"):
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

    # Single asset ID -> equality
    sel_single = VictoriaMetricsMetricProvider._selector("cpu_usage_percent", "asset-123")
    assert 'cpmCPUTotal1minRev{asset_id="asset-123"}' in sel_single
    assert 'ruijieCpuCostRate{asset_id="asset-123"}' in sel_single

    # Multi-ID union -> regex match
    sel_regex = VictoriaMetricsMetricProvider._selector("cpu_usage_percent", "asset-123|dev-456")
    assert 'cpmCPUTotal1minRev{asset_id=~"asset-123|dev-456"}' in sel_regex
    assert 'hh3cEntityExtCpuUsage{asset_id=~"asset-123|dev-456"}' in sel_regex

    # Interface counter with regex inside rate()
    sel_rate = VictoriaMetricsMetricProvider._selector("interface_rx_bps", "asset-123|dev-456")
    assert 'ifHCInOctets{asset_id=~"asset-123|dev-456"}' in sel_rate


def test_monitoring_device_realtime_resolves_provider_metrics(monkeypatch):
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
                    "cpu_usage": None,
                    "memory_usage": None,
                    "temp": None,
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
        def instant(self, *, query, asset_id=None, **_kwargs):
            if query == "cpu_usage_percent":
                return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "28.6"]}]}
            if query == "memory_usage_percent":
                return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "55.2"]}]}
            if query == "temperature_celsius":
                return {"status": "success", "data": [{"metric": {"asset_id": asset_id}, "value": [1700000000, "36.0"]}]}
            return {"status": "success", "data": []}

    connection = _RealtimeConn()
    monkeypatch.setattr(monitoring, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring, "fetch_interface_data", lambda conn, dev_id: [])
    monkeypatch.setattr(monitoring, "provider_from_environment", lambda mode: _InstantProvider())

    payload = monitoring.monitoring_device_realtime(
        "device-1",
        window_minutes=15,
        limit=100,
        provider="victoriametrics",
        user={"role": "Administrator"},
    )

    assert payload["device"]["cpu_usage"] == 28.6
    assert payload["device"]["memory_usage"] == 55.2
    assert payload["device"]["temp"] == 36.0
    assert connection.closed is True

