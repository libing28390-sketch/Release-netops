"""Business rules for Windows WinRM HTTPS asset management."""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.rbac import enforce_resource_scope
from database import get_db_connection
from drivers.windows_winrm import (
    WindowsWinRMDriver,
    WindowsWinRMError,
    WinRMConnectionSettings,
)
from services.audit_service import log_audit_event
from services.vault_service import resolve_device_credentials

logger = logging.getLogger(__name__)


class WindowsManagementError(RuntimeError):
    """A business validation or downstream Windows-management failure."""

    def __init__(self, message: str, *, status_code: int = 400, code: str = "WINDOWS_MANAGEMENT_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


_CRITICAL_SERVICES = {
    "eventlog",
    "lanmanserver",
    "lanmanworkstation",
    "rpcss",
    "rpceptmapper",
    "dcomlaunch",
    "plugplay",
    "samss",
    "wininit",
    "winmgmt",
    "winrm",
    "termservice",
}


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _is_windows_asset(asset: dict[str, Any]) -> bool:
    values = {
        str(asset.get("os_type") or "").strip().lower(),
        str(asset.get("platform") or "").strip().lower(),
        str(asset.get("asset_type") or "").strip().lower(),
    }
    return any("windows" in value for value in values) or bool(
        values & {"windows", "windows_server", "windows-server"}
    )


def _tenant_id(asset: dict[str, Any]) -> str:
    return str(asset.get("tenant_id") or asset.get("site_tenant_id") or "tenant-default").strip()


class WindowsManagementService:
    """Resolve a scoped asset and delegate only approved operations to a driver."""

    def __init__(
        self,
        *,
        driver_factory: Callable[[WinRMConnectionSettings], Any] | None = None,
        credential_resolver: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        audit_logger: Callable[..., Any] | None = None,
    ) -> None:
        self.driver_factory = driver_factory or (lambda settings: WindowsWinRMDriver(settings))
        self.credential_resolver = credential_resolver or resolve_device_credentials
        self.audit_logger = audit_logger or log_audit_event

    def _load_asset(self, asset_id: str, user: dict[str, Any], action: str = "view") -> dict[str, Any]:
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT pa.*, s.tenant_id AS site_tenant_id
                     FROM physical_assets pa
                     LEFT JOIN sites s ON s.id = pa.site_id
                    WHERE pa.id = ?""",
                (asset_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise WindowsManagementError("Asset not found", status_code=404, code="ASSET_NOT_FOUND")
        asset = dict(row)
        tenant_id = _tenant_id(asset)
        user_tenant = str(user.get("tenant_id") or "").strip()
        if user_tenant and tenant_id and user_tenant != tenant_id and user.get("role") != "Administrator":
            raise WindowsManagementError("Asset is outside the user's tenant", status_code=403, code="TENANT_SCOPE_DENIED")
        try:
            enforce_resource_scope(user, "pam", action, tenant_id=tenant_id, site_id=str(asset.get("site_id") or ""))
        except Exception as exc:
            # Preserve the project's structured HTTP exception from RBAC while
            # keeping unit tests and service callers independent of FastAPI.
            if getattr(exc, "status_code", None) == 403:
                raise WindowsManagementError("Insufficient permission for this asset", status_code=403, code="RESOURCE_SCOPE_DENIED") from exc
            raise
        if not _is_windows_asset(asset):
            raise WindowsManagementError("Asset is not a Windows machine", status_code=409, code="NOT_WINDOWS_ASSET")
        if not _truthy(asset.get("winrm_enabled")):
            raise WindowsManagementError("WinRM HTTPS is disabled for this asset", status_code=409, code="WINRM_DISABLED")
        return asset

    def _driver_for(self, asset: dict[str, Any]) -> Any:
        host = str(asset.get("management_ip") or asset.get("ip_address") or "").strip()
        if not host:
            raise WindowsManagementError("Asset has no management address", status_code=422, code="MISSING_MANAGEMENT_IP")
        try:
            port = int(asset.get("winrm_port") or 5986)
        except (TypeError, ValueError) as exc:
            raise WindowsManagementError("Invalid WinRM HTTPS port", status_code=422, code="INVALID_WINRM_PORT") from exc
        if not 1 <= port <= 65535:
            raise WindowsManagementError("Invalid WinRM HTTPS port", status_code=422, code="INVALID_WINRM_PORT")
        auth_mode = str(asset.get("winrm_auth_mode") or "ntlm").strip().lower()
        tls_mode = str(asset.get("winrm_tls_mode") or "verify_ca").strip().lower()
        if auth_mode not in {"ntlm", "basic"}:
            raise WindowsManagementError("Unsupported WinRM authentication mode", status_code=422, code="INVALID_WINRM_AUTH")
        if tls_mode not in {"verify_ca", "pin_fingerprint", "insecure_lab"}:
            raise WindowsManagementError("Unsupported WinRM TLS mode", status_code=422, code="INVALID_WINRM_TLS")
        try:
            creds = self.credential_resolver(asset) or {}
        except Exception as exc:  # noqa: BLE001 - do not expose resolver details
            raise WindowsManagementError("Unable to resolve Windows credentials", status_code=502, code="CREDENTIAL_RESOLUTION_FAILED") from exc
        username = str(
            creds.get("normal_username")
            or creds.get("username")
            or creds.get("admin_username")
            or ""
        ).strip()
        password = str(
            creds.get("normal_password")
            or creds.get("password")
            or creds.get("admin_password")
            or ""
        )
        if not username or not password:
            raise WindowsManagementError("Windows credentials are not configured", status_code=422, code="MISSING_WINDOWS_CREDENTIALS")
        return self.driver_factory(
            WinRMConnectionSettings(
                host=host,
                port=port,
                username=username,
                password=password,
                auth_mode=auth_mode,
                tls_mode=tls_mode,
                cert_fingerprint=str(asset.get("winrm_cert_fingerprint") or ""),
            )
        )

    def _audit(self, *, user: dict[str, Any], asset: dict[str, Any], status: str, summary: str, details: dict[str, Any] | None = None, severity: str = "info") -> None:
        try:
            self.audit_logger(
                event_type="windows.management",
                category="pam",
                severity=severity,
                status=status,
                summary=summary,
                actor_id=str(user.get("id") or user.get("user_id") or ""),
                actor_username=str(user.get("username") or "system"),
                actor_role=str(user.get("role") or ""),
                target_type="physical_asset",
                target_id=str(asset.get("id") or ""),
                target_name=str(asset.get("hostname") or asset.get("management_ip") or ""),
                details=details or {},
            )
        except Exception:  # auditing must not hide the operation result
            logger.warning("Unable to write Windows management audit event", exc_info=True)

    @staticmethod
    def _driver_error(exc: Exception) -> WindowsManagementError:
        return WindowsManagementError("Windows WinRM operation failed", status_code=502, code="WINRM_OPERATION_FAILED")

    def test_connection(self, asset_id: str, user: dict[str, Any]) -> dict[str, Any]:
        asset = self._load_asset(asset_id, user, "view")
        try:
            result = self._driver_for(asset).test_connection()
            payload = {"asset_id": asset_id, "reachable": True, **result}
            self._audit(user=user, asset=asset, status="success", summary="Windows WinRM connection test succeeded")
            return payload
        except Exception as exc:  # noqa: BLE001
            self._audit(user=user, asset=asset, status="failed", severity="warning", summary="Windows WinRM connection test failed")
            if isinstance(exc, WindowsManagementError):
                raise
            raise self._driver_error(exc) from exc

    def get_summary(self, asset_id: str, user: dict[str, Any]) -> dict[str, Any]:
        asset = self._load_asset(asset_id, user, "view")
        try:
            summary = self._driver_for(asset).get_summary()
            return {"asset_id": asset_id, "hostname": asset.get("hostname") or "", "summary": summary}
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, WindowsManagementError):
                raise
            raise self._driver_error(exc) from exc

    def list_services(self, asset_id: str, user: dict[str, Any], *, page: int = 1, page_size: int = 20, search: str = "", status: str = "") -> dict[str, Any]:
        asset = self._load_asset(asset_id, user, "view")
        try:
            result = self._driver_for(asset).list_services(page=page, page_size=page_size, search=search, status=status)
            return {"asset_id": asset_id, **result}
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, WindowsManagementError):
                raise
            raise self._driver_error(exc) from exc

    def action_service(self, asset_id: str, service_name: str, action: str, *, confirm: bool, reason: str, user: dict[str, Any]) -> dict[str, Any]:
        asset = self._load_asset(asset_id, user, "create_change")
        normalized_action = str(action or "").lower()
        if normalized_action not in {"start", "stop", "restart"}:
            raise WindowsManagementError("Unsupported Windows service action", status_code=422, code="INVALID_SERVICE_ACTION")
        if not confirm:
            raise WindowsManagementError("Service action requires explicit confirmation", status_code=422, code="CONFIRMATION_REQUIRED")
        if not str(reason or "").strip():
            raise WindowsManagementError("A reason is required for a service change", status_code=422, code="REASON_REQUIRED")
        if normalized_action in {"stop", "restart"} and str(service_name or "").casefold() in _CRITICAL_SERVICES:
            raise WindowsManagementError("Stopping or restarting a critical Windows service is not allowed", status_code=409, code="CRITICAL_SERVICE_PROTECTED")
        driver = self._driver_for(asset)
        before: dict[str, Any] | None = None
        try:
            before = driver.get_service(service_name)
            if before is None:
                raise WindowsManagementError("Windows service not found", status_code=404, code="SERVICE_NOT_FOUND")
            after = driver.action_service(service_name, normalized_action)
            self._audit(
                user=user,
                asset=asset,
                status="success",
                severity="warning",
                summary=f"Windows service {normalized_action} completed",
                details={"service_name": service_name, "action": normalized_action, "reason": str(reason).strip()},
            )
            return {"asset_id": asset_id, "service_name": service_name, "action": normalized_action, "before": before, "after": after}
        except Exception as exc:  # noqa: BLE001
            self._audit(
                user=user,
                asset=asset,
                status="failed",
                severity="warning",
                summary=f"Windows service {normalized_action} failed",
                details={"service_name": service_name, "action": normalized_action, "reason": str(reason).strip()},
            )
            if isinstance(exc, WindowsManagementError):
                raise
            raise self._driver_error(exc) from exc


service = WindowsManagementService()
