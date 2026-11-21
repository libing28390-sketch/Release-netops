#!/usr/bin/env python3
"""Small dependency-free SNMPv2c simulator for the capacity lab.

The simulator intentionally implements only the read-only MIB surface used by
the checked-in ``capacity_ifmib`` exporter module.  It binds UDP sockets on
0.0.0.0, never opens an outbound connection, and serves the same deterministic
interface set on every configured port.

Supported operations are GET (A0), GETNEXT (A1), and GETBULK (A5).  Responses
use the standard GetResponse PDU (A2), preserve request IDs, and return
noSuchObject/endOfMibView for unsupported or exhausted OIDs.  Bulk responses
are capped to keep a single datagram well below the usual 1500-byte MTU.
"""

from __future__ import annotations

import argparse
import dataclasses
import socket
import struct
import threading
import time
from typing import Iterable, Optional, Sequence


DEFAULT_COMMUNITY = "capacity_lab_only"
DEFAULT_PORTS = (1161,)
MAX_BULK_REPETITIONS = 24
MAX_RESPONSE_BYTES = 1400

OID_SYS_DESCR = (1, 3, 6, 1, 2, 1, 1, 1, 0)
OID_SYS_UPTIME = (1, 3, 6, 1, 2, 1, 1, 3, 0)
OID_IF_TABLE = (1, 3, 6, 1, 2, 1, 2, 2, 1)
OID_IF_INDEX = OID_IF_TABLE + (1,)
OID_IF_DESCR = OID_IF_TABLE + (2,)
OID_IF_SPEED = OID_IF_TABLE + (5,)
OID_IF_OPER_STATUS = OID_IF_TABLE + (8,)
OID_IF_IN_OCTETS = OID_IF_TABLE + (10,)
OID_IF_OUT_OCTETS = OID_IF_TABLE + (16,)
OID_IF_HC_IN_OCTETS = OID_IF_TABLE + (31,)
OID_IF_HC_OUT_OCTETS = OID_IF_TABLE + (32,)

# Public catalogue consumed when the lab writes the snmp-exporter module.
# The required module walks the first three columns; the remaining columns are
# useful for local protocol tests and cost no extra target configuration.
CAPACITY_IFMIB_OIDS = {
    "ifIndex": OID_IF_INDEX,
    "ifInOctets": OID_IF_IN_OCTETS,
    "ifOutOctets": OID_IF_OUT_OCTETS,
}


class BerError(ValueError):
    pass


def _encode_length(length: int) -> bytes:
    if length < 0:
        raise ValueError("negative BER length")
    if length < 0x80:
        return bytes((length,))
    data = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes((0x80 | len(data),)) + data


