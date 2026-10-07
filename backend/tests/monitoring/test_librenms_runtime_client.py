from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from services.librenms_runtime_client import (
    LibreNMSAPIError,
    LibreNMSRuntimeClient,
    normalize_librenms_base_url,
)


def _client(handler: Any, *, token: str = "test-token", timeout: float = 1.0) -> LibreNMSRuntimeClient:
    return LibreNMSRuntimeClient(
        "http://librenms",
        token,
        timeout_seconds=timeout,
        transport=httpx.MockTransport(handler),
    )


def test_base_url_and_token_are_validated_before_request() -> None:
    for bad_url, expected_code in (
        ("ftp://librenms", "invalid_base_url"),
        ("http://user:secret@librenms", "invalid_base_url"),
        ("http://librenms/api/v0", "invalid_base_url"),
        ("http://librenms?token=secret", "invalid_base_url"),
        ("http://outside.example", "host_not_allowed"),
        ("http://librenms:bad-port", "invalid_base_url"),
    ):
        with pytest.raises(LibreNMSAPIError) as exc_info:
            LibreNMSRuntimeClient(bad_url, "test-token")
        assert exc_info.value.code == expected_code

    with pytest.raises(LibreNMSAPIError, match="missing_api_token"):
        LibreNMSRuntimeClient("http://librenms", " ")
    with pytest.raises(LibreNMSAPIError, match="invalid_api_token"):
        LibreNMSRuntimeClient("http://librenms", "token\r\nInjected: yes")
    with pytest.raises(LibreNMSAPIError, match="invalid_api_token"):
        LibreNMSRuntimeClient("http://librenms", "token with space")


def test_base_url_allowlist_supports_explicit_port_and_rejects_api_path() -> None:
    assert normalize_librenms_base_url("HTTPS://LibreNMS:8443/proxy/", allowed_hosts="librenms:8443") == (
        "https://LibreNMS:8443/proxy"
    )
    with pytest.raises(LibreNMSAPIError, match="host_not_allowed"):
        normalize_librenms_base_url("http://librenms:8443", allowed_hosts="librenms:8080")


def test_reuses_one_http_client_and_reads_system_and_device() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v0/system":
            return httpx.Response(200, json={"status": "ok", "system": [{"version": "26.9"}]})
        if request.url.path == "/api/v0/devices/sw-1":
            return httpx.Response(200, json={"status": "ok", "devices": [{"device_id": 7, "hostname": "sw-1"}]})
        return httpx.Response(404, json={"status": "error", "message": "private detail"})

    async def run() -> None:
        client = _client(handler)
        try:
            system = await client.get_system_info()
            http_client = client._http
            device = await client.get_device("sw-1")
            assert client._http is http_client
            assert system == {"version": "26.9"}
            assert device["hostname"] == "sw-1"
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(requests) == 2
    assert all(request.headers["Authorization"] == "Bearer test-token" for request in requests)
    assert all(request.headers["Accept"] == "application/json" for request in requests)


def test_device_search_supports_exact_ip_lookup_and_sanitizes_ip_address_rows() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v0/devices":
            return httpx.Response(200, json={"status": "ok", "devices": [{
                "device_id": 17, "hostname": "sw-1", "display": "Switch 1",
                "sysName": "sw-1", "private_field": "must not escape",
            }]})
        if request.url.path == "/api/v0/devices/17/ip":
            return httpx.Response(200, json={"status": "ok", "addresses": [{
                "ipv4_address": "192.0.2.10", "ipv4_prefixlen": "24",
                "ipv6_address": "2001:db8::10", "private_field": "must not escape",
            }]})
        return httpx.Response(404, json={"status": "error"})

    async def run() -> None:
        client = _client(handler)
        try:
            devices = await client.get_devices(device_type="ipv4", query="192.0.2.10", max_rows=10)
            addresses = await client.get_device_ip_addresses("17")
        finally:
            await client.aclose()
        assert devices == [{"device_id": 17, "hostname": "sw-1", "display": "Switch 1"}]
        assert addresses == [{"ipv4_address": "192.0.2.10", "ipv6_address": "2001:db8::10"}]

    asyncio.run(run())
    assert requests[0].url.params["type"] == "ipv4"
    assert requests[0].url.params["query"] == "192.0.2.10"
    assert [request.url.path for request in requests] == ["/api/v0/devices", "/api/v0/devices/17/ip"]


