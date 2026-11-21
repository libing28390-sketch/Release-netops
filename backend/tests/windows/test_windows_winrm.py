import json

import pytest

from drivers.windows_winrm import (
    WindowsWinRMDriver,
    WindowsWinRMError,
    WinRMConnectionSettings,
)
from services import windows_management_service as module
from services.windows_management_service import WindowsManagementError, WindowsManagementService


class FakeResult:
    status_code = 0

    def __init__(self, payload):
        self.std_out = json.dumps(payload).encode()
        self.std_err = b""


class FakeSession:
    def __init__(self):
        self.scripts = []

    def run_ps(self, script):
        self.scripts.append(script)
        if "Win32_Service" in script:
            return FakeResult([
                {"Name": "Spooler", "DisplayName": "Print Spooler", "State": "Running"},
                {"Name": "W32Time", "DisplayName": "Windows Time", "State": "Stopped"},
            ])
        return FakeResult({"Caption": "Microsoft Windows Server", "Version": "10.0"})


def test_driver_uses_https_and_fixed_templates():
    session = FakeSession()
    driver = WindowsWinRMDriver(
        WinRMConnectionSettings("win01.example", 5986, "operator", "secret"),
        session_factory=lambda endpoint, **kwargs: session,
    )

    assert driver.test_connection()["reachable"] is True
    services = driver.list_services(search="spool", page=1, page_size=20)
    assert services["total"] == 1
    assert services["items"][0]["Name"] == "Spooler"
    assert session.scripts and "ConvertTo-Json" in session.scripts[-1]
    assert all("https://win01.example:5986/wsman" not in script for script in session.scripts)


def test_driver_rejects_bad_pinned_fingerprint_before_session():
    called = []
    driver = WindowsWinRMDriver(
        WinRMConnectionSettings(
            "win01.example", 5986, "operator", "secret", tls_mode="pin_fingerprint", cert_fingerprint="bad"
        ),
        session_factory=lambda *args, **kwargs: called.append(True),
    )
    with pytest.raises(WindowsWinRMError, match="fingerprint"):
        driver.test_connection()
    assert called == []


class FakeConnection:
    def execute(self, *_args):
        return FakeCursor(FakeRow({
            "id": "asset-1",
            "hostname": "win01",
            "management_ip": "192.0.2.10",
            "asset_type": "server",
            "platform": "windows",
            "site_id": "site-1",
            "site_tenant_id": "tenant-a",
            "winrm_enabled": True,
            "winrm_port": 5986,
            "winrm_auth_mode": "ntlm",
            "winrm_tls_mode": "insecure_lab",
        }))

    def close(self):
        pass


class FakeRow(dict):
    pass


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeDriver:
    def test_connection(self):
        return {"reachable": True, "os": {"Caption": "Windows"}}

    def get_summary(self):
        return {"Caption": "Windows"}

    def list_services(self, **kwargs):
        return {"items": [], "total": 0, "page": kwargs["page"], "page_size": kwargs["page_size"]}

    def get_service(self, name):
        return {"Name": name, "State": "Running"}

    def action_service(self, name, action):
        return {"Name": name, "Status": "Stopped" if action == "stop" else "Running"}


def test_service_enforces_confirmation_and_audits(monkeypatch):
    monkeypatch.setattr(module, "get_db_connection", lambda: FakeConnection())
    monkeypatch.setattr(module, "enforce_resource_scope", lambda *args, **kwargs: None)
    audit = []
    service = WindowsManagementService(
        driver_factory=lambda settings: FakeDriver(),
        credential_resolver=lambda asset: {"username": "operator", "password": "secret"},
        audit_logger=lambda **kwargs: audit.append(kwargs),
    )
    user = {"id": "u1", "username": "operator", "role": "Operator", "tenant_id": "tenant-a"}
    with pytest.raises(WindowsManagementError, match="confirmation"):
        service.action_service("asset-1", "Spooler", "stop", confirm=False, reason="maintenance", user=user)
    result = service.action_service("asset-1", "Spooler", "stop", confirm=True, reason="maintenance", user=user)
    assert result["after"]["Status"] == "Stopped"
    assert audit[-1]["status"] == "success"
