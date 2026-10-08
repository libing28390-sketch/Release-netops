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


@pytest.mark.parametrize("version", ["1", "2c", "3"])
def test_known_instance_gets_are_batched_and_keep_selected_version(monkeypatch, version) -> None:
    import puresnmp
    from services import snmp_service

    builds = []
    requests = []
    credentials = {"username": "test-user", "security_level": "noAuthNoPriv"} if version == "3" else "test-community"

    def build(ip, profile, port, selected_version):
        builds.append((ip, profile, port, selected_version))
        return object()

    class Wrapper:
        def __init__(self, _client):
            pass

        async def multiget(self, oids):
            requests.append(oids)
            return [42 if not oid.endswith('.0') else None for oid in oids]

    monkeypatch.setattr(snmp_service, "_build_versioned_snmp_client", build)
    monkeypatch.setattr(puresnmp, "PyWrapper", Wrapper)
    oids = [f"1.3.6.1.2.1.1.{i}" for i in range(45)]
    result = asyncio.run(snmp_service._snmp_get_many_versioned("192.0.2.1", credentials, oids + oids[:2], 1161, version))

    assert sorted(map(len, requests)) == [5, 20, 20]
    assert all(build == ("192.0.2.1", credentials, 1161, version) for build in builds)
    assert len(result) == 45
    assert result[oids[0]] is None
    assert all(result[oid] == "42" for oid in oids[1:])


def test_v1_missing_instance_does_not_discard_other_get_results(monkeypatch) -> None:
    import puresnmp
    from puresnmp.exc import NoSuchOID
    from services import snmp_service

    class Wrapper:
        def __init__(self, _client):
            pass

        async def multiget(self, oids):
            if any(oid.endswith('.2') for oid in oids):
                raise NoSuchOID(None)
            return [7 for _ in oids]

    monkeypatch.setattr(snmp_service, "_build_versioned_snmp_client", lambda *_: object())
    monkeypatch.setattr(puresnmp, "PyWrapper", Wrapper)
    result = asyncio.run(snmp_service._snmp_get_many_versioned(
        "192.0.2.1", "test-community", ["1.3.6.1.2.1.1.1", "1.3.6.1.2.1.1.2", "1.3.6.1.2.1.1.3"], 161, "1",
    ))
    assert list(result.values()) == ["7", None, "7"]


def test_get_timeout_does_not_fan_out_to_individual_sensor_requests(monkeypatch) -> None:
    import puresnmp
    from services import snmp_service

    requests = []

    class Wrapper:
        def __init__(self, _client):
            pass

        async def multiget(self, oids):
            requests.append(oids)
            raise TimeoutError("test timeout")

    monkeypatch.setattr(snmp_service, "_build_versioned_snmp_client", lambda *_: object())
    monkeypatch.setattr(puresnmp, "PyWrapper", Wrapper)
    oids = [f"1.3.6.1.2.1.1.{i}" for i in range(40)]
    result = asyncio.run(snmp_service._snmp_get_many_versioned("192.0.2.1", "test-community", oids, 161, "2c"))
    assert len(requests) == 2
    assert set(result.values()) == {None}


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


def test_snmpv3_walk_uses_bound_profile_context_and_authentication(monkeypatch) -> None:
    from types import SimpleNamespace

    import puresnmp
    from puresnmp import V3
    from services import snmp_service

    observed: dict[str, object] = {}

    def fake_build_client(ip, credentials, port, **kwargs):
        observed["endpoint"] = (ip, port)
        observed["credentials"] = credentials
        observed["context_name"] = kwargs.get("context_name", b"")
        return object()

    class FakeWrapper:
        def __init__(self, _client):
            pass

        async def walk(self, oid):
            observed["oid"] = str(oid)
            yield SimpleNamespace(oid=f"{oid}.0", value=42)

    monkeypatch.setattr(snmp_service, "_build_snmp_client", fake_build_client)
    monkeypatch.setattr(puresnmp, "PyWrapper", FakeWrapper)

    profile = {
        "version": "3",
        "username": "probe-user",
        "security_level": "authPriv",
        "auth_protocol": "SHA",
        "auth_password": "test-auth-key",
        "priv_protocol": "AES",
        "priv_password": "test-privacy-key",
        "context_name": "tenant-a",
    }
    rows = asyncio.run(snmp_service._snmp_walk(
        "192.0.2.1",
        profile,
        "1.3.6.1.2.1.1",
        port=1161,
        version="3",
        raise_on_error=True,
    ))

    credentials = observed["credentials"]
    assert isinstance(credentials, V3)
    assert credentials.username == "probe-user"
    assert credentials.auth is not None and credentials.auth.method == "sha1"
    assert credentials.priv is not None and credentials.priv.method == "aes"
    assert observed["context_name"] == b"tenant-a"
    assert observed["endpoint"] == ("192.0.2.1", 1161)
    assert observed["oid"] == "1.3.6.1.2.1.1"
    assert rows == [("0", "42")]


@pytest.mark.parametrize(
    ("security_level", "auth_present", "priv_present"),
    [
        ("noAuthNoPriv", False, False),
        ("authNoPriv", True, False),
        ("authPriv", True, True),
    ],
)
def test_snmpv3_security_levels_map_to_expected_usm_options(
    security_level: str,
    auth_present: bool,
    priv_present: bool,
) -> None:
    from services.snmp_service import _snmpv3_credentials

    credentials, context = _snmpv3_credentials({
        "username": "probe-user",
        "security_level": security_level,
        "auth_protocol": "SHA",
        "auth_password": "test-auth-key",
        "priv_protocol": "AES",
        "priv_password": "test-privacy-key",
        "context_name": "",
    })

    assert (credentials.auth is not None) is auth_present
    assert (credentials.priv is not None) is priv_present
    assert context == b""


def test_snmpv3_rejects_algorithms_not_implemented_by_the_transport() -> None:
    from services.snmp_service import _snmpv3_credentials

    with pytest.raises(ValueError, match="Unsupported SNMPv3 authentication protocol"):
        _snmpv3_credentials({
            "username": "probe-user",
            "security_level": "authNoPriv",
            "auth_protocol": "SHA-1024",
            "auth_password": "test-auth-key",
        })


@pytest.mark.parametrize(
    ("algorithm", "plugin", "digest_length"),
    [
        ("SHA-224", "sha224", 16),
        ("SHA-256", "sha256", 24),
        ("SHA-384", "sha384", 32),
        ("SHA-512", "sha512", 48),
    ],
)
def test_snmpv3_sha2_auth_plugins_follow_rfc7860(
    algorithm: str,
    plugin: str,
    digest_length: int,
) -> None:
    from puresnmp.plugins.auth import create
    from services.snmp_service import _snmpv3_credentials

    credentials, _ = _snmpv3_credentials({
        "username": "probe-user",
        "security_level": "authNoPriv",
        "auth_protocol": algorithm,
        "auth_password": "test-auth-key",
    })
    assert credentials.auth is not None
    assert credentials.auth.method == plugin

    auth_plugin = create(plugin)
    message = b"snmpv3-auth-test"
    digest = auth_plugin.authenticate_outgoing_message(
        credentials.auth.key,
        message,
        b"engine-id",
    )
    assert len(digest) == digest_length
    assert auth_plugin.authenticate_incoming_message(
        credentials.auth.key,
        message,
        digest,
        b"engine-id",
    )
