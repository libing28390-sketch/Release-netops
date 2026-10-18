from api import monitoring_v1


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.row = row
        self.closed = False

    def execute(self, statement, params=()):
        assert "collector_type" in statement
        assert params == (self.row["id"],)
        return _Result(self.row)

    def close(self):
        self.closed = True


def test_local_collector_view_uses_actual_runtime_probe(monkeypatch):
    probe_result = {
        "runtime_status": "ONLINE",
        "runtime_probe": "LOCAL_COMPONENT_HEALTH",
        "runtime_checked_at": "2026-10-18T14:00:00+00:00",
        "runtime_components": {"vmagent": "ONLINE", "snmp_exporter": "ONLINE"},
    }
    monkeypatch.setattr(monitoring_v1, "_probe_local_collector_runtime", lambda: probe_result)

    view = monitoring_v1._safe_collector_view({
        "id": "collector-local",
        "collector_type": "LOCAL",
        "enabled": 1,
        "status": "UNKNOWN",
    })

    assert view["status"] == "ONLINE"
    assert view["runtime_status"] == "ONLINE"
    assert view["runtime_components"] == probe_result["runtime_components"]


def test_remote_collector_without_heartbeat_is_unknown_even_if_legacy_status_is_online():
    view = monitoring_v1._safe_collector_view({
        "id": "collector-remote",
        "collector_type": "REMOTE",
        "enabled": 1,
        "status": "ONLINE",
        "last_heartbeat_at": None,
    })

    assert view["status"] == "UNKNOWN"
    assert view["runtime_status"] == "UNKNOWN"
    assert view["runtime_probe"] == "HEARTBEAT_NOT_CONFIGURED"


def test_disabled_collector_skips_runtime_probe(monkeypatch):
    def fail_if_probed():
        raise AssertionError("disabled collector must not be probed")

    monkeypatch.setattr(monitoring_v1, "_probe_local_collector_runtime", fail_if_probed)

    view = monitoring_v1._safe_collector_view({
        "id": "collector-local",
        "collector_type": "LOCAL",
        "enabled": 0,
        "status": "ONLINE",
    })

    assert view["status"] == "DISABLED"
    assert view["runtime_status"] == "DISABLED"
    assert view["runtime_probe"] == "NOT_RUN"


def test_collector_status_check_probes_local_runtime(monkeypatch):
    row = {
        "id": "collector-local",
        "code": "local",
        "enabled": 1,
        "collector_type": "LOCAL",
        "last_heartbeat_at": None,
    }
    connection = _Connection(row)
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)
    monkeypatch.setattr(monitoring_v1, "_probe_local_collector_runtime", lambda: {
        "runtime_status": "OFFLINE",
        "runtime_probe": "LOCAL_COMPONENT_HEALTH",
        "runtime_checked_at": "2026-10-18T14:00:00+00:00",
        "runtime_components": {"vmagent": "ONLINE", "snmp_exporter": "OFFLINE"},
    })

    result = monitoring_v1.test_collector("collector-local", _user={"role": "Operator"})

    assert result["status"] == "FAILED"
    assert result["runtime_status"] == "OFFLINE"
    assert result["runtime_components"]["snmp_exporter"] == "OFFLINE"
    assert connection.closed is True


def test_remote_status_check_does_not_pass_from_enabled_flag_alone(monkeypatch):
    row = {
        "id": "collector-remote",
        "code": "remote",
        "enabled": 1,
        "collector_type": "REMOTE",
        "last_heartbeat_at": None,
    }
    connection = _Connection(row)
    monkeypatch.setattr(monitoring_v1, "get_db_connection", lambda: connection)

    result = monitoring_v1.test_collector("collector-remote", _user={"role": "Operator"})

    assert result["status"] == "UNKNOWN"
    assert result["runtime_status"] == "UNKNOWN"
    assert result["runtime_probe"] == "HEARTBEAT_NOT_CONFIGURED"
    assert connection.closed is True
