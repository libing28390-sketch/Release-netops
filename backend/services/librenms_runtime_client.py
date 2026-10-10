"""Small, read-only HTTP client for LibreNMS native runtime API v0.

This module deliberately contains no SNMP, MIB, vendor, unit-conversion, or
polling logic. LibreNMS remains the only component that discovers and samples
hardware; this client only reads its versioned API output.
"""

from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from core.config import settings


_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_HEALTH_TYPES = {"processor", "mempool", "storage"}
_ADD_DEVICE_SNMP_FIELDS = {
    "snmpver",
    "community",
    "authlevel",
    "authname",
    "authpass",
    "authalgo",
    "cryptopass",
    "cryptoalgo",
}
_ADD_DEVICE_RESPONSE_FIELDS = {
    "device_id",
    "hostname",
    "display",
    "os",
    "version",
    "hardware",
    "sysObjectID",
    "status",
    "disabled",
    "ignore",
    "last_discovered",
    "last_polled",
}


class LibreNMSAPIError(RuntimeError):
    """Sanitized API failure; never includes request headers or response body."""

    def __init__(self, code: str, *, http_status: int | None = None) -> None:
        self.code = code
        self.http_status = http_status
        super().__init__(code)


def _host_key(host: str) -> str:
    normalized = host.rstrip(".").casefold()
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return normalized


