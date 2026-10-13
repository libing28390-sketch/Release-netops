"""Server-side Apache Guacamole JSON authentication and tunnel helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


JSON_SECRET_ENV = "GUACAMOLE_JSON_SECRET_KEY"
DEFAULT_BASE_URL = "http://guacamole:8080/guacamole"
AUTH_TIMEOUT_SECONDS = 8.0
MAX_AUTH_RESPONSE_BYTES = 1024 * 1024


class GuacamoleServiceError(RuntimeError):
    """Safe Guacamole failure with no upstream response or secret attached."""

    def __init__(self, code: str = "GUACAMOLE_UNAVAILABLE"):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GuacamoleConnection:
    auth_token: str
    data_source: str
    connection_id: str
    websocket_url: str


def _secret_key(secret_hex: str | None = None) -> bytes:
    value = str(secret_hex if secret_hex is not None else os.getenv(JSON_SECRET_ENV, "")).strip()
    if len(value) != 32:
        raise GuacamoleServiceError("GUACAMOLE_NOT_CONFIGURED")
    try:
        key = bytes.fromhex(value)
    except ValueError as exc:
        raise GuacamoleServiceError("GUACAMOLE_NOT_CONFIGURED") from exc
    if len(key) != 16:
        raise GuacamoleServiceError("GUACAMOLE_NOT_CONFIGURED")
    return key


def encrypt_json_authentication(data: Mapping[str, object], secret_hex: str | None = None) -> str:
    """HMAC-SHA256 then AES-128-CBC encrypt a Guacamole JSON auth payload.

    Guacamole's JSON extension prepends the raw HMAC digest to the exact JSON
    bytes, encrypts the combined bytes with an all-zero IV, then base64 encodes
    the ciphertext.  The same configured 128-bit key is used for HMAC and AES.
    """
    key = _secret_key(secret_hex)
    plain_json = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signed = hmac.new(key, plain_json, hashlib.sha256).digest() + plain_json
    padding_length = 16 - (len(signed) % 16)
    padded = signed + bytes([padding_length]) * padding_length
    encryptor = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("ascii")


def _base_url() -> str:
    value = str(os.getenv("GUACAMOLE_BASE_URL", DEFAULT_BASE_URL) or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise GuacamoleServiceError("GUACAMOLE_NOT_CONFIGURED")
    if parsed.query or parsed.fragment:
        raise GuacamoleServiceError("GUACAMOLE_NOT_CONFIGURED")
    return value


def _api_url(base: str, suffix: str) -> str:
    return f"{base}/api/{suffix.lstrip('/')}"


def _guacamole_recording_name(recording_name: str) -> str:
    name = str(recording_name or "").strip()
    if not name or any(char in name for char in "/\\\r\n"):
        raise GuacamoleServiceError("REMOTE_DESKTOP_INVALID_RECORDING")
    return name if name.lower().endswith(".guac") else f"{name}.guac"


def build_connection_parameters(
    *,
    protocol: str,
    hostname: str,
    port: int,
    username: str,
    password: str,
    profile: Mapping[str, object],
    guac_recording_dir: str,
    recording_name: str,
) -> dict[str, str]:
    """Build target parameters exclusively from authorized server-side data."""
    protocol_name = str(protocol or "").strip().lower()
    if protocol_name not in {"rdp", "vnc"}:
        raise GuacamoleServiceError("REMOTE_DESKTOP_INVALID_PROTOCOL")
    resolved_host = str(hostname or "").strip()
    if not resolved_host or any(char in resolved_host for char in "/?#@\r\n"):
        raise GuacamoleServiceError("REMOTE_DESKTOP_INVALID_TARGET")
    try:
        resolved_port = int(port)
    except (TypeError, ValueError) as exc:
        raise GuacamoleServiceError("REMOTE_DESKTOP_INVALID_TARGET") from exc
    if not 1 <= resolved_port <= 65535:
        raise GuacamoleServiceError("REMOTE_DESKTOP_INVALID_TARGET")
    if not password:
        raise GuacamoleServiceError("REMOTE_DESKTOP_CREDENTIALS_MISSING")
    if protocol_name == "rdp" and not username:
        raise GuacamoleServiceError("REMOTE_DESKTOP_CREDENTIALS_MISSING")

    clipboard = bool(profile.get("clipboard_enabled"))
    parameters: dict[str, str] = {
        "hostname": resolved_host,
        "port": str(resolved_port),
        "disable-copy": "false" if clipboard else "true",
        "disable-paste": "false" if clipboard else "true",
        "recording-path": guac_recording_dir,
        "create-recording-path": "true",
        "recording-name": _guacamole_recording_name(recording_name),
        "recording-exclude-output": "false",
        "recording-exclude-mouse": "false",
        "recording-exclude-keys": "false",
    }
    if protocol_name == "rdp":
        mode = str(profile.get("rdp_security_mode") or "nla").strip().lower()
        if mode not in {"any", "nla", "tls", "rdp"}:
            raise GuacamoleServiceError("REMOTE_DESKTOP_INVALID_PROFILE")
        cert_fingerprint = str(profile.get("rdp_cert_fingerprint") or "").strip()
        if cert_fingerprint and not re.fullmatch(r"[0-9A-Fa-f]{64}", cert_fingerprint):
            raise GuacamoleServiceError("REMOTE_DESKTOP_INVALID_PROFILE")
        parameters.update(
            {
                "username": username,
                "password": password,
                "security": mode,
                "resize-method": "display-update",
                "width": "1920",
                "height": "1080",
                "ignore-cert": "false",
                "enable-drive": "false",
                "enable-printing": "false",
                "enable-audio": "false",
                "enable-sftp": "false",
            }
        )
        if cert_fingerprint:
            # The Guacamole image ships FreeRDP 2.11.x, whose fingerprint
            # matcher compares the hash in colon-separated byte form.
            normalized_fingerprint = cert_fingerprint.lower()
            freerdp_fingerprint = ":".join(
                normalized_fingerprint[index : index + 2]
                for index in range(0, len(normalized_fingerprint), 2)
            )
            parameters["cert-fingerprints"] = f"sha256:{freerdp_fingerprint}"
        domain = str(profile.get("rdp_domain") or "").strip()
        if domain:
            parameters["domain"] = domain
    else:
        # VNC servers commonly authenticate with a password only; username is
        # omitted unless a specific server requires one.
        parameters["password"] = password
        parameters["color-depth"] = "24"
        if username:
            parameters["username"] = username
    return parameters


def _millis_until_expiration(seconds: int = 30) -> int:
    return int((datetime.now(timezone.utc).timestamp() + max(1, int(seconds))) * 1000)


async def create_connection(
    *,
    session_id: str,
    protocol: str,
    parameters: Mapping[str, str],
    transport: httpx.AsyncBaseTransport | None = None,
) -> GuacamoleConnection:
    """Authenticate with Guacamole and return its actual connection identifier."""
    base = _base_url()
    connection_name = f"nexora-{session_id}"
    username = f"nexora-{secrets.token_urlsafe(16)}"
    payload = {
        "username": username,
        "expires": _millis_until_expiration(),
        "connections": {
            connection_name: {
                "protocol": protocol,
                "parameters": dict(parameters),
            }
        },
    }
    encrypted_data = encrypt_json_authentication(payload)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(AUTH_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            response = await client.post(_api_url(base, "tokens"), data={"data": encrypted_data})
            if response.status_code != 200 or len(response.content) > MAX_AUTH_RESPONSE_BYTES:
                raise GuacamoleServiceError("GUACAMOLE_AUTH_FAILED")
            auth = response.json()
            if not isinstance(auth, Mapping):
                raise GuacamoleServiceError("GUACAMOLE_AUTH_FAILED")
            auth_token = str(auth.get("authToken") or "")
            data_source = str(auth.get("dataSource") or "")
            if not auth_token or not data_source:
                raise GuacamoleServiceError("GUACAMOLE_AUTH_FAILED")
            connection_response = await client.get(
                _api_url(base, f"session/data/{data_source}/connections"),
                params={"token": auth_token},
            )
            if connection_response.status_code != 200 or len(connection_response.content) > MAX_AUTH_RESPONSE_BYTES:
                raise GuacamoleServiceError("GUACAMOLE_CONNECTION_LOOKUP_FAILED")
            connections = connection_response.json()
            connection = connections.get(connection_name) if isinstance(connections, dict) else None
            if not isinstance(connection, dict):
                raise GuacamoleServiceError("GUACAMOLE_CONNECTION_LOOKUP_FAILED")
            connection_id = str(connection.get("identifier") or connection.get("id") or "")
            if not connection_id:
                raise GuacamoleServiceError("GUACAMOLE_CONNECTION_LOOKUP_FAILED")
    except GuacamoleServiceError:
        raise
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as exc:
        # Do not preserve upstream URL/token, target settings, or response body.
        raise GuacamoleServiceError("GUACAMOLE_UNAVAILABLE") from None

    parsed = urlsplit(base)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    path = f"{parsed.path.rstrip('/')}/websocket-tunnel"
    websocket_url = urlunsplit(
        (
            ws_scheme,
            parsed.netloc,
            path,
            urlencode(
                {
                    "token": auth_token,
                    "GUAC_DATA_SOURCE": data_source,
                    "GUAC_ID": connection_id,
                    "GUAC_TYPE": "c",
                }
            ),
            "",
        )
    )
    return GuacamoleConnection(
        auth_token=auth_token,
        data_source=data_source,
        connection_id=connection_id,
        websocket_url=websocket_url,
    )


async def release_authorization(
    connection: GuacamoleConnection,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """Invalidate the temporary Guacamole authentication token best-effort."""
    try:
        base = _base_url()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(AUTH_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            await client.delete(
                _api_url(base, "session"),
                headers={"Guacamole-Token": connection.auth_token},
            )
    except Exception:
        # Guacamole tokens expire shortly after issuance; logout is best-effort
        # and failures intentionally do not reveal the internal token.
        return


__all__ = [
    "GuacamoleConnection",
    "GuacamoleServiceError",
    "build_connection_parameters",
    "create_connection",
    "encrypt_json_authentication",
    "release_authorization",
]
