import pytest
import database
from psycopg2.errors import ForeignKeyViolation

from services import background_monitor_service as monitor


class _Connection:
    def __init__(self, order, *, raw_error=False, commit_error=False):
        self.order = order
        self.raw_error = raw_error
        self.commit_error = commit_error

    def executemany(self, sql, rows):
        self.order.append("raw")
        if self.raw_error:
            raise RuntimeError("raw batch failed")

    def commit(self):
        self.order.append("commit")
        if self.commit_error:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.order.append("rollback")

    def close(self):
        self.order.append("close")


def _sample():
    return dict(
        device_id="device-1", profile_id="profile-1", config_hash="new-config",
        values={"Gi0/1": {"in_pkts": 9492296441}}, sampled_at="2026-10-02T15:00:00",
        device_uptime_cs=1000, raw_rows=[("raw-sample",)],
    )


def test_raw_batch_failure_does_not_advance_either_baseline(monkeypatch):
    previous = {"Gi0/1": {"in_pkts": 1}}
    monkeypatch.setattr(monitor, "prev_intf_octets", {"device-1": previous})
    monkeypatch.setattr(monitor, "prev_intf_config_hash", {"device-1": "old-config"})
    saved = []
    monkeypatch.setattr(monitor, "save_interface_counter_sample", lambda **kwargs: saved.append(kwargs))

    order = []
    monkeypatch.setattr(monitor, "get_db_connection", lambda: _Connection(order, raw_error=True))
    with pytest.raises(RuntimeError, match="raw batch failed"):
        monitor._store_interface_sample(**_sample())
    assert saved == []
    assert monitor.prev_intf_octets["device-1"] == previous
    assert monitor.prev_intf_config_hash["device-1"] == "old-config"
    assert order == ["raw", "rollback", "close"]


def test_raw_batch_is_stored_before_baseline(monkeypatch):
    order = []
    monkeypatch.setattr(monitor, "prev_intf_octets", {})
    monkeypatch.setattr(monitor, "prev_intf_config_hash", {})
    monkeypatch.setattr(monitor, "get_db_connection", lambda: _Connection(order))
    monkeypatch.setattr(monitor, "save_interface_counter_sample", lambda **kwargs: order.append("baseline"))
    sample = _sample()
    monitor._store_interface_sample(**sample)
    assert order == ["raw", "baseline", "commit", "close"]
    assert monitor.prev_intf_octets["device-1"] == sample["values"]
    assert monitor.prev_intf_config_hash["device-1"] == "new-config"


def test_commit_failure_does_not_advance_memory_baseline(monkeypatch):
    order = []
    monkeypatch.setattr(monitor, "prev_intf_octets", {})
    monkeypatch.setattr(monitor, "prev_intf_config_hash", {})
    monkeypatch.setattr(monitor, "get_db_connection", lambda: _Connection(order, commit_error=True))
    monkeypatch.setattr(monitor, "save_interface_counter_sample", lambda **kwargs: order.append("baseline"))
    with pytest.raises(RuntimeError, match="commit failed"):
        monitor._store_interface_sample(**_sample())
    assert monitor.prev_intf_octets == {}
    assert monitor.prev_intf_config_hash == {}
    assert order == ["raw", "baseline", "commit", "rollback", "close"]


def test_baseline_insert_failure_rolls_back_raw_batch_in_postgresql(isolated_db, monkeypatch):
    monkeypatch.setattr(monitor, "prev_intf_octets", {})
    monkeypatch.setattr(monitor, "prev_intf_config_hash", {})
    sample = _sample()
    sample["raw_rows"] = [(
        sample["sampled_at"], "device-1", "Gi0/1", "up", 1000,
        0, 0, 0, 0, 9492296441, 0,
        0, 0, 0, 0, 0, 0, 0, 0, "hc", "hc",
    )]
    # No device exists: the durable baseline FK fails after the raw insert.
    with pytest.raises(ForeignKeyViolation):
        monitor._store_interface_sample(**sample)
    with database.get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM interface_telemetry_raw").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM snmp_interface_counter_samples").fetchone()[0] == 0
    assert monitor.prev_intf_octets == {}
    assert monitor.prev_intf_config_hash == {}