def _allowed_host_matches(host: str, port: int | None, allowlist: str) -> bool:
    target_host = _host_key(host)
    for raw_entry in str(allowlist or "").split(","):
        entry = raw_entry.strip()
        if not entry or any(ord(character) < 33 for character in entry):
            continue
        try:
            parsed = urlsplit(f"//{entry}")
            allowed_host = parsed.hostname or ""
            allowed_port = parsed.port
        except ValueError:
            continue
        # Allowlist entries are authorities only. Ignore malformed entries
        # instead of accidentally accepting a host with credentials or a path.
        if (
            not allowed_host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            continue
        if _host_key(allowed_host) == target_host and (allowed_port is None or allowed_port == port):
            return True
    return False


def normalize_librenms_base_url(value: str, *, allowed_hosts: str | None = None) -> str:
    """Validate an administrator-configured API origin against host allowlist."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise LibreNMSAPIError("invalid_base_url") from exc

    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not host
        or host != host.strip()
        or any(ord(character) < 33 for character in parsed.netloc)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "?" in raw
        or "#" in raw
    ):
        raise LibreNMSAPIError("invalid_base_url")

    configured_allowlist = settings.LIBRENMS_ALLOWED_HOSTS if allowed_hosts is None else allowed_hosts
    if not _allowed_host_matches(host, port, configured_allowlist):
        raise LibreNMSAPIError("host_not_allowed")

    path = parsed.path.rstrip("/")
    if "/api/" in path.casefold() or path.casefold().endswith("/api"):
        raise LibreNMSAPIError("invalid_base_url")
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc, path, "", "")).rstrip("/")


def _records(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    """Read a documented collection field, preserving valid empty collections."""
    if key not in payload:
        raise LibreNMSAPIError("unexpected_payload")
    rows = payload[key]
    if not isinstance(rows, list):
        raise LibreNMSAPIError("unexpected_payload")
    if any(not isinstance(row, Mapping) for row in rows):
        raise LibreNMSAPIError("unexpected_payload")
    return [dict(row) for row in rows]


def _sensor_is_deleted(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


@dataclass(frozen=True)
class LibreNMSDeviceSnapshot:
    """Native current readings and separate health graph metadata.

    ``health_graphs`` only reports which graphs LibreNMS can expose; those
    rows are metadata and must not be displayed or stored as sampled values.
    """

    device: dict[str, Any]
    sensors: list[dict[str, Any]]
    wireless_sensors: list[dict[str, Any]]
    transceivers: list[dict[str, Any]]
    processor_sensors: list[dict[str, Any]]
    memory_pools: list[dict[str, Any]]
    health_graphs: dict[str, list[dict[str, Any]]]


class LibreNMSRuntimeClient:
    """Authenticated read-only client for LibreNMS API v0.

    One ``httpx.AsyncClient`` is reused for the object's lifetime. Callers may
    use it as an async context manager or call :meth:`aclose` explicitly.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        secret = str(token or "").strip()
        if not secret:
            raise LibreNMSAPIError("missing_api_token")
        if not secret.isascii() or any(ord(character) < 33 or ord(character) > 126 for character in secret):
            raise LibreNMSAPIError("invalid_api_token")

        self.base_url = normalize_librenms_base_url(base_url)
        self._token = secret
        timeout_value = settings.LIBRENMS_API_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        try:
            self._timeout = float(timeout_value)
        except (TypeError, ValueError) as exc:
            raise LibreNMSAPIError("invalid_timeout") from exc
        if not math.isfinite(self._timeout) or self._timeout <= 0:
            raise LibreNMSAPIError("invalid_timeout")

        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._closed = False

    async def __aenter__(self) -> "LibreNMSRuntimeClient":
        if self._closed:
            raise LibreNMSAPIError("client_closed")
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the reused transport and prevent accidental use after close."""
        if self._closed:
            return
        self._closed = True
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._closed:
            raise LibreNMSAPIError("client_closed")
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                verify=True,
                follow_redirects=False,
                trust_env=False,
                transport=self._transport,
            )
        return self._http

    async def _request_json_payload(
        self,
        method: str,
        resource_path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if not resource_path.startswith("/api/v0/") or ".." in resource_path.split("/"):
            raise LibreNMSAPIError("invalid_api_path")

        http = self._get_http_client()
        url = f"{self.base_url}{resource_path}"
        try:
            async with http.stream(
                method,
                url,
                params=dict(params or {}),
                json=dict(json_payload) if json_payload is not None else None,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            ) as response:
                if response.status_code == 401:
                    raise LibreNMSAPIError("unauthorized", http_status=response.status_code)
                if response.status_code == 403:
                    raise LibreNMSAPIError("forbidden", http_status=response.status_code)
                if response.status_code >= 300:
                    raise LibreNMSAPIError("http_error", http_status=response.status_code)

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise LibreNMSAPIError("response_too_large")
        except LibreNMSAPIError:
            raise
        except httpx.TimeoutException as exc:
            raise LibreNMSAPIError("timeout") from exc
        except httpx.TransportError as exc:
            raise LibreNMSAPIError("unreachable") from exc

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            raise LibreNMSAPIError("invalid_json") from exc
        if isinstance(payload, dict):
            if str(payload.get("status") or "").casefold() == "error":
                raise LibreNMSAPIError("upstream_error")
            return payload
        if isinstance(payload, list) and all(isinstance(row, Mapping) for row in payload):
            return [dict(row) for row in payload]
        raise LibreNMSAPIError("unexpected_payload")

    async def _request_json(
        self,
        method: str,
        resource_path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read a JSON object response, rejecting collection-shaped payloads."""
        payload = await self._request_json_payload(
            method,
            resource_path,
            params=params,
            json_payload=json_payload,
        )
        if not isinstance(payload, dict):
            raise LibreNMSAPIError("unexpected_payload")
        return payload

    async def _get_json(self, resource_path: str, *, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return await self._request_json("GET", resource_path, params=params)

    @staticmethod
    def _validated_add_device_payload(
        *, hostname: str, snmp_parameters: Mapping[str, Any], port: int
    ) -> dict[str, Any]:
        if not isinstance(hostname, str):
            raise LibreNMSAPIError("invalid_hostname")
        normalized_hostname = hostname.strip()
        if (
            not normalized_hostname
            or len(normalized_hostname) > 253
            or any(character.isspace() or ord(character) < 33 for character in normalized_hostname)
            or any(character in normalized_hostname for character in "/?#@")
        ):
            raise LibreNMSAPIError("invalid_hostname")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise LibreNMSAPIError("invalid_port")
        if not isinstance(snmp_parameters, Mapping):
            raise LibreNMSAPIError("invalid_snmp_parameters")

        parameters = dict(snmp_parameters)
        if any(not isinstance(key, str) for key in parameters):
            raise LibreNMSAPIError("invalid_snmp_parameters")
        if set(parameters) - _ADD_DEVICE_SNMP_FIELDS:
            # Reject path/behavior controls and unknown options at this boundary.
            raise LibreNMSAPIError("unsupported_snmp_parameter")
        if "snmpver" not in parameters or not isinstance(parameters["snmpver"], str):
            raise LibreNMSAPIError("invalid_snmp_parameters")

        version = parameters["snmpver"].strip().casefold()
        if version not in {"v1", "v2c", "v3"}:
            raise LibreNMSAPIError("invalid_snmp_parameters")
        parameters["snmpver"] = version

        def require_text(field: str) -> str:
            value = parameters.get(field)
            if not isinstance(value, str):
                raise LibreNMSAPIError("invalid_snmp_parameters")
            if not value.strip() or len(value) > 2048 or any(ord(character) < 32 for character in value):
                raise LibreNMSAPIError("invalid_snmp_parameters")
            # Credential octet strings can contain meaningful surrounding
            # spaces. Validate blankness, but pass the original value through.
            return value

        if version in {"v1", "v2c"}:
            if set(parameters) != {"snmpver", "community"}:
                raise LibreNMSAPIError("invalid_snmp_parameters")
            parameters["community"] = require_text("community")
        else:
            authlevel = parameters.get("authlevel")
            if not isinstance(authlevel, str):
                raise LibreNMSAPIError("invalid_snmp_parameters")
            levels = {
                "noauthnopriv": "noAuthNoPriv",
                "authnopriv": "authNoPriv",
                "authpriv": "authPriv",
            }
            canonical_level = levels.get(authlevel.strip().casefold())
            if canonical_level is None:
                raise LibreNMSAPIError("invalid_snmp_parameters")
            parameters["authlevel"] = canonical_level

            required_fields = {"snmpver", "authlevel", "authname"}
            if canonical_level in {"authNoPriv", "authPriv"}:
                required_fields.update({"authpass", "authalgo"})
            if canonical_level == "authPriv":
                required_fields.update({"cryptopass", "cryptoalgo"})
            if set(parameters) != required_fields:
                raise LibreNMSAPIError("invalid_snmp_parameters")
            for field in required_fields - {"snmpver", "authlevel"}:
                parameters[field] = require_text(field)

        return {"hostname": normalized_hostname, "port": port, **parameters}

    @staticmethod
    def _safe_add_device_result(payload: Mapping[str, Any]) -> dict[str, Any]:
        """Project only non-credential identity fields from a write response."""
        result: dict[str, Any] = {}
        status = payload.get("status")
        if isinstance(status, str):
            result["status"] = status

        def safe_row(row: Mapping[str, Any]) -> dict[str, Any]:
            return {key: row[key] for key in _ADD_DEVICE_RESPONSE_FIELDS if key in row}

        devices = payload.get("devices")
        if isinstance(devices, list):
            result["devices"] = [safe_row(row) for row in devices if isinstance(row, Mapping)]
        device = payload.get("device")
        if isinstance(device, Mapping):
            result["device"] = safe_row(device)
        top_level = safe_row(payload)
        for key, value in top_level.items():
            if key not in result:
                result[key] = value
        return result

    async def add_device(
        self,
        *,
        hostname: str,
        snmp_parameters: Mapping[str, Any],
        port: int = 161,
    ) -> dict[str, Any]:
        """Create one LibreNMS device using its documented add-device fields.

        The request is always sent to the fixed devices endpoint. Device SNMP
        credentials are never included in an exception or returned response.
        """
        request_payload = self._validated_add_device_payload(
            hostname=hostname,
            snmp_parameters=snmp_parameters,
            port=port,
        )
        payload = await self._request_json("POST", "/api/v0/devices", json_payload=request_payload)
        if str(payload.get("status") or "").strip().casefold() != "ok":
            raise LibreNMSAPIError("unexpected_payload")
        return self._safe_add_device_result(payload)

    async def update_device_snmp_profile(
        self,
        *,
        native_device_id: str,
        snmp_parameters: Mapping[str, Any],
        port: int = 161,
    ) -> dict[str, Any]:
        """Apply one explicitly selected profile to an existing native device.

        LibreNMS documents PATCH /devices/:hostname for updating device fields;
        its Device model exposes the SNMP fields as writable. Keep this caller
        constrained to those fields and a numeric native device ID so callers
        cannot turn the generic endpoint into an arbitrary device mutation.
        """
        device_id = str(native_device_id or "").strip()
        if not device_id.isdigit():
            raise LibreNMSAPIError("invalid_native_device_id")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise LibreNMSAPIError("invalid_port")

        normalized = self._validated_add_device_payload(
            hostname="127.0.0.1",
            snmp_parameters=snmp_parameters,
            port=port,
        )
        fields = [
            "snmpver",
            "port",
            "community",
            "authlevel",
            "authname",
            "authpass",
            "authalgo",
            "cryptopass",
            "cryptoalgo",
        ]
        values = [
            normalized["snmpver"],
            port,
            normalized.get("community", ""),
            normalized.get("authlevel", ""),
            normalized.get("authname", ""),
            normalized.get("authpass", ""),
            normalized.get("authalgo", ""),
            normalized.get("cryptopass", ""),
            normalized.get("cryptoalgo", ""),
        ]
        response_payload = await self._request_json_payload(
            "PATCH",
            f"/api/v0/devices/{quote(device_id, safe='')}",
            json_payload={"field": fields, "data": values},
        )
        if isinstance(response_payload, list):
            if len(response_payload) != 1:
                raise LibreNMSAPIError("unexpected_payload")
            payload = response_payload[0]
        else:
            payload = response_payload

        response_status = str(payload.get("status") or "").strip().casefold()
        if response_status == "error":
            raise LibreNMSAPIError("upstream_error")
        if response_status != "ok":
            raise LibreNMSAPIError("profile_update_rejected")
        # Do not echo arbitrary upstream fields or messages after a credential
        # update. The caller only needs an unambiguous success indication.
        return {"status": "ok"}

    async def get_system_info(self) -> dict[str, Any]:
        payload = await self._get_json("/api/v0/system")
        system = payload.get("system")
        # LibreNMS server_info() passes [$versions] to api_success(), so the
        # documented response currently wraps its version object in a list.
        if isinstance(system, list) and len(system) == 1:
            system = system[0]
        if not isinstance(system, Mapping):
            raise LibreNMSAPIError("unexpected_payload")
        return dict(system)

    async def get_device(self, native_device_id: str) -> dict[str, Any]:
        device_id = quote(str(native_device_id or "").strip(), safe="")
        if not device_id:
            raise LibreNMSAPIError("missing_native_device_id")
        payload = await self._get_json(f"/api/v0/devices/{device_id}")
        devices = _records(payload, "devices")
        if devices:
            return devices[0]
        device = payload.get("device")
        return dict(device) if isinstance(device, Mapping) else {}

    async def get_devices(self, *, query: str = "", device_type: str = "all", max_rows: int = 5000) -> list[dict[str, Any]]:
        """List native device identities for exact operator or auto matching.

        LibreNMS documents a filtered device-list endpoint but no pagination
        contract. Keep the request bounded and expose only identity/status
        fields; automatic matching must separately verify an exact IP address.
        """
        allowed_types = {
            "all", "active", "ignored", "up", "down", "disabled", "hostname",
            "sysName", "display", "device_id", "ipv4", "ipv6",
        }
        selected_type = str(device_type or "all").strip()
        if selected_type not in allowed_types:
            raise LibreNMSAPIError("unsupported_device_filter")
        search = str(query or "").strip()
        if selected_type not in {"all", "active", "ignored", "up", "down", "disabled"} and not search:
            raise LibreNMSAPIError("missing_device_query")
        payload = await self._get_json(
            "/api/v0/devices",
            params={"type": selected_type, **({"query": search} if search else {})},
        )
        rows = _records(payload, "devices")
        safe_fields = (
            "device_id", "hostname", "display", "os", "version", "hardware",
            "sysObjectID", "status", "disabled", "ignore", "last_discovered",
            "last_polled", "poller_group",
        )
        return [
            {field: row[field] for field in safe_fields if field in row}
            for row in rows[:max(0, int(max_rows))]
        ]

    async def get_device_ip_addresses(self, native_device_id: str) -> list[dict[str, Any]]:
        """Read the documented IP address list for one native device."""
        device_id = quote(str(native_device_id or "").strip(), safe="")
        if not device_id:
            raise LibreNMSAPIError("missing_native_device_id")
        payload = await self._get_json(f"/api/v0/devices/{device_id}/ip")
        rows = _records(payload, "addresses")
        safe_fields = ("ipv4_address", "ipv6_address")
        return [
            {field: row[field] for field in safe_fields if field in row}
            for row in rows
        ]

    async def get_health_graphs(self, native_device_id: str, health_type: str) -> list[dict[str, Any]]:
        """Read LibreNMS graph/category metadata; this route is not a sampler."""
        category = str(health_type or "").strip().casefold()
        if category not in _HEALTH_TYPES:
            raise LibreNMSAPIError("unsupported_health_type")
        device_id = quote(str(native_device_id or "").strip(), safe="")
        if not device_id:
            raise LibreNMSAPIError("missing_native_device_id")

        summary = await self._get_json(f"/api/v0/devices/{device_id}/health/{category}")
        graphs = _records(summary, "graphs")
        return graphs

    async def get_health_sensor(
        self,
        native_device_id: str,
        health_type: str,
        sensor_id: str,
    ) -> dict[str, Any] | None:
        """Read one native health row by its LibreNMS sensor identifier.

        LibreNMS returns graph metadata from the class endpoint. The optional
        sensor ID endpoint returns the persisted row, including current
        processor or memory-pool values; a graph name alone is never treated
        as a reading.
        """
        category = str(health_type or "").strip().casefold()
        if category not in _HEALTH_TYPES:
            raise LibreNMSAPIError("unsupported_health_type")
        device_id = quote(str(native_device_id or "").strip(), safe="")
        row_id = quote(str(sensor_id or "").strip(), safe="")
        if not device_id:
            raise LibreNMSAPIError("missing_native_device_id")
        if not row_id:
            raise LibreNMSAPIError("missing_native_sensor_id")

        payload = await self._get_json(f"/api/v0/devices/{device_id}/health/{category}/{row_id}")
        rows = _records(payload, "graphs")
        return rows[0] if rows else None

    async def get_health_sensors(
        self,
        native_device_id: str,
        health_type: str,
        *,
        max_rows: int = 2000,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return class graph metadata and the available native sensor rows.

        LibreNMS exposes current processor/mempool values through one detail
        request per sensor ID. Requests are bounded to avoid opening an
        unbounded number of simultaneous connections on large devices.
        """
        graphs = await self.get_health_graphs(native_device_id, health_type)
        sensor_ids = []
        for graph in graphs[:max(0, int(max_rows))]:
            sensor_id = graph.get("sensor_id")
            if sensor_id is not None and str(sensor_id).strip():
                sensor_ids.append(str(sensor_id).strip())

        semaphore = asyncio.Semaphore(8)

        async def read_one(sensor_id: str) -> dict[str, Any] | None:
            async with semaphore:
                return await self.get_health_sensor(native_device_id, health_type, sensor_id)

        details = await asyncio.gather(*(read_one(sensor_id) for sensor_id in sensor_ids))
        return graphs, [row for row in details if isinstance(row, dict)]

    async def get_all_sensors(self) -> list[dict[str, Any]]:
        """Fetch the native sensor table once; filter by native ID in caller."""
        payload = await self._get_json("/api/v0/resources/sensors")
        return _records(payload, "sensors")

    async def get_wireless_sensors(self, native_device_id: str) -> list[dict[str, Any]]:
        device_id = quote(str(native_device_id or "").strip(), safe="")
        if not device_id:
            raise LibreNMSAPIError("missing_native_device_id")
        payload = await self._get_json(f"/api/v0/devices/{device_id}/wireless-sensors")
        return _records(payload, "wireless_sensors")

    async def get_transceivers(self, native_device_id: str) -> list[dict[str, Any]]:
        device_id = quote(str(native_device_id or "").strip(), safe="")
        if not device_id:
            raise LibreNMSAPIError("missing_native_device_id")
        payload = await self._get_json(f"/api/v0/devices/{device_id}/transceivers")
        return _records(payload, "transceivers")

    async def read_device_snapshot(self, native_device_id: str) -> LibreNMSDeviceSnapshot:
        """Read one native device and its current hardware entity rows."""
        device_id = str(native_device_id or "").strip()
        device = await self.get_device(device_id)
        if not device:
            raise LibreNMSAPIError("native_device_not_found", http_status=404)

        # A valid empty list is the API's representation for optional data not
        # present on a device. HTTP 404/auth/upstream errors are deliberately
        # propagated rather than reinterpreted as an empty hardware inventory.
        results = await asyncio.gather(
            self.get_all_sensors(),
            self.get_wireless_sensors(device_id),
            self.get_transceivers(device_id),
            self.get_health_sensors(device_id, "processor"),
            self.get_health_sensors(device_id, "mempool"),
            self.get_health_graphs(device_id, "storage"),
            return_exceptions=True,
        )
        # Wait for every in-flight request before propagating an error. With
        # gather's default behavior, sibling requests keep running after the
        # first failure and can race a caller closing this client.
        for result in results:
            if isinstance(result, BaseException):
                raise result
        all_sensors, wireless, transceivers, processor_result, mempool_result, storage_graphs = results
        processor_graphs, processor_sensors = processor_result
        mempool_graphs, memory_pools = mempool_result
        resolved_device_id = str(device.get("device_id") or device_id)
        local_sensors = [
            row for row in all_sensors
            if str(row.get("device_id") or "") == resolved_device_id
            and not _sensor_is_deleted(row.get("sensor_deleted"))
        ]

        return LibreNMSDeviceSnapshot(
            device=device,
            sensors=local_sensors,
            wireless_sensors=wireless,
            transceivers=transceivers,
            processor_sensors=processor_sensors,
            memory_pools=memory_pools,
            health_graphs={
                "processor": processor_graphs,
                "mempool": mempool_graphs,
                "storage": storage_graphs,
            },
        )
