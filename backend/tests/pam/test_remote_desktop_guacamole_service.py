from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import HTTPException

from services import guacamole_service, pam_remote_desktop


TEST_JSON_KEY = "00112233445566778899aabbccddeeff"
TEST_PASSWORD = "fixture-password-not-secret"


def _decrypt_json_auth(data: str, key_hex: str = TEST_JSON_KEY) -> dict:
    ciphertext = base64.b64decode(data)
    decryptor = Cipher(algorithms.AES(bytes.fromhex(key_hex)), modes.CBC(bytes(16))).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    padding = padded[-1]
    signed = padded[:-padding]
    digest, payload = signed[:32], signed[32:]
    assert hmac.compare_digest(digest, hmac.new(bytes.fromhex(key_hex), payload, hashlib.sha256).digest())
    return json.loads(payload.decode("utf-8"))


def test_json_authentication_uses_hmac_sha256_and_aes_128_cbc():
    expected = {"username": "nexora-session", "expires": 1234567890000, "connections": {}}

    encrypted = guacamole_service.encrypt_json_authentication(expected, TEST_JSON_KEY)

    assert _decrypt_json_auth(encrypted) == expected


def test_connection_parameters_keep_rdp_nla_and_certificate_validation_enabled():
    parameters = guacamole_service.build_connection_parameters(
        protocol="rdp",
        hostname="win-01.example.test",
        port=3389,
        username="operator",
        password=TEST_PASSWORD,
        profile={"rdp_security_mode": "nla", "rdp_domain": "OPS", "clipboard_enabled": False},
        guac_recording_dir="/recordings/pam-rdp-test",
        recording_name="pam-rdp-test",
    )

    assert parameters["security"] == "nla"
    assert parameters["resize-method"] == "display-update"
    assert "width" not in parameters
    assert "height" not in parameters
    assert parameters["ignore-cert"] == "false"
    assert "cert-fingerprints" not in parameters
    assert parameters["recording-path"] == "/recordings/pam-rdp-test"
    assert parameters["recording-name"] == "pam-rdp-test.guac"
    assert parameters["create-recording-path"] == "true"
    assert parameters["enable-drive"] == "false"
    assert parameters["enable-printing"] == "false"
    assert parameters["domain"] == "OPS"
    assert parameters["password"] == TEST_PASSWORD


def test_vnc_parameters_allow_password_only_and_disable_file_transfer():
    parameters = guacamole_service.build_connection_parameters(
        protocol="vnc",
        hostname="192.0.2.21",
        port=5900,
        username="",
        password=TEST_PASSWORD,
        profile={},
        guac_recording_dir="/recordings/pam-vnc-test",
        recording_name="pam-vnc-test",
    )

    assert parameters["password"] == TEST_PASSWORD
    assert "username" not in parameters
    assert "resize-method" not in parameters
    assert parameters["recording-path"] == "/recordings/pam-vnc-test"
    assert parameters["recording-name"] == "pam-vnc-test.guac"


def test_rdp_certificate_fingerprint_pins_sha256_without_ignoring_validation():
    fingerprint = "4CE56BB09B6F1B96A521AE58EFCEA743ECBB632A9C8D29F999D01CE47F9FF80E"
    parameters = guacamole_service.build_connection_parameters(
        protocol="rdp",
        hostname="win-01.example.test",
        port=3389,
        username="operator",
        password=TEST_PASSWORD,
        profile={"rdp_cert_fingerprint": fingerprint},
        guac_recording_dir="/recordings/pam-rdp-pinned",
        recording_name="pam-rdp-pinned",
    )

    assert parameters["ignore-cert"] == "false"
    expected_fingerprint = ":".join(
        fingerprint.lower()[index : index + 2] for index in range(0, len(fingerprint), 2)
    )
    assert parameters["cert-fingerprints"] == f"sha256:{expected_fingerprint}"


def test_rdp_certificate_fingerprint_rejects_malformed_pin():
    with pytest.raises(guacamole_service.GuacamoleServiceError, match="REMOTE_DESKTOP_INVALID_PROFILE"):
        guacamole_service.build_connection_parameters(
            protocol="rdp",
            hostname="win-01.example.test",
            port=3389,
            username="operator",
            password=TEST_PASSWORD,
            profile={"rdp_cert_fingerprint": "not-a-sha256-fingerprint"},
            guac_recording_dir="/recordings/pam-rdp-invalid-pin",
            recording_name="pam-rdp-invalid-pin",
        )


