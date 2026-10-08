from __future__ import annotations

import asyncio

import pytest

from services.snmp_service import (
    _SafeSNMPClientProtocol,
    _SNMP_TRANSPORT_RETRIES,
    _SNMP_TRANSPORT_TIMEOUT_SECONDS,
    _build_snmp_client,
)


class _FakeDatagramTransport:
    def __init__(self) -> None:
        self.close_calls = 0
        self.abort_calls = 0
        self.sent_packets: list[bytes] = []

    def sendto(self, packet: bytes) -> None:
        self.sent_packets.append(packet)

    def close(self) -> None:
        self.close_calls += 1

    def abort(self) -> None:
        self.abort_calls += 1


def test_late_datagram_does_not_set_completed_future_again() -> None:
    async def exercise() -> None:
        protocol = _SafeSNMPClientProtocol(b'request')
        transport = _FakeDatagramTransport()
        protocol.connection_made(transport)

        protocol.datagram_received(b'first-response', ('192.0.2.1', 161))
        assert await protocol.future == b'first-response'

        # This models a duplicate or late packet delivered after the request
        # Future has already completed.
        protocol.datagram_received(b'late-response', ('192.0.2.1', 161))

        assert not protocol.future.cancelled()
        assert protocol.future.result() == b'first-response'
        assert transport.close_calls == 2

    asyncio.run(exercise())


def test_external_cancellation_aborts_udp_transport() -> None:
    async def exercise() -> None:
        protocol = _SafeSNMPClientProtocol(b'request')
        transport = _FakeDatagramTransport()
        protocol.connection_made(transport)
        task = asyncio.create_task(protocol.get_data(timeout=10))
        await asyncio.sleep(0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert protocol.future.cancelled()
        assert transport.abort_calls == 1

        # A packet delivered after cancellation must be ignored.
        protocol.datagram_received(b'late-response', ('192.0.2.1', 161))

    asyncio.run(exercise())


def test_snmp_client_uses_bounded_internal_timeout_and_retries() -> None:
    from puresnmp import V2C

    client = _build_snmp_client('192.0.2.1', V2C('public'), 161)

    assert client.config.timeout == _SNMP_TRANSPORT_TIMEOUT_SECONDS
    assert client.config.retries == _SNMP_TRANSPORT_RETRIES


def test_snmpv3_get_uses_selected_authentication_and_privacy(monkeypatch) -> None:
    import puresnmp
    from puresnmp import V3
    from services import snmp_service

    observed: dict[str, object] = {}

    def fake_build_client(ip, credentials, port):
        observed["endpoint"] = (ip, port)
        observed["credentials"] = credentials
        return object()

    class FakeWrapper:
        def __init__(self, _client):
            pass

        async def get(self, oid):
            observed["oid"] = oid
            return b"device-name"

    monkeypatch.setattr(snmp_service, "_build_snmp_client", fake_build_client)
    monkeypatch.setattr(puresnmp, "PyWrapper", FakeWrapper)

    result = asyncio.run(snmp_service._snmp_get_v3(
        "192.0.2.1",
        "probe-user",
        "1.3.6.1.2.1.1.5.0",
        port=1161,
        auth_password="test-auth-key",
        auth_protocol="sha1",
        priv_password="test-privacy-key",
        priv_protocol="aes",
    ))

    credentials = observed["credentials"]
    assert isinstance(credentials, V3)
    assert credentials.username == "probe-user"
    assert credentials.auth is not None
    assert credentials.auth.method == "sha1"
    assert credentials.auth.key == b"test-auth-key"
    assert credentials.priv is not None
    assert credentials.priv.method == "aes"
    assert credentials.priv.key == b"test-privacy-key"
    assert observed["endpoint"] == ("192.0.2.1", 1161)
    assert observed["oid"] == "1.3.6.1.2.1.1.5.0"
    assert result == "device-name"
