from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
import uuid

from database import get_db_connection
from services import ip_locator_cli_service as cli_service
from services import ip_locator_service as legacy
from services.ip_locator_session_pool import IPLocatorSessionPool
from services.ip_locator_session_pool import LocatorSessionError
from services.ip_locator_task_service import create_locator_run, list_locator_run_tasks


def _device_id() -> str:
    return f"locator-cli-device-{uuid.uuid4().hex[:12]}"


def _insert_device(device_id: str) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO devices (id, hostname, tenant_id) VALUES (?, ?, ?)",
            (device_id, device_id, "tenant-default"),
        )
        conn.commit()
    finally:
        conn.close()


def test_100_concurrent_traces_share_one_postgres_cli_query(isolated_db, monkeypatch) -> None:
    device_id = _device_id()
    _insert_device(device_id)
    runs = [
        create_locator_run(
            owner_id=f"user-query-{index}",
            target_ip="192.0.2.221",
            tenant_id="tenant-default",
            scope_hash="scope-shared-cli",
            site_id="site-shared",
            authorization_scope_hash="auth-shared",
        )
        for index in range(100)
    ]
    monkeypatch.setattr(
        cli_service,
        "_CLI_TASK_COMPLETED_SHARE_SECONDS",
        30,
    )

    class FakeSessionPool:
        def run(self, device, callback, **_kwargs):
            return callback()

    monkeypatch.setattr(cli_service, "get_ip_locator_session_pool", lambda: FakeSessionPool())
    calls = 0
    calls_lock = threading.Lock()

    def callback():
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.2)
        return "Routing entry for 192.0.2.0/24\n directly connected, via Vlan10"

    task_context = {
        "tenant_id": "tenant-default",
        "scope_hash": "scope-shared-cli",
        "site_id": "site-shared",
        "vrf_name": "default",
        "authorization_scope_hash": "auth-shared",
        "target_ip": "192.0.2.221",
        "force_refresh": False,
        "target": {"command": "show ip route 192.0.2.221", "platform": "cisco_ios"},
    }

    with ThreadPoolExecutor(max_workers=32) as executor:
        futures = [
            executor.submit(
                cli_service.run_locator_cli_query,
                {"id": device_id, "ip_address": "192.0.2.10", "platform": "cisco_ios"},
                "route",
                callback,
                task_context={
                    **task_context,
                    "durable_run_id": run["id"],
                    "run_owner_id": run["owner_id"],
                },
                wait_seconds=20,
            )
            for run in runs
        ]
        results = [future.result(timeout=30) for future in futures]

    assert calls == 1
    assert len({item.task_id for item in results}) == 1
    assert len({item.collected_at for item in results}) == 1
    assert all(item.value == results[0].value for item in results)
    assert all(
        len(list_locator_run_tasks(run["id"], owner_id=run["owner_id"])) == 1
        for run in runs
    )


