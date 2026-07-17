from engine.pool import ConnectionPool


class _Connection:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


def _device(name: str):
    return {
        "ip_address": f"192.0.2.{name}",
        "ssh_port": 22,
        "username": "normal",
    }


def test_pool_reclaims_idle_sessions(monkeypatch):
    pool = ConnectionPool()
    pool.close_all()
    now = {"value": 100.0}
    monkeypatch.setattr("engine.pool.time.monotonic", lambda: now["value"])
    monkeypatch.setattr("core.config.settings.NETWORK_POOL_IDLE_SECONDS", 60)

    conn = _Connection()
    pool.set_connection(_device("10"), conn)
    now["value"] += 61

    assert pool.cleanup() == 1
    assert conn.closed == 1
    assert pool.snapshot()["active"] == 0


def test_pool_enforces_process_limit(monkeypatch):
    pool = ConnectionPool()
    pool.close_all()
    monkeypatch.setattr("core.config.settings.NETWORK_POOL_MAX_SIZE", 1)
    monkeypatch.setattr("engine.pool.time.monotonic", lambda: 100.0)

    first = _Connection()
    second = _Connection()
    pool.set_connection(_device("11"), first)
    pool.set_connection(_device("12"), second)

    assert pool.snapshot()["active"] == 1
    assert first.closed == 1
    assert second.closed == 0
    pool.close_all()