@pytest.mark.parametrize(
    ("hostname", "snmp_parameters", "port", "response_row", "expected_payload", "secrets"),
    [
        (
            "192.0.2.21",
            {"snmpver": "v2c", "community": " private-community "},
            161,
            {"device_id": 21, "hostname": "192.0.2.21", "community": " private-community "},
            {"hostname": "192.0.2.21", "port": 161, "snmpver": "v2c", "community": " private-community "},
            (" private-community ",),
        ),
        (
            "edge-01.example.net",
            {
                "snmpver": "v3",
                "authlevel": "authPriv",
                "authname": "private-user",
                "authpass": "private-auth-pass",
                "authalgo": "SHA",
                "cryptopass": "private-privacy-pass",
                "cryptoalgo": "AES",
            },
            1161,
            {
                "device_id": 22,
                "hostname": "edge-01.example.net",
                "authname": "private-user",
                "authpass": "private-auth-pass",
                "cryptopass": "private-privacy-pass",
            },
            {
                "hostname": "edge-01.example.net",
                "port": 1161,
                "snmpver": "v3",
                "authlevel": "authPriv",
                "authname": "private-user",
                "authpass": "private-auth-pass",
                "authalgo": "SHA",
                "cryptopass": "private-privacy-pass",
                "cryptoalgo": "AES",
            },
            ("private-user", "private-auth-pass", "private-privacy-pass"),
        ),
    ],
)
def test_add_device_posts_only_fixed_documented_payload_and_sanitizes_result(
    hostname: str,
    snmp_parameters: dict[str, str],
    port: int,
    response_row: dict[str, Any],
    expected_payload: dict[str, Any],
    secrets: tuple[str, ...],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "devices": [response_row]})

    async def run() -> None:
        client = _client(handler)
        try:
            result = await client.add_device(
                hostname=hostname,
                snmp_parameters=snmp_parameters,
                port=port,
            )
        finally:
            await client.aclose()

        assert result["status"] == "ok"
        assert result["devices"][0]["device_id"] in {21, 22}
        serialized_result = json.dumps(result)
        for secret in secrets:
            assert secret not in serialized_result

    asyncio.run(run())
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v0/devices"
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["Accept"] == "application/json"
    assert json.loads(request.content) == expected_payload
    assert "force_add" not in json.loads(request.content)
    assert "ping_fallback" not in json.loads(request.content)