@pytest.mark.anyio
async def test_connection_auth_uses_actual_data_source_and_connection_identifier(monkeypatch):
    monkeypatch.setenv("GUACAMOLE_JSON_SECRET_KEY", TEST_JSON_KEY)
    monkeypatch.setenv("GUACAMOLE_BASE_URL", "http://guacamole:8080/guacamole")
    calls: list[tuple[str, str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, dict(request.headers)))
        if request.method == "POST":
            assert request.url.path == "/guacamole/api/tokens"
            auth_form = parse_qs(request.content.decode("utf-8"))
            body = _decrypt_json_auth(auth_form["data"][0])
            assert body["connections"]["nexora-pam-rdp-test"]["protocol"] == "rdp"
            return httpx.Response(200, json={"authToken": "opaque-test-token", "dataSource": "json"})
        assert request.url.path == "/guacamole/api/session/data/json/connections"
        assert request.url.params.get("token") == "opaque-test-token"
        return httpx.Response(200, json={"nexora-pam-rdp-test": {"identifier": "91"}})

    connection = await guacamole_service.create_connection(
        session_id="pam-rdp-test",
        protocol="rdp",
        parameters={"hostname": "win-01.example.test", "password": TEST_PASSWORD},
        transport=httpx.MockTransport(handler),
    )

    assert connection.auth_token == "opaque-test-token"
    assert connection.data_source == "json"
    assert connection.connection_id == "91"
    parsed = urlsplit(connection.websocket_url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/guacamole/websocket-tunnel"
    assert parsed.scheme == "ws"
    assert query["token"] == ["opaque-test-token"]
    assert query["GUAC_DATA_SOURCE"] == ["json"]
    assert query["GUAC_ID"] == ["91"]
    assert [(method, path) for method, path, _headers in calls] == [
        ("POST", "/guacamole/api/tokens"),
        ("GET", "/guacamole/api/session/data/json/connections"),
    ]


@pytest.mark.anyio
async def test_temporary_authorization_uses_guacamole_16_logout_endpoint(monkeypatch):
    monkeypatch.setenv("GUACAMOLE_BASE_URL", "http://guacamole:8080/guacamole")
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    connection = guacamole_service.GuacamoleConnection(
        auth_token="opaque-test-token",
        data_source="json",
        connection_id="91",
        websocket_url="ws://guacamole:8080/guacamole/websocket-tunnel",
    )
    await guacamole_service.release_authorization(connection, transport=httpx.MockTransport(handler))

    assert len(seen) == 1
    assert seen[0].method == "DELETE"
    assert seen[0].url.path == "/guacamole/api/session"
    assert seen[0].headers["Guacamole-Token"] == "opaque-test-token"


class _FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params):
        if "FROM devices" in query:
            return _FakeResult(self.rows.get("device"))
        if "FROM credentials" in query:
            return _FakeResult(self.rows.get("credential"))
        raise AssertionError("Unexpected query in credential resolution unit test")


def test_credential_inheritance_reuses_device_vault_role(monkeypatch):
    device = {"id": "device-1", "asset_id": "asset-1"}
    monkeypatch.setattr(
        "services.vault_service.resolve_device_credentials",
        lambda _device: {"normal_username": "desktop-user", "normal_password": TEST_PASSWORD},
    )
    conn = _FakeConnection({"device": device})

    username, password = pam_remote_desktop.resolve_remote_desktop_credentials(
        conn,
        {"id": "asset-1", "normal_username": "legacy-user", "normal_password": "legacy-value"},
        {"normal_credential_id": None},
        "rdp",
        "normal",
    )

    assert username == "desktop-user"
    assert password == TEST_PASSWORD


def test_stale_explicit_profile_credential_fails_closed():
    conn = _FakeConnection({"credential": None})
    with pytest.raises(HTTPException) as error:
        pam_remote_desktop.resolve_remote_desktop_credentials(
            conn,
            {"id": "asset-1", "normal_username": "legacy-user", "normal_password": "legacy-value"},
            {"normal_credential_id": "missing-credential"},
            "rdp",
            "normal",
        )
    assert error.value.status_code == 422