def _decode_length(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        raise BerError("missing BER length")
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    count = first & 0x7F
    if count == 0 or count > 4 or offset + count > len(data):
        raise BerError("invalid BER length")
    length = int.from_bytes(data[offset : offset + count], "big")
    return length, offset + count


def tlv(tag: int, value: bytes) -> bytes:
    return bytes((tag,)) + _encode_length(len(value)) + value


def encode_integer(value: int) -> bytes:
    # BER INTEGER is signed.  Add a leading zero when the high bit would make
    # a positive value appear negative.
    if value == 0:
        raw = b"\x00"
    elif value > 0:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        if raw[0] & 0x80:
            raw = b"\x00" + raw
    else:
        size = max(1, (value.bit_length() + 8) // 8)
        raw = value.to_bytes(size, "big", signed=True)
        while len(raw) > 1 and ((raw[0] == 0xFF and raw[1] & 0x80) or (raw[0] == 0x00 and not raw[1] & 0x80)):
            raw = raw[1:]
    return tlv(0x02, raw)


def decode_integer(data: bytes) -> int:
    if not data:
        raise BerError("empty BER integer")
    return int.from_bytes(data, "big", signed=bool(data[0] & 0x80))


def encode_oid(oid: Sequence[int]) -> bytes:
    if len(oid) < 2 or oid[0] not in (0, 1, 2) or oid[1] < 0 or (oid[0] < 2 and oid[1] > 39):
        raise ValueError("invalid OID")
    output = bytearray()
    first = oid[0] * 40 + oid[1]
    values = (first, *oid[2:])
    for value in values:
        if value < 0:
            raise ValueError("negative OID component")
        parts = [value & 0x7F]
        value >>= 7
        while value:
            parts.append(value & 0x7F)
            value >>= 7
        for index in range(len(parts) - 1, -1, -1):
            output.append(parts[index] | (0x80 if index else 0))
    return tlv(0x06, bytes(output))


def decode_oid(data: bytes) -> tuple[int, ...]:
    if not data:
        raise BerError("empty OID")
    components: list[int] = []
    current = 0
    for byte in data:
        current = (current << 7) | (byte & 0x7F)
        if not byte & 0x80:
            components.append(current)
            current = 0
    if current:
        raise BerError("truncated OID")
    if not components:
        raise BerError("empty OID")
    first = components.pop(0)
    if first < 40:
        return (0, first, *components)
    if first < 80:
        return (1, first - 40, *components)
    return (2, first - 80, *components)


@dataclasses.dataclass(frozen=True)
class BerTlv:
    tag: int
    value: bytes
    end: int


def read_tlv(data: bytes, offset: int = 0) -> BerTlv:
    if offset >= len(data):
        raise BerError("missing BER tag")
    tag = data[offset]
    length, value_offset = _decode_length(data, offset + 1)
    end = value_offset + length
    if end > len(data):
        raise BerError("BER value exceeds packet")
    return BerTlv(tag, data[value_offset:end], end)


def sequence_items(data: bytes) -> list[BerTlv]:
    items: list[BerTlv] = []
    offset = 0
    while offset < len(data):
        item = read_tlv(data, offset)
        items.append(item)
        offset = item.end
    if offset != len(data):
        raise BerError("invalid BER sequence")
    return items


def _parse_varbinds(data: bytes) -> list[tuple[tuple[int, ...], int]]:
    outer = read_tlv(data)
    if outer.tag != 0x30 or outer.end != len(data):
        raise BerError("invalid variable binding list")
    result: list[tuple[tuple[int, ...], int]] = []
    for binding in sequence_items(outer.value):
        if binding.tag != 0x30:
            raise BerError("invalid variable binding")
        fields = sequence_items(binding.value)
        if len(fields) < 1 or fields[0].tag != 0x06:
            raise BerError("variable binding has no OID")
        result.append((decode_oid(fields[0].value), fields[1].tag if len(fields) > 1 else 0x05))
    return result


@dataclasses.dataclass(frozen=True)
class Request:
    version: int
    community: str
    pdu_tag: int
    request_id: int
    error_or_non_repeaters: int
    index_or_max_repetitions: int
    varbinds: tuple[tuple[int, ...], ...]


def parse_request(packet: bytes) -> Request:
    message = read_tlv(packet)
    if message.tag != 0x30 or message.end != len(packet):
        raise BerError("SNMP message is not a sequence")
    fields = sequence_items(message.value)
    if len(fields) != 3 or fields[0].tag != 0x02 or fields[1].tag != 0x04:
        raise BerError("invalid SNMP message header")
    pdu = fields[2]
    if pdu.tag not in (0xA0, 0xA1, 0xA5):
        raise BerError("unsupported SNMP PDU")
    pdu_fields = sequence_items(pdu.value)
    if len(pdu_fields) != 4 or any(field.tag != 0x02 for field in pdu_fields[:3]) or pdu_fields[3].tag != 0x30:
        raise BerError("invalid SNMP PDU")
    bindings = _parse_varbinds(tlv(pdu_fields[3].tag, pdu_fields[3].value))
    # The BER parser above returns value tags too; request OIDs are all that
    # matter for GET/GETNEXT/GETBULK.
    return Request(
        version=decode_integer(fields[0].value),
        community=fields[1].value.decode("utf-8", errors="replace"),
        pdu_tag=pdu.tag,
        request_id=decode_integer(pdu_fields[0].value),
        error_or_non_repeaters=decode_integer(pdu_fields[1].value),
        index_or_max_repetitions=decode_integer(pdu_fields[2].value),
        varbinds=tuple(item[0] for item in bindings),
    )


def encode_varbind(oid: Sequence[int], tag: int, value: bytes) -> bytes:
    return tlv(0x30, encode_oid(oid) + tlv(tag, value))


def _encode_varbind_list(bindings: Iterable[tuple[Sequence[int], int, bytes]]) -> bytes:
    return tlv(0x30, b"".join(encode_varbind(oid, tag, value) for oid, tag, value in bindings))


def encode_response(request: Request, bindings: Iterable[tuple[Sequence[int], int, bytes]]) -> bytes:
    varbind_list = _encode_varbind_list(bindings)
    pdu_body = encode_integer(request.request_id) + encode_integer(0) + encode_integer(0) + varbind_list
    pdu = tlv(0xA2, pdu_body)
    return tlv(0x30, encode_integer(request.version) + tlv(0x04, request.community.encode("utf-8")) + pdu)


def parse_response(packet: bytes) -> tuple[int, str, int, int, int, list[tuple[tuple[int, ...], int, bytes]]]:
    """Decode the response fields used by protocol tests and smoke clients."""

    message = read_tlv(packet)
    if message.tag != 0x30 or message.end != len(packet):
        raise BerError("SNMP response is not a sequence")
    fields = sequence_items(message.value)
    if len(fields) != 3 or fields[0].tag != 0x02 or fields[1].tag != 0x04 or fields[2].tag != 0xA2:
        raise BerError("invalid SNMP response header")
    pdu_fields = sequence_items(fields[2].value)
    if len(pdu_fields) != 4 or any(field.tag != 0x02 for field in pdu_fields[:3]) or pdu_fields[3].tag != 0x30:
        raise BerError("invalid SNMP response PDU")
    bindings: list[tuple[tuple[int, ...], int, bytes]] = []
    for binding in sequence_items(pdu_fields[3].value):
        if binding.tag != 0x30:
            raise BerError("invalid SNMP response variable binding")
        values = sequence_items(binding.value)
        if len(values) != 2 or values[0].tag != 0x06:
            raise BerError("invalid SNMP response variable binding fields")
        bindings.append((decode_oid(values[0].value), values[1].tag, values[1].value))
    return (
        decode_integer(fields[0].value),
        fields[1].value.decode("utf-8", errors="replace"),
        decode_integer(pdu_fields[0].value),
        decode_integer(pdu_fields[1].value),
        decode_integer(pdu_fields[2].value),
        bindings,
    )


def _oid_is_prefix(prefix: Sequence[int], oid: Sequence[int]) -> bool:
    return len(oid) >= len(prefix) and tuple(oid[: len(prefix)]) == tuple(prefix)


def _interface_oid(column: Sequence[int], index: int) -> tuple[int, ...]:
    return tuple(column) + (index,)


def _supported_oids(interfaces: int) -> list[tuple[int, ...]]:
    oids = [OID_SYS_DESCR, OID_SYS_UPTIME]
    for index in range(1, interfaces + 1):
        # The table ordering is column-major, as returned by a normal MIB
        # walker and by the Prometheus SNMP exporter.
        for column in (OID_IF_INDEX, OID_IF_DESCR, OID_IF_SPEED, OID_IF_OPER_STATUS, OID_IF_IN_OCTETS, OID_IF_OUT_OCTETS, OID_IF_HC_IN_OCTETS, OID_IF_HC_OUT_OCTETS):
            oids.append(_interface_oid(column, index))
    return sorted(oids)


def _counter_value(port: int, index: int, *, outbound: bool, wide: bool = False) -> int:
    elapsed = int(max(0.0, time.monotonic() - _START_TIME))
    base = (port * 10_000_000 + index * 100_000) % (2**32)
    rate = (index + 1) * (131 if outbound else 173)
    value = base + elapsed * rate
    return value % (2**64 if wide else 2**32)


def _value_for_oid(oid: Sequence[int], interfaces: int, port: int) -> Optional[tuple[int, bytes]]:
    oid = tuple(oid)
    if oid == OID_SYS_DESCR:
        return 0x04, b"Nexora capacity lab SNMP simulator"
    if oid == OID_SYS_UPTIME:
        return 0x43, struct.pack(">I", int((time.monotonic() - _START_TIME) * 100) & 0xFFFFFFFF)
    for index in range(1, interfaces + 1):
        if oid == _interface_oid(OID_IF_INDEX, index):
            return 0x02, encode_integer(index)[2:]
        if oid == _interface_oid(OID_IF_DESCR, index):
            return 0x04, f"capacity-eth{index - 1}".encode("ascii")
        if oid == _interface_oid(OID_IF_SPEED, index):
            return 0x42, (1_000_000_000).to_bytes(4, "big")
        if oid == _interface_oid(OID_IF_OPER_STATUS, index):
            return 0x02, encode_integer(1)[2:]
        if oid == _interface_oid(OID_IF_IN_OCTETS, index):
            return 0x41, _counter_value(port, index, outbound=False).to_bytes(4, "big")
        if oid == _interface_oid(OID_IF_OUT_OCTETS, index):
            return 0x41, _counter_value(port, index, outbound=True).to_bytes(4, "big")
        if oid == _interface_oid(OID_IF_HC_IN_OCTETS, index):
            return 0x46, _counter_value(port, index, outbound=False, wide=True).to_bytes(8, "big")
        if oid == _interface_oid(OID_IF_HC_OUT_OCTETS, index):
            return 0x46, _counter_value(port, index, outbound=True, wide=True).to_bytes(8, "big")
    return None


def next_oid(oid: Sequence[int], interfaces: int) -> Optional[tuple[int, ...]]:
    for candidate in _supported_oids(interfaces):
        if tuple(candidate) > tuple(oid):
            return candidate
    return None


def build_bindings(request: Request, *, interfaces: int, port: int) -> list[tuple[Sequence[int], int, bytes]]:
    supported = _supported_oids(interfaces)

    def one(oid: tuple[int, ...], *, get_next: bool) -> tuple[Sequence[int], int, bytes]:
        selected = next_oid(oid, interfaces) if get_next else oid
        if selected is None:
            return oid, 0x82, b""
        value = _value_for_oid(selected, interfaces, port)
        if value is None:
            return selected, 0x80, b""
        return selected, value[0], value[1]

    if request.pdu_tag == 0xA0:
        return [one(oid, get_next=False) for oid in request.varbinds]
    if request.pdu_tag == 0xA1:
        return [one(oid, get_next=True) for oid in request.varbinds]

    non_repeaters = max(0, min(request.error_or_non_repeaters, len(request.varbinds)))
    repetitions = max(0, min(request.index_or_max_repetitions, MAX_BULK_REPETITIONS))
    result: list[tuple[Sequence[int], int, bytes]] = []
    for oid in request.varbinds[:non_repeaters]:
        result.append(one(oid, get_next=True))
    repeaters = list(request.varbinds[non_repeaters:])
    current = [tuple(oid) for oid in repeaters]
    for _ in range(repetitions):
        next_round: list[tuple[int, ...]] = []
        for oid in current:
            selected = next_oid(oid, interfaces)
            if selected is None:
                result.append((oid, 0x82, b""))
            else:
                value = _value_for_oid(selected, interfaces, port)
                result.append((selected, value[0], value[1]) if value else (selected, 0x80, b""))
                next_round.append(selected)
        current = next_round
        if not current:
            break
    return result


class SimulatorServer:
    """Threaded UDP server used by the CLI and protocol tests."""

    def __init__(self, *, interfaces: int, ports: Sequence[int], community: str = DEFAULT_COMMUNITY, bind: str = "0.0.0.0") -> None:
        if interfaces < 1:
            raise ValueError("interfaces must be positive")
        if not ports or any(int(port) < 1 or int(port) > 65535 for port in ports):
            raise ValueError("ports must contain valid UDP ports")
        self.interfaces = int(interfaces)
        self.ports = tuple(int(port) for port in ports)
        # This lab simulator has a fixed, non-secret community.  Accepting a
        # CLI argument keeps command lines compatible with older harnesses but
        # never turns a user supplied secret into a credential.
        self.community = DEFAULT_COMMUNITY
        self.bind = bind
        self.stop_event = threading.Event()
        self.sockets: list[socket.socket] = []
        self.threads: list[threading.Thread] = []

    def _serve_socket(self, sock: socket.socket, port: int) -> None:
        sock.settimeout(0.4)
        while not self.stop_event.is_set():
            try:
                packet, address = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                return
            if not packet or len(packet) > 65507:
                continue
            try:
                request = parse_request(packet)
                if request.version != 1 or request.community != self.community:
                    continue
                bindings = build_bindings(request, interfaces=self.interfaces, port=port)
                response = encode_response(request, bindings)
                # GETBULK with a malicious repetition count is capped in
                # build_bindings; trim defensively if a future MIB extension
                # still creates a large packet.
                if len(response) > MAX_RESPONSE_BYTES and request.pdu_tag == 0xA5:
                    bindings = bindings[: max(1, len(bindings) // 2)]
                    response = encode_response(request, bindings)
                sock.sendto(response, address)
            except (BerError, ValueError, OSError):
                continue

    def start(self) -> None:
        if self.threads:
            return
        for port in self.ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.bind, port))
            self.sockets.append(sock)
            thread = threading.Thread(target=self._serve_socket, args=(sock, port), name=f"snmp-simulator-{port}", daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self) -> None:
        self.stop_event.set()
        for sock in self.sockets:
            with contextlib_suppress(OSError):
                sock.close()
        for thread in self.threads:
            thread.join(timeout=1.0)
        self.sockets.clear()
        self.threads.clear()

    def serve_forever(self) -> None:
        self.start()
        try:
            while not self.stop_event.wait(0.5):
                pass
        finally:
            self.close()


class contextlib_suppress:
    """Tiny local suppress context to keep this module's imports minimal."""

    def __init__(self, *exceptions: type[BaseException]) -> None:
        self.exceptions = exceptions

    def __enter__(self) -> "contextlib_suppress":
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc: Optional[BaseException], tb: object) -> bool:
        return exc_type is not None and issubclass(exc_type, self.exceptions)


def parse_ports(value: str) -> tuple[int, ...]:
    ports: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item or not item.isdigit():
            raise argparse.ArgumentTypeError("ports must be comma-separated integers")
        port = int(item)
        if not 1 <= port <= 65535:
            raise argparse.ArgumentTypeError("port is outside the valid range")
        ports.append(port)
    if not ports or len(set(ports)) != len(ports):
        raise argparse.ArgumentTypeError("ports must be non-empty and unique")
    return tuple(ports)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Nexora capacity SNMPv2c simulator")
    parser.add_argument("--interfaces", type=int, default=48)
    parser.add_argument("--ports", type=parse_ports, default=DEFAULT_PORTS)
    parser.add_argument("--community", default=DEFAULT_COMMUNITY, help="accepted for CLI compatibility; simulator uses capacity_lab_only")
    args = parser.parse_args(argv)
    if args.interfaces < 1:
        parser.error("--interfaces must be positive")
    server = SimulatorServer(interfaces=args.interfaces, ports=args.ports, community=args.community)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.close()
    return 0


_START_TIME = time.monotonic()


if __name__ == "__main__":
    raise SystemExit(main())