@pytest.mark.parametrize("response_payload", [{}, {"status": "pending", "devices": []}])
def test_add_device_requires_explicit_success_status(response_payload: dict[str, Any]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.add_device(
                    hostname="192.0.2.40",
                    snmp_parameters={"snmpver": "v2c", "community": "private"},
                )
        finally:
            await client.aclose()
        assert exc_info.value.code == "unexpected_payload"

    asyncio.run(run())


@pytest.mark.parametrize(
    "response_payload",
    [
        {"status": "ok", "message": "updated", "authpass": "response-secret"},
        [{"status": "ok", "message": "updated", "community": "response-secret"}],
    ],
)
def test_update_device_snmp_profile_accepts_object_and_documented_array_response(
    response_payload: dict[str, Any] | list[dict[str, Any]],
) -> None:
    requests: list[httpx.Request] = []
    secret = "v3-private-auth-secret"
    parameters = {
        "snmpver": "v3",
        "authlevel": "authPriv",
        "authname": "profile-user",
        "authpass": secret,
        "authalgo": "SHA",
        "cryptopass": "v3-private-privacy-secret",
        "cryptoalgo": "AES",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_payload)

    async def run() -> None:
        client = _client(handler)
        try:
            result = await client.update_device_snmp_profile(
                native_device_id="42",
                snmp_parameters=parameters,
                port=1161,
            )
        finally:
            await client.aclose()
        assert result == {"status": "ok"}
        assert secret not in json.dumps(result)
        assert "response-secret" not in json.dumps(result)

    asyncio.run(run())
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/api/v0/devices/42"
    payload = json.loads(request.content)
    assert payload["field"] == [
        "snmpver", "port", "community", "authlevel", "authname", "authpass",
        "authalgo", "cryptopass", "cryptoalgo",
    ]
    assert payload["data"] == [
        "v3", 1161, "", "authPriv", "profile-user", secret, "SHA",
        "v3-private-privacy-secret", "AES",
    ]
    assert "hostname" not in payload
    assert "force_add" not in payload


@pytest.mark.parametrize(
    ("response_payload", "expected_code"),
    [
        ({"status": "error", "message": "private upstream detail", "authpass": "response-secret"}, "upstream_error"),
        ([{"status": "error", "message": "private upstream detail", "community": "response-secret"}], "upstream_error"),
        ({"message": "status missing"}, "profile_update_rejected"),
        ([{}], "profile_update_rejected"),
        ([], "unexpected_payload"),
    ],
)
def test_update_device_snmp_profile_rejects_error_or_empty_status_without_exposing_response(
    response_payload: dict[str, Any] | list[dict[str, Any]],
    expected_code: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload)

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.update_device_snmp_profile(
                    native_device_id="42",
                    snmp_parameters={"snmpver": "v2c", "community": "request-secret"},
                )
            assert exc_info.value.code == expected_code
            assert "private upstream detail" not in str(exc_info.value)
            assert "response-secret" not in str(exc_info.value)
            assert "request-secret" not in str(exc_info.value)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_update_device_snmp_profile_rejects_non_numeric_id_and_bad_profile() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    async def run() -> None:
        client = _client(handler)
        try:
            for native_device_id, parameters, expected in (
                ("../devices/other", {"snmpver": "v2c", "community": "community"}, "invalid_native_device_id"),
                ("42", {"snmpver": "v2c", "community": "community", "hostname": "bad"}, "unsupported_snmp_parameter"),
            ):
                with pytest.raises(LibreNMSAPIError) as exc_info:
                    await client.update_device_snmp_profile(
                        native_device_id=native_device_id,
                        snmp_parameters=parameters,
                    )
                assert exc_info.value.code == expected
        finally:
            await client.aclose()

    asyncio.run(run())
    assert requests == []


@pytest.mark.parametrize(
    ("hostname", "snmp_parameters", "port", "expected_code"),
    [
        ("", {"snmpver": "v2c", "community": "community"}, 161, "invalid_hostname"),
        ("device/../api/v0/system", {"snmpver": "v2c", "community": "community"}, 161, "invalid_hostname"),
        ("192.0.2.2", {"snmpver": "v2c", "community": "community"}, 0, "invalid_port"),
        ("192.0.2.2", {"snmpver": "v2c", "community": "community"}, True, "invalid_port"),
        ("192.0.2.2", {"snmpver": "v2c"}, 161, "invalid_snmp_parameters"),
        (
            "192.0.2.2",
            {"snmpver": "v3", "authlevel": "authPriv", "authname": "user"},
            161,
            "invalid_snmp_parameters",
        ),
        (
            "192.0.2.2",
            {"snmpver": "v3", "authlevel": "authPriv", "authname": "user", "authpass": "pass",
             "authalgo": "SHA", "cryptopass": "privacy", "cryptoalgo": "AES", "force_add": True},
            161,
            "unsupported_snmp_parameter",
        ),
        (
            "192.0.2.2",
            {"snmpver": "v3", "authlevel": "authPriv", "authname": "user", "authpass": "pass",
             "authalgo": "SHA", "cryptopass": "privacy", "cryptoalgo": "AES", "ping_fallback": True},
            161,
            "unsupported_snmp_parameter",
        ),
    ],
)
def test_add_device_rejects_invalid_or_unapproved_inputs_before_request(
    hostname: str,
    snmp_parameters: dict[str, Any],
    port: int,
    expected_code: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.add_device(hostname=hostname, snmp_parameters=snmp_parameters, port=port)
            assert exc_info.value.code == expected_code
            assert "community" not in str(exc_info.value)
            assert "pass" not in str(exc_info.value)
        finally:
            await client.aclose()

    asyncio.run(run())
    assert requests == []


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(401, "unauthorized"), (403, "forbidden"), (503, "http_error")],
)
def test_add_device_upstream_failures_do_not_expose_request_or_response_secrets(
    status_code: int, expected_code: str
) -> None:
    auth_secret = "request-auth-secret"
    response_secret = "response-auth-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": response_secret, "authpass": response_secret})

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.add_device(
                    hostname="192.0.2.4",
                    snmp_parameters={
                        "snmpver": "v3",
                        "authlevel": "authNoPriv",
                        "authname": "snmp-user",
                        "authpass": auth_secret,
                        "authalgo": "SHA",
                    },
                )
            assert exc_info.value.code == expected_code
            assert exc_info.value.http_status == status_code
            assert auth_secret not in str(exc_info.value)
            assert response_secret not in str(exc_info.value)
        finally:
            await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(401, "unauthorized"), (403, "forbidden"), (404, "http_error"), (503, "http_error")],
)
def test_http_failures_are_sanitized_and_status_is_preserved(status_code: int, expected_code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "secret response body"})

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.get_system_info()
            error = exc_info.value
            assert error.code == expected_code
            assert error.http_status == status_code
            assert "secret" not in str(error)
            assert "test-token" not in str(error)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_librenms_error_payload_does_not_expose_upstream_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "message": "sensitive upstream detail"})

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.get_system_info()
            assert exc_info.value.code == "upstream_error"
            assert "sensitive" not in str(exc_info.value)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_redirect_is_not_followed() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://outside.example/collect"})

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.get_system_info()
            assert exc_info.value.code == "http_error"
            assert exc_info.value.http_status == 302
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (httpx.ReadTimeout("private timeout"), "timeout"),
        (httpx.ConnectError("private connection detail"), "unreachable"),
    ],
)
def test_timeout_and_unreachable_errors_are_sanitized(failure: Exception, expected_code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await client.get_system_info()
            assert exc_info.value.code == expected_code
            assert "private" not in str(exc_info.value)
        finally:
            await client.aclose()

    asyncio.run(run())


def test_invalid_json_and_non_object_payloads_are_rejected() -> None:
    async def run() -> None:
        invalid_json = _client(lambda request: httpx.Response(200, content=b"not-json"))
        try:
            with pytest.raises(LibreNMSAPIError, match="invalid_json"):
                await invalid_json.get_system_info()
        finally:
            await invalid_json.aclose()

        non_object = _client(lambda request: httpx.Response(200, json=["not", "an", "object"]))
        try:
            with pytest.raises(LibreNMSAPIError, match="unexpected_payload"):
                await non_object.get_system_info()
        finally:
            await non_object.aclose()

    asyncio.run(run())


def test_oversized_response_is_stopped_during_streaming() -> None:
    class OversizedStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.yielded = 0

        async def __aiter__(self):
            chunk = b"x" * (1024 * 1024)
            for _ in range(20):
                self.yielded += 1
                yield chunk

        async def aclose(self) -> None:
            return None

    stream = OversizedStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async def run() -> None:
        client = _client(handler)
        try:
            with pytest.raises(LibreNMSAPIError, match="response_too_large"):
                await client.get_system_info()
        finally:
            await client.aclose()

    asyncio.run(run())
    assert stream.yielded == 9


def test_snapshot_keeps_current_readings_separate_from_health_metadata() -> None:
    calls: list[str] = []
    responses = {
        "/api/v0/devices/sw-1": {"status": "ok", "devices": [{"device_id": 17, "hostname": "sw-1"}]},
        "/api/v0/resources/sensors": {
            "status": "ok",
            "sensors": [
                {
                    "device_id": 17,
                    "sensor_type": "temperature",
                    "sensor_current": 41.5,
                    "sensor_oid": ".1.2.3",
                    "sensor_deleted": "0",
                },
                {"device_id": 18, "sensor_type": "temperature", "sensor_current": 9},
                {"device_id": 17, "sensor_type": "temperature", "sensor_current": 0, "sensor_deleted": 1},
            ],
        },
        "/api/v0/devices/sw-1/wireless-sensors": {"status": "ok", "wireless_sensors": []},
        "/api/v0/devices/sw-1/transceivers": {"status": "ok", "transceivers": []},
        "/api/v0/devices/sw-1/health/processor": {
            "status": "ok",
            "graphs": [{"sensor_id": 101, "sensor_descr": "CPU graph metadata"}],
        },
        "/api/v0/devices/sw-1/health/processor/101": {
            "status": "ok",
            "graphs": [{
                "processor_id": 101, "device_id": 17, "processor_usage": "37.5",
                "processor_descr": "CPU 1", "processor_type": "hr-device", "processor_index": "1",
                "lastupdate": "2026-10-07 09:00:00",
            }],
        },
        "/api/v0/devices/sw-1/health/mempool": {
            "status": "ok",
            "graphs": [{"sensor_id": 202, "desc": "System Memory"}],
        },
        "/api/v0/devices/sw-1/health/mempool/202": {
            "status": "ok",
            "graphs": [{
                "mempool_id": 202, "device_id": 17, "mempool_perc": "62",
                "mempool_descr": "System Memory", "mempool_class": "system",
                "mempool_used": 630, "mempool_total": 1000, "mempool_precision": 1,
                "lastupdate": "2026-10-07 09:00:00",
            }],
        },
        "/api/v0/devices/sw-1/health/storage": {"status": "ok", "graphs": []},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=responses[request.url.path])

    async def run() -> None:
        client = _client(handler)
        try:
            snapshot = await client.read_device_snapshot("sw-1")
        finally:
            await client.aclose()
        assert snapshot.device["device_id"] == 17
        assert len(snapshot.sensors) == 1
        assert snapshot.sensors[0]["sensor_current"] == 41.5
        assert snapshot.wireless_sensors == []
        assert snapshot.transceivers == []
        assert snapshot.processor_sensors == [{
            "processor_id": 101, "device_id": 17, "processor_usage": "37.5",
            "processor_descr": "CPU 1", "processor_type": "hr-device", "processor_index": "1",
            "lastupdate": "2026-10-07 09:00:00",
        }]
        assert snapshot.memory_pools == [{
            "mempool_id": 202, "device_id": 17, "mempool_perc": "62",
            "mempool_descr": "System Memory", "mempool_class": "system",
            "mempool_used": 630, "mempool_total": 1000, "mempool_precision": 1,
            "lastupdate": "2026-10-07 09:00:00",
        }]
        assert snapshot.health_graphs == {
            "processor": [{"sensor_id": 101, "sensor_descr": "CPU graph metadata"}],
            "mempool": [{"sensor_id": 202, "desc": "System Memory"}],
            "storage": [],
        }
        # The graph list is metadata; current values come from the documented
        # sensor-ID detail routes, not the graph name itself.
        assert "/api/v0/devices/sw-1/health/processor/101" in calls
        assert "/api/v0/devices/sw-1/health/mempool/202" in calls

    asyncio.run(run())


def test_snapshot_accepts_empty_optional_readings_and_health_metadata() -> None:
    responses = {
        "/api/v0/devices/sw-1": {"status": "ok", "devices": [{"device_id": 17, "hostname": "sw-1"}]},
        "/api/v0/resources/sensors": {"status": "ok", "sensors": []},
        "/api/v0/devices/sw-1/wireless-sensors": {"status": "ok", "wireless_sensors": []},
        "/api/v0/devices/sw-1/transceivers": {"status": "ok", "transceivers": []},
        "/api/v0/devices/sw-1/health/processor": {"status": "ok", "graphs": []},
        "/api/v0/devices/sw-1/health/mempool": {"status": "ok", "graphs": []},
        "/api/v0/devices/sw-1/health/storage": {"status": "ok", "graphs": []},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[request.url.path])

    async def run() -> None:
        client = _client(handler)
        try:
            snapshot = await client.read_device_snapshot("sw-1")
        finally:
            await client.aclose()
        assert snapshot.sensors == []
        assert snapshot.wireless_sensors == []
        assert snapshot.transceivers == []
        assert snapshot.health_graphs == {"processor": [], "mempool": [], "storage": []}

    asyncio.run(run())


def test_optional_collection_404_and_missing_collection_are_not_silently_empty() -> None:
    async def run() -> None:
        not_found = _client(lambda request: httpx.Response(404, json={"status": "error"}))
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await not_found.get_wireless_sensors("sw-1")
            assert exc_info.value.code == "http_error"
            assert exc_info.value.http_status == 404
        finally:
            await not_found.aclose()

        malformed = _client(lambda request: httpx.Response(200, json={"status": "ok"}))
        try:
            with pytest.raises(LibreNMSAPIError, match="unexpected_payload"):
                await malformed.get_all_sensors()
        finally:
            await malformed.aclose()

    asyncio.run(run())


def test_empty_native_device_response_is_not_found_but_auth_failure_is_not_swallowed() -> None:
    async def run() -> None:
        empty = _client(lambda request: httpx.Response(200, json={"status": "ok", "devices": []}))
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await empty.read_device_snapshot("unknown")
            assert exc_info.value.code == "native_device_not_found"
            assert exc_info.value.http_status == 404
        finally:
            await empty.aclose()

        unauthorized = _client(lambda request: httpx.Response(401, json={"status": "error"}))
        try:
            with pytest.raises(LibreNMSAPIError) as exc_info:
                await unauthorized.read_device_snapshot("sw-1")
            assert exc_info.value.code == "unauthorized"
        finally:
            await unauthorized.aclose()

    asyncio.run(run())
