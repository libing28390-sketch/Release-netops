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
