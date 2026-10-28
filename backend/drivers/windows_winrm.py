"""Small, deliberately constrained WinRM driver for Windows asset management.

The driver exposes only the operations required by the Windows management
API.  In particular, it does not provide a generic PowerShell execution
method: every command sent to a host is a module-owned, constant template.
``pywinrm`` remains an optional dependency and is imported only when a
connection is opened.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


class WindowsWinRMError(RuntimeError):
    """A safe, user-displayable WinRM failure."""


@dataclass(frozen=True)
class WinRMConnectionSettings:
    host: str
    port: int
    username: str
    password: str
    auth_mode: str = "ntlm"
    tls_mode: str = "verify_ca"
    cert_fingerprint: str = ""
    timeout_seconds: int = 20


_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,256}$")

# These strings are intentionally constants.  A caller cannot turn this
# driver into an arbitrary PowerShell endpoint by passing a script parameter.
_PS_TEST = (
    "$os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop; "
    "[pscustomobject]@{ Caption=$os.Caption; Version=$os.Version; "
    "BuildNumber=$os.BuildNumber } | ConvertTo-Json -Compress"
)
_PS_SUMMARY = (
    "$os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop; "
    "$cs = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop; "
    "$disk = Get-CimInstance Win32_LogicalDisk -Filter \"DriveType=3\" "
    "-ErrorAction SilentlyContinue | Measure-Object Size -Sum -ErrorAction SilentlyContinue; "
    "[pscustomobject]@{ Caption=$os.Caption; Version=$os.Version; "
    "BuildNumber=$os.BuildNumber; LastBootUpTime=$os.LastBootUpTime; "
    "TotalPhysicalMemory=$cs.TotalPhysicalMemory; "
    "NumberOfLogicalProcessors=$cs.NumberOfLogicalProcessors; "
    "DiskBytesTotal=$disk.Sum } | ConvertTo-Json -Compress"
)
_PS_SERVICES = (
    "Get-CimInstance Win32_Service -ErrorAction Stop | "
    "ForEach-Object { [pscustomobject]@{ "
    "Name=$_.Name; DisplayName=$_.DisplayName; State=([string]$_.State); "
    "StartMode=([string]$_.StartMode); StartName=$_.StartName } } | "
    "ConvertTo-Json -Compress"
)

# WinRM may use the Windows console code page for PowerShell 5.1 output.  Set
# both encodings inside the remote process before emitting JSON so non-ASCII
# host and service names survive the WS-Man response unchanged.
_PS_UTF8_SETUP = (
    "$utf8 = [System.Text.UTF8Encoding]::new($false); "
    "[Console]::OutputEncoding = $utf8; $OutputEncoding = $utf8; "
)

_SERVICE_STATUS_NAMES = {
    1: "Stopped",
    2: "StartPending",
    3: "StopPending",
    4: "Running",
    5: "ContinuePending",
    6: "PausePending",
    7: "Paused",
}
_SERVICE_START_TYPE_NAMES = {
    0: "Boot",
    1: "System",
    2: "Automatic",
    3: "Manual",
    4: "Disabled",
    5: "Unknown",
}


def _normalise_fingerprint(value: str) -> str:
    normalised = str(value or "").strip().lower()
    if normalised.startswith("sha256:"):
        normalised = normalised[7:]
    return re.sub(r"[^0-9a-f]", "", normalised)


def verify_certificate_fingerprint(
    host: str,
    port: int,
    expected: str,
    *,
    timeout: int = 10,
    socket_factory: Callable[..., Any] | None = None,
) -> None:
    """Perform a pre-session SHA-256 certificate pin check.

    The unverified context is intentional here: a pinned self-signed
    certificate is valid for ``pin_fingerprint`` mode.  The exact certificate
    presented by the TLS handshake is still checked before pywinrm is given a
    chance to authenticate.
    """

    expected_hex = _normalise_fingerprint(expected)
    if len(expected_hex) != 64:
        raise WindowsWinRMError("A SHA-256 certificate fingerprint is required")
    factory = socket_factory or socket.create_connection
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        raw = factory((host, int(port)), timeout=timeout)
        with context.wrap_socket(raw, server_hostname=host) as wrapped:
            certificate = wrapped.getpeercert(binary_form=True)
    except WindowsWinRMError:
        raise
    except Exception as exc:  # noqa: BLE001 - avoid leaking socket details
        raise WindowsWinRMError("Unable to inspect the Windows TLS certificate") from exc
    actual = hashlib.sha256(certificate or b"").hexdigest()
    if not actual or not hmac.compare_digest(actual, expected_hex):
        raise WindowsWinRMError("Windows TLS certificate fingerprint does not match")


class _FingerprintAdapter:
    """Requests adapter that makes urllib3 enforce the certificate pin.

    ``pywinrm`` owns the requests session, so a pre-flight socket check alone
    is insufficient: a certificate can change between that check and the
    authenticated request.  Passing ``assert_fingerprint`` to urllib3's pool
    binds the check to every actual HTTPS connection used by pywinrm.
    """

    def __new__(cls, fingerprint: str) -> Any:
        try:
            from requests.adapters import HTTPAdapter
        except ImportError as exc:  # pragma: no cover - pywinrm requires requests
            raise WindowsWinRMError("Certificate pinning requires requests and urllib3") from exc

        class FingerprintHTTPAdapter(HTTPAdapter):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._assert_fingerprint = fingerprint
                super().__init__(*args, **kwargs)

            def init_poolmanager(
                self,
                connections: int,
                maxsize: int,
                block: bool = False,
                **pool_kwargs: Any,
            ) -> None:
                pool_kwargs["assert_fingerprint"] = self._assert_fingerprint
                super().init_poolmanager(connections, maxsize, block, **pool_kwargs)

            def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
                proxy_kwargs["assert_fingerprint"] = self._assert_fingerprint
                return super().proxy_manager_for(proxy, **proxy_kwargs)

        return FingerprintHTTPAdapter()


def _bind_fingerprint_to_session(session: Any, fingerprint: str) -> None:
    """Mount the pinning adapter on pywinrm's real requests session.

    Failing closed is important here.  If a custom session does not expose
    pywinrm's protocol transport, the independent pre-check must not be
    mistaken for protection of the subsequent authenticated connection.
    """

    protocol = getattr(session, "protocol", None)
    transport = getattr(protocol, "transport", None)
    if transport is None:
        raise WindowsWinRMError("Unable to bind the Windows TLS certificate pin")
    build_session = getattr(transport, "build_session", None)
    if callable(build_session):
        requests_session = build_session()
    else:
        requests_session = getattr(transport, "session", None)
    mount = getattr(requests_session, "mount", None)
    if not callable(mount):
        raise WindowsWinRMError("Unable to bind the Windows TLS certificate pin")
    mount("https://", _FingerprintAdapter(fingerprint))


class WindowsWinRMDriver:
    """WinRM HTTPS driver with fixed, read-only and service-action methods."""

    def __init__(
        self,
        settings: WinRMConnectionSettings,
        *,
        session_factory: Callable[..., Any] | None = None,
        socket_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.settings = settings
        self._session_factory = session_factory
        self._socket_factory = socket_factory
        self._session: Any | None = None

    def _open_session(self) -> Any:
        if self._session is not None:
            return self._session
        s = self.settings
        if not s.host or not s.username or not s.password:
            raise WindowsWinRMError("Windows WinRM credentials are incomplete")
        if str(s.tls_mode).lower() not in {"verify_ca", "pin_fingerprint", "insecure_lab"}:
            raise WindowsWinRMError("Unsupported Windows TLS mode")
        if str(s.auth_mode).lower() not in {"ntlm", "basic"}:
            raise WindowsWinRMError("Unsupported Windows authentication mode")
        if str(s.tls_mode).lower() == "pin_fingerprint":
            verify_certificate_fingerprint(
                s.host,
                s.port,
                s.cert_fingerprint,
                timeout=s.timeout_seconds,
                socket_factory=self._socket_factory,
            )
        try:
            factory = self._session_factory
            if factory is None:
                try:
                    import winrm  # type: ignore[import-not-found]
                except ImportError as exc:
                    raise WindowsWinRMError(
                        "pywinrm is not installed; install it to manage Windows assets"
                    ) from exc
                factory = winrm.Session
            tls_mode = str(s.tls_mode).lower()
            # pywinrm's plaintext transport still uses the HTTPS endpoint and
            # is the supported Basic-auth transport; NTLM has its own HTTPS
            # transport.  CA validation is delegated to pywinrm.
            transport = "ntlm" if str(s.auth_mode).lower() == "ntlm" else "plaintext"
            cert_validation = "validate" if tls_mode == "verify_ca" else "ignore"
            endpoint = f"https://{s.host}:{int(s.port)}/wsman"
            session = factory(
                endpoint,
                auth=(s.username, s.password),
                transport=transport,
                server_cert_validation=cert_validation,
                # Keep channel binding enabled for NTLM.  This must remain
                # true even when a certificate pin is also configured.
                send_cbt=str(s.auth_mode).lower() == "ntlm",
                operation_timeout_sec=max(1, int(s.timeout_seconds)),
            )
            if tls_mode == "pin_fingerprint":
                _bind_fingerprint_to_session(session, _normalise_fingerprint(s.cert_fingerprint))
            self._session = session
            return self._session
        except WindowsWinRMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise WindowsWinRMError("Unable to open the Windows WinRM HTTPS session") from exc

    @staticmethod
    def _decode_result(result: Any) -> Any:
        status = getattr(result, "status_code", 0)
        stdout = getattr(result, "std_out", b"")
        stderr = getattr(result, "std_err", b"")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8-sig", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8-sig", errors="replace")
        if status not in (None, 0):
            raise WindowsWinRMError("Windows command failed")
        if stderr and not str(stdout).strip():
            raise WindowsWinRMError("Windows command returned an error")
        return str(stdout or "").strip()

    def _run_json(self, script: str) -> Any:
        result = self._open_session().run_ps(_PS_UTF8_SETUP + script)
        output = self._decode_result(result)
        if not output:
            return {}
        try:
            return json.loads(output)
        except (TypeError, ValueError) as exc:
            raise WindowsWinRMError("Windows returned invalid JSON") from exc

    def test_connection(self) -> dict[str, Any]:
        data = self._run_json(_PS_TEST)
        return {"reachable": True, "os": data if isinstance(data, dict) else {}}

    def get_summary(self) -> dict[str, Any]:
        data = self._run_json(_PS_SUMMARY)
        return data if isinstance(data, dict) else {}

    def list_services(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        raw = self._run_json(_PS_SERVICES)
        values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        needle = str(search or "").strip().casefold()
        wanted_status = str(status or "").strip().casefold()
        items = []
        for value in values:
            if not isinstance(value, dict):
                continue
            item = self._normalise_service_item(value)
            if needle and needle not in f"{item.get('Name', '')} {item.get('DisplayName', '')}".casefold():
                continue
            if wanted_status and str(item.get("State") or "").casefold() != wanted_status:
                continue
            items.append(item)
        items.sort(key=lambda item: str(item.get("DisplayName") or item.get("Name") or "").casefold())
        safe_page = max(1, int(page))
        safe_size = min(200, max(1, int(page_size)))
        start = (safe_page - 1) * safe_size
        return {
            "items": items[start : start + safe_size],
            "total": len(items),
            "page": safe_page,
            "page_size": safe_size,
        }

    def get_service(self, service_name: str) -> dict[str, Any] | None:
        if not _SERVICE_NAME_RE.fullmatch(str(service_name or "")):
            raise WindowsWinRMError("Invalid Windows service name")
        # Do not route this lookup through the paged list endpoint: a valid
        # service can sort after the first 200 records.  The service inventory
        # is already bounded by the host and is fetched once for an exact name
        # match.
        raw = self._run_json(_PS_SERVICES)
        values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        for value in values:
            if not isinstance(value, dict):
                continue
            item = self._normalise_service_item(value)
            if str(item.get("Name") or "").casefold() == service_name.casefold():
                return item
        return None

    @staticmethod
    def _normalise_service_item(value: dict[str, Any]) -> dict[str, Any]:
        item = {str(k): v for k, v in value.items()}
        for key, names in (("State", _SERVICE_STATUS_NAMES), ("Status", _SERVICE_STATUS_NAMES), ("StartMode", _SERVICE_START_TYPE_NAMES), ("StartType", _SERVICE_START_TYPE_NAMES)):
            raw = item.get(key)
            try:
                numeric = int(raw) if isinstance(raw, (int, str)) and str(raw).strip().isdigit() else None
            except (TypeError, ValueError):
                numeric = None
            if numeric is not None and numeric in names:
                item[key] = names[numeric]
            elif raw is not None:
                item[key] = str(raw)
        return item

    def action_service(self, service_name: str, action: str) -> dict[str, Any]:
        if not _SERVICE_NAME_RE.fullmatch(str(service_name or "")):
            raise WindowsWinRMError("Invalid Windows service name")
        action = str(action or "").lower()
        if action not in {"start", "stop", "restart"}:
            raise WindowsWinRMError("Unsupported Windows service action")
        # Quote only a validated service identifier.  This is still a fixed
        # action template; arbitrary script text never crosses this boundary.
        quoted_name = str(service_name).replace("'", "''")
        command = {"start": "Start-Service", "stop": "Stop-Service", "restart": "Restart-Service"}[action]
        desired_state = "Running" if action in {"start", "restart"} else "Stopped"
        script = (
            f"$svc = Get-Service -Name '{quoted_name}' -ErrorAction Stop; "
            f"{command} -InputObject $svc -ErrorAction Stop; "
            f"$deadline = [DateTime]::UtcNow.AddSeconds(30); "
            f"do {{ $svc.Refresh(); if ([string]$svc.Status -eq '{desired_state}') {{ break }}; "
            "Start-Sleep -Milliseconds 250 } while ([DateTime]::UtcNow -lt $deadline); "
            "$svc.Refresh(); "
            f"if ([string]$svc.Status -ne '{desired_state}') {{ throw \"Service did not reach {desired_state} state\" }}; "
            "[pscustomobject]@{ Name=$svc.Name; DisplayName=$svc.DisplayName; "
            "Status=([string]$svc.Status); StartType=([string]$svc.StartType) } | "
            "ConvertTo-Json -Compress"
        )
        data = self._run_json(script)
        return self._normalise_service_item(data) if isinstance(data, dict) else {}
