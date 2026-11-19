"""Small protobuf wire reader for the vendor Dial-out envelope messages.

The collector only needs the stable envelope fields. Business payloads stay
JSON and are validated separately; this avoids generated-code drift while
keeping the checked-in vendor ``.proto`` contracts reviewable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


class ProtobufWireError(ValueError):
    pass


@dataclass(frozen=True)
class WireField:
    number: int
    wire_type: int
    value: int | bytes


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift < 70:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ProtobufWireError("invalid protobuf varint")


def fields(data: bytes, *, maximum_bytes: int = 4 * 1024 * 1024) -> Iterator[WireField]:
    """Yield protobuf scalar and length-delimited fields with strict bounds."""
    if not isinstance(data, bytes) or len(data) > maximum_bytes:
        raise ProtobufWireError("protobuf envelope exceeds the configured size limit")
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire_type = tag >> 3, tag & 7
        if number <= 0:
            raise ProtobufWireError("protobuf field number must be positive")
        if wire_type == 0:
            value, offset = _varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ProtobufWireError("truncated fixed64 protobuf field")
            value, offset = data[offset:end], end
        elif wire_type == 2:
            size, offset = _varint(data, offset)
            end = offset + size
            if end > len(data):
                raise ProtobufWireError("truncated length-delimited protobuf field")
            value, offset = data[offset:end], end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ProtobufWireError("truncated fixed32 protobuf field")
            value, offset = data[offset:end], end
        else:
            raise ProtobufWireError(f"unsupported protobuf wire type {wire_type}")
        yield WireField(number=number, wire_type=wire_type, value=value)


def _first_text(data: bytes, field_number: int, *, maximum: int = 4096) -> str:
    for field in fields(data, maximum_bytes=maximum):
        if field.number == field_number and field.wire_type == 2:
            try:
                return bytes(field.value).decode("utf-8").strip()
            except UnicodeDecodeError as exc:
                raise ProtobufWireError("protobuf string field is not valid UTF-8") from exc
    return ""


def _all_bytes(data: bytes, field_number: int, *, maximum: int = 4 * 1024 * 1024) -> list[bytes]:
    return [bytes(field.value) for field in fields(data, maximum_bytes=maximum)
            if field.number == field_number and field.wire_type == 2]


def decode_huawei_service_args(data: bytes) -> tuple[str, bytes]:
    """Return the selected JSON value from Huawei ``serviceArgs`` oneof."""
    selected_json: bytes | None = None
    selected_binary = False
    for field in fields(data):
        if field.number in (4, 6) and field.wire_type == 2:
            selected_json = bytes(field.value)
            selected_binary = False
        elif field.number in (2, 5) and field.wire_type == 2:
            selected_binary = True
            selected_json = None
    if selected_binary:
        raise ProtobufWireError("Huawei GPB payload is not enabled; use the approved JSON Dial-out profile")
    if selected_json is None:
        raise ProtobufWireError("Huawei serviceArgs does not contain data_json or packed_data_json")
    return "packed_data_json" if any(f.number == 6 for f in fields(data)) else "data_json", selected_json


def decode_h3c_v2_dialout(data: bytes) -> tuple[str, str, str, bytes]:
    """Decode H3C ``grpc_dialout.DialoutMsg`` and return identity/path/JSON."""
    device_message = next((bytes(field.value) for field in fields(data)
                           if field.number == 1 and field.wire_type == 2), b"")
    path = _first_text(data, 2)
    body = next((bytes(field.value) for field in fields(data)
                 if field.number == 3 and field.wire_type == 2), b"")
    producer = _first_text(device_message, 1)
    device_name = _first_text(device_message, 2)
    if not path or not body:
        raise ProtobufWireError("H3C DialoutMsg is missing sensorPath or jsonData")
    return producer, device_name, path, body


def decode_h3c_v3_payload(data: bytes) -> list[tuple[str, bytes]]:
    """Return opaque Telemetry records from H3C ``DialoutV3Args.data``.

    The data member contains a version-specific three-layer Telemetry protobuf
    whose application body schema is model-specific. This bounded envelope
    extractor deliberately refuses to guess the inner schema. A versioned
    profile must provide a reviewed decoder before records can be normalized.
    """
    packed = next((bytes(field.value) for field in fields(data)
                   if field.number == 2 and field.wire_type == 2), b"")
    if not packed:
        raise ProtobufWireError("H3C DialoutV3Args has no telemetry data")
    if len(packed) > 4 * 1024 * 1024:
        raise ProtobufWireError("H3C three-layer payload exceeds the message limit")
    records = _all_bytes(packed, 1)
    if not records:
        records = [packed]
    return [("telemetry-v3-unmapped", record) for record in records]


def decode_h3c_v3_envelope(data: bytes) -> tuple[int, int, bytes]:
    """Decode one bounded gRPC v3 frame before optional message reassembly."""
    request_id = 0
    total_size = 0
    packed = b""
    for field in fields(data):
        if field.number == 1 and field.wire_type == 0:
            request_id = int(field.value)
        elif field.number == 2 and field.wire_type == 2:
            packed = bytes(field.value)
        elif field.number == 4 and field.wire_type == 0:
            total_size = int(field.value)
    if not packed:
        raise ProtobufWireError("H3C v3 data field is missing")
    return request_id, total_size, packed


def decode_h3c_v3_data(packed: bytes) -> list[tuple[str, Any, bytes]]:
    """Decode a complete telemetry.TelemetryPacked JSON data payload."""
    telemetry_records = _all_bytes(packed, 1)
    if not telemetry_records:
        telemetry_records = [packed]
    result: list[tuple[str, Any, bytes]] = []
    for record in telemetry_records:
        path = _first_text(record, 16)
        timestamp = next((int(field.value) for field in fields(record)
                          if field.number == 19 and field.wire_type == 0), None)
        data_json = next((bytes(field.value) for field in fields(record)
                          if field.number == 24 and field.wire_type == 2), b"")
        if not data_json:
            raise ProtobufWireError("H3C v3 Telemetry record has no JSON data_str")
        if not path:
            raise ProtobufWireError("H3C v3 Telemetry record has no sensor_path")
        result.append((path, timestamp, data_json))
    return result


def decode_h3c_v3_json(data: bytes) -> tuple[int, int, list[tuple[str, Any, bytes]]]:
    request_id, total_size, packed = decode_h3c_v3_envelope(data)
    return request_id, total_size, decode_h3c_v3_data(packed)


def encode_h3c_v2_response(message: str = "accepted") -> bytes:
    encoded = message.encode("utf-8")
    return bytes((0x0A, len(encoded))) + encoded


def encode_huawei_service_args(message: str = "accepted") -> bytes:
    del message
    return b""


def encode_h3c_v3_response(request_id: int) -> bytes:
    if not request_id:
        return b""
    value = int(request_id)
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return b"\x08" + bytes(encoded)
