from __future__ import annotations

from types import SimpleNamespace

from services.platform_registry_service import PlatformActionSession, execute_platform_action


def test_platform_action_session_reuses_one_driver_for_multiple_read_actions(isolated_db):
    conn = isolated_db["module"].get_db_connection()
    try:
        conn.execute(
            """INSERT INTO devices
               (id, hostname, ip_address, platform, status, username, password,
                connection_method, platform_profile_id, platform_source, tenant_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "session-device-1",
                "session-edge-1",
                "192.0.2.41",
                "cisco_ios",
                "active",
                "u",
                "p",
                "mock",
                "system-profile-cisco_ios",
                "SYSTEM",
                "tenant-1",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    class FakeDriver:
        instances = []

        def __init__(self, *_args, **_kwargs):
            self.commands = []
            self.entered = False
            self.exited = False
            self.__class__.instances.append(self)

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, *_args):
            self.exited = True
            return None

        def send_command(self, command):
            self.commands.append(command)
            return SimpleNamespace(success=True, output="", error=None)

    class FakeFactory:
        @classmethod
        def get_driver(cls, *_args, **_kwargs):
            return FakeDriver()

    user = {"id": "admin-1", "username": "admin", "role": "Administrator", "tenant_id": "tenant-1"}
    session = PlatformActionSession("session-device-1", user, driver_factory=FakeFactory)
    with session:
        clock = execute_platform_action(
            "session-device-1",
            "get_clock",
            user=user,
            driver_factory=FakeFactory,
            _session=session,
        )
        config = execute_platform_action(
            "session-device-1",
            "get_running_config",
            user=user,
            driver_factory=FakeFactory,
            _session=session,
        )

    assert clock["success"] is True
    assert config["success"] is True
    assert len(FakeDriver.instances) == 1
    assert FakeDriver.instances[0].commands == ["show clock", "show running-config"]
    assert FakeDriver.instances[0].entered is True
    assert FakeDriver.instances[0].exited is True
