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