def test_session_pool_reuses_connection_and_releases_slot_after_idle(isolated_db, monkeypatch):
    device_id = _device_id()
    _insert_device(device_id)

    class FakeNetmikoClient:
        def __init__(self):
            self.commands = []
            self.closed = False

        def send_command(self, command, **_kwargs):
            self.commands.append(command)
            return f"output:{command}"

        def is_alive(self):
            return not self.closed

        def disconnect(self):
            self.closed = True

        def enable(self):
            return None

    clients = []
    connection_params = []

    def fake_connect(**params):
        connection_params.append(params)
        client = FakeNetmikoClient()
        clients.append(client)
        return client

    monkeypatch.setattr(legacy, "ConnectHandler", fake_connect)
    pool = IPLocatorSessionPool(idle_seconds=1, heartbeat_interval=0.5)
    device = {
        "id": device_id,
        "hostname": device_id,
        "ip_address": "192.0.2.30",
        "platform": "cisco_ios",
        "tenant_id": "tenant-default",
        "username": "test-user",
        "password": "test-password",
        "port": 22,
    }

    def send(command: str) -> str:
        return legacy._send_command(device, command, force_refresh=True)

    try:
        first = pool.run(device, lambda: send("show ip route 192.0.2.1"), task_id="task-a", run_id="run-a", wait_seconds=5)
        second = pool.run(device, lambda: send("show ip arp 192.0.2.1"), task_id="task-b", run_id="run-a", wait_seconds=5)
        assert first == "output:show ip route 192.0.2.1"
        assert second == "output:show ip arp 192.0.2.1"
        assert len(clients) == 1
        for key in ("timeout", "conn_timeout", "auth_timeout", "banner_timeout",
                    "blocking_timeout", "session_timeout"):
            assert 0 < connection_params[0][key] <= 5
        assert clients[0].commands == ["show ip route 192.0.2.1", "show ip arp 192.0.2.1"]

        time.sleep(1.25)
        third = pool.run(device, lambda: send("show mac address-table"), task_id="task-c", run_id="run-a", wait_seconds=5)
        assert third == "output:show mac address-table"
        assert len(clients) == 2
        assert clients[0].closed is True
        assert pool.snapshot()["active_sessions"] == 1
    finally:
        pool.close_all()

    conn = get_db_connection()
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM network_device_access_slots "
            "WHERE canonical_device_id = ? AND purpose = 'network_ssh' "
            "AND lease_until > CURRENT_TIMESTAMP",
            (device_id,),
        ).fetchone()[0]
        assert active == 0
    finally:
        conn.close()


def test_session_pool_retries_only_configured_ssh_fallback(isolated_db, monkeypatch):
    device_id = _device_id()
    _insert_device(device_id)

    class FakeNetmikoClient:
        def __init__(self):
            self.closed = False

        def send_command(self, command, **_kwargs):
            return f"output:{command}"

        def is_alive(self):
            return not self.closed

        def disconnect(self):
            self.closed = True

    attempted_users = []

    def fake_connect(**params):
        attempted_users.append(params["username"])
        if params["username"] == "primary-user":
            raise legacy.NetmikoAuthenticationException("authentication failed")
        return FakeNetmikoClient()

    monkeypatch.setattr(legacy, "ConnectHandler", fake_connect)
    pool = IPLocatorSessionPool(idle_seconds=30)
    device = {
        "id": device_id,
        "ip_address": "192.0.2.31",
        "platform": "h3c_comware",
        "tenant_id": "tenant-default",
        "_ssh_username": "primary-user",
        "_ssh_password": "primary-password",
        "_ssh_fallback_credentials": [("fallback-user", "fallback-password")],
        "port": 22,
    }
    try:
        output = pool.run(
            device,
            lambda: legacy._send_command(device, "display ip routing-table 192.0.2.1", force_refresh=True),
            task_id="task-fallback",
            run_id="run-fallback",
            wait_seconds=5,
        )
        assert output == "output:display ip routing-table 192.0.2.1"
        assert attempted_users == ["primary-user", "fallback-user"]
        assert "primary-password" not in str(pool.snapshot())
        assert "fallback-password" not in str(pool.snapshot())
    finally:
        pool.close_all()


def test_session_pool_rejects_unknown_platform_without_cisco_fallback(isolated_db, monkeypatch):
    import pytest

    device_id = _device_id()
    _insert_device(device_id)
    monkeypatch.setattr(
        legacy,
        "ConnectHandler",
        lambda **_params: (_ for _ in ()).throw(AssertionError("must reject before connecting")),
    )
    pool = IPLocatorSessionPool(idle_seconds=30)
    device = {
        "id": device_id,
        "ip_address": "192.0.2.32",
        "vendor": "Unknown",
        "platform": "mystery_os",
        "username": "test-user",
        "password": "test-password",
        "port": 22,
    }
    try:
        with pytest.raises(LocatorSessionError, match="registered SSH driver"):
            pool.run(device, lambda: "must not run", task_id="task-unknown", run_id="run-unknown", wait_seconds=2)
    finally:
        pool.close_all()
