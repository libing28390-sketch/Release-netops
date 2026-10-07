from __future__ import annotations

import asyncio
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
