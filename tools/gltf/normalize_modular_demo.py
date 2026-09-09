#!/usr/bin/env python3
"""Normalize the external modular-switch GLB demo for Nexora.

The demo in ``D:/data/downloads`` is useful as a slot/FRU proof of concept,
but it was exported with Y-up/Z-front coordinates and mesh-only metadata.  The
RackVision runtime expects X=left/right, Y=front/back, Z=vertical, semantic
node extras, normals and UVs.  This dependency-free converter keeps the
original files untouched and writes a separate ``modular_demo`` draft set.

It deliberately does not claim OEM accuracy or promote the output to the
approved registry.  The output is a normalized, inspectable hand-off for the
next visual review.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import struct
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.1"
COMPONENT_SIZE = {
    5120: 1,  # BYTE
    5121: 1,  # UNSIGNED_BYTE
    5122: 2,  # SHORT
    5123: 2,  # UNSIGNED_SHORT
    5125: 4,  # UNSIGNED_INT
    5126: 4,  # FLOAT
}
COMPONENT_FORMAT = {
    5120: "b",
    5121: "B",
    5122: "h",
    5123: "H",
    5125: "I",
    5126: "f",
}
TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


FILE_META: dict[str, dict[str, Any]] = {
    "core_switch_chassis_8slot.glb": {
        "asset_key": "generic_modular_switch_chassis_8slot",
        "model": "Nexora Modular Core Switch Chassis 8-Slot Demo",
        "asset_kind": "device",
        "role": "modular_switch_chassis",
    },
    "core_switch_assembled_demo.glb": {
        "asset_key": "generic_modular_switch_assembled_demo",
        "model": "Nexora Modular Core Switch Assembled Demo",
        "asset_kind": "device",
        "role": "modular_switch",
    },
    "module_linecard_48ge.glb": {
        "asset_key": "generic_modular_linecard_48ge",
        "model": "Nexora Modular 48GE Line Card Demo",
        "asset_kind": "device",
        "role": "linecard",
    },
    "module_linecard_24sfp.glb": {
        "asset_key": "generic_modular_linecard_24sfp",
        "model": "Nexora Modular 24SFP Line Card Demo",
        "asset_kind": "device",
        "role": "linecard",
    },
    "module_supervisor.glb": {
        "asset_key": "generic_modular_supervisor",
        "model": "Nexora Modular Supervisor Module Demo",
        "asset_kind": "device",
        "role": "supervisor",
    },
    "module_psu_ac.glb": {
        "asset_key": "generic_modular_psu_ac",
        "model": "Nexora Modular AC PSU Demo",
        "asset_kind": "device",
        "role": "power_module",
    },
    "module_fan_tray.glb": {
        "asset_key": "generic_modular_fan_tray",
        "model": "Nexora Modular Fan Tray Demo",
        "asset_kind": "device",
        "role": "fan_tray",
    },
    "module_blank_panel.glb": {
        "asset_key": "generic_modular_blank_panel",
        "model": "Nexora Modular Blank Panel Demo",
        "asset_kind": "device",
        "role": "blank_panel",
    },
}


MATERIALS = [
    {
        "name": "MAT_CHASSIS",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.12, 0.14, 0.17, 1.0],
            "metallicFactor": 0.72,
            "roughnessFactor": 0.42,
        },
    },
    {
        "name": "MAT_FRONT_PANEL",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.04, 0.055, 0.07, 1.0],
            "metallicFactor": 0.62,
            "roughnessFactor": 0.34,
        },
    },
    {
        "name": "MAT_BRUSHED_STEEL",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.42, 0.48, 0.54, 1.0],
            "metallicFactor": 0.88,
            "roughnessFactor": 0.28,
        },
    },
    {
        "name": "MAT_PORT",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.025, 0.035, 0.045, 1.0],
            "metallicFactor": 0.46,
            "roughnessFactor": 0.28,
        },
    },
    {
        "name": "MAT_SOCKET_BLACK",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.006, 0.009, 0.014, 1.0],
            "metallicFactor": 0.22,
            "roughnessFactor": 0.24,
        },
    },
    {
        "name": "MAT_LABEL",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.70, 0.78, 0.84, 1.0],
            "metallicFactor": 0.20,
            "roughnessFactor": 0.30,
        },
    },
    {
        "name": "MAT_LED_GREEN",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.02, 0.56, 0.28, 1.0],
            "metallicFactor": 0.12,
            "roughnessFactor": 0.18,
        },
        "emissiveFactor": [0.02, 1.0, 0.20],
    },
    {
        "name": "MAT_LED_AMBER",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.70, 0.26, 0.02, 1.0],
            "metallicFactor": 0.12,
            "roughnessFactor": 0.18,
        },
        "emissiveFactor": [1.0, 0.25, 0.02],
    },
]


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_glb(path: Path) -> tuple[dict[str, Any], bytearray]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"{path} is not a glTF 2.0 binary")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2 or total_length > len(data):
        raise ValueError(f"{path} has invalid GLB header")
    offset = 12
    document: dict[str, Any] | None = None
    binary = bytearray()
    while offset + 8 <= total_length:
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == 0x4E4F534A:  # JSON
            document = json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
        elif chunk_type == 0x004E4942:  # BIN\x00
            binary = bytearray(chunk)
    if document is None:
        raise ValueError(f"{path} has no JSON chunk")
    return document, binary


def write_glb(document: dict[str, Any], binary: bytearray, path: Path) -> bytes:
    document.setdefault("buffers", [{}])
    document["buffers"][0]["byteLength"] = len(binary)
    json_bytes = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (_align4(len(json_bytes)) - len(json_bytes))
    bin_bytes = bytes(binary) + b"\x00" * (_align4(len(binary)) - len(binary))
    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    output = bytearray(struct.pack("<4sII", b"glTF", 2, total_length))
    output.extend(struct.pack("<II", len(json_bytes), 0x4E4F534A))
    output.extend(json_bytes)
    output.extend(struct.pack("<II", len(bin_bytes), 0x004E4942))
    output.extend(bin_bytes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)
    return bytes(output)


def _accessor_layout(document: dict[str, Any], accessor_index: int) -> tuple[int, int, int, int, str]:
    accessor = document["accessors"][accessor_index]
    component_type = int(accessor["componentType"])
    component_size = COMPONENT_SIZE[component_type]
    component_count = TYPE_COMPONENTS[accessor["type"]]
    view = document["bufferViews"][accessor["bufferView"]]
    packed_size = component_size * component_count
    stride = int(view.get("byteStride") or packed_size)
    start = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0)
    return start, stride, component_type, component_count, COMPONENT_FORMAT[component_type]


def read_accessor(document: dict[str, Any], binary: bytearray, accessor_index: int) -> list[tuple[float, ...]]:
    accessor = document["accessors"][accessor_index]
    count = int(accessor.get("count") or 0)
    if "bufferView" not in accessor:
        return [tuple(0.0 for _ in range(TYPE_COMPONENTS[accessor["type"]])) for _ in range(count)]
    start, stride, _, component_count, component_format = _accessor_layout(document, accessor_index)
    component_size = struct.calcsize("<" + component_format)
    result: list[tuple[float, ...]] = []
    for index in range(count):
        item_start = start + index * stride
        values = struct.unpack_from(
            "<" + component_format * component_count,
            binary,
            item_start,
        )
        result.append(tuple(float(value) for value in values))
        if item_start + component_size * component_count > len(binary):
            raise ValueError(f"accessor {accessor_index} reads beyond BIN chunk")
    return result


def write_accessor(document: dict[str, Any], binary: bytearray, accessor_index: int, values: Iterable[tuple[float, ...]]) -> None:
    accessor = document["accessors"][accessor_index]
    start, stride, component_type, component_count, component_format = _accessor_layout(document, accessor_index)
    values_list = list(values)
    if len(values_list) != int(accessor.get("count") or 0):
        raise ValueError(f"accessor {accessor_index} value count changed")
    for index, value in enumerate(values_list):
        item_start = start + index * stride
        cast_values: list[int | float] = []
        for item in value[:component_count]:
            cast_values.append(int(round(item)) if component_type != 5126 else float(item))
        struct.pack_into("<" + component_format * component_count, binary, item_start, *cast_values)
    if values_list:
        mins = [min(row[i] for row in values_list) for i in range(component_count)]
        maxs = [max(row[i] for row in values_list) for i in range(component_count)]
        accessor["min"] = mins
        accessor["max"] = maxs


def append_float_accessor(
    document: dict[str, Any],
    binary: bytearray,
    values: Iterable[tuple[float, ...]],
    accessor_type: str,
) -> int:
    values_list = list(values)
    component_count = TYPE_COMPONENTS[accessor_type]
    offset = _align4(len(binary))
    binary.extend(b"\x00" * (offset - len(binary)))
    raw = bytearray()
    for value in values_list:
        raw.extend(struct.pack("<" + "f" * component_count, *[float(x) for x in value]))
    binary.extend(raw)
    view_index = len(document.setdefault("bufferViews", []))
    document["bufferViews"].append({
        "buffer": 0,
        "byteOffset": offset,
        "byteLength": len(raw),
        "target": 34962,
    })
    accessor_index = len(document.setdefault("accessors", []))
    mins = [min(row[i] for row in values_list) for i in range(component_count)] if values_list else [0.0] * component_count
    maxs = [max(row[i] for row in values_list) for i in range(component_count)] if values_list else [0.0] * component_count
    document["accessors"].append({
        "bufferView": view_index,
        "componentType": 5126,
        "count": len(values_list),
        "type": accessor_type,
        "min": mins,
        "max": maxs,
    })
    return accessor_index


def _position_bounds(values: list[tuple[float, ...]]) -> tuple[list[float], list[float]]:
    if not values:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    mins = [min(row[i] for row in values) for i in range(3)]
    maxs = [max(row[i] for row in values) for i in range(3)]
    return mins, maxs


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(item * item for item in value))
    if length < 1e-9:
        return (0.0, 0.0, 1.0)
    return tuple(item / length for item in value)


def _mesh_bounds(document: dict[str, Any], binary: bytearray, mesh_index: int) -> tuple[list[float], list[float]]:
    mesh = document["meshes"][mesh_index]
    positions: list[tuple[float, ...]] = []
    for primitive in mesh.get("primitives", []):
        position_accessor = primitive.get("attributes", {}).get("POSITION")
        if position_accessor is not None:
            positions.extend(read_accessor(document, binary, int(position_accessor)))
    return _position_bounds(positions)


def _is_index_accessor(document: dict[str, Any], accessor_index: int) -> bool:
    accessor = document["accessors"][accessor_index]
    return accessor.get("type") == "SCALAR" and int(accessor.get("componentType") or 0) in {5121, 5123, 5125}


def _reverse_triangle_order(document: dict[str, Any], binary: bytearray, accessor_index: int) -> None:
    values = read_accessor(document, binary, accessor_index)
    reversed_values = list(values)
    for offset in range(0, len(reversed_values) - 2, 3):
        reversed_values[offset + 1], reversed_values[offset + 2] = reversed_values[offset + 2], reversed_values[offset + 1]
    write_accessor(document, binary, accessor_index, reversed_values)


def _normalize_geometry(document: dict[str, Any], binary: bytearray) -> dict[str, Any]:
    """Swap Y/Z, move to bottom/front origin, add normals and UVs."""

    position_accessors: set[int] = set()
    primitives: list[tuple[dict[str, Any], int]] = []
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            accessor_index = primitive.get("attributes", {}).get("POSITION")
            if accessor_index is not None:
                accessor_index = int(accessor_index)
                position_accessors.add(accessor_index)
                primitives.append((primitive, accessor_index))
    source_positions = {index: read_accessor(document, binary, index) for index in position_accessors}
    all_source = [point for values in source_positions.values() for point in values]
    source_min, source_max = _position_bounds(all_source)
    center_x = (source_min[0] + source_max[0]) / 2.0
    # Source manifest: X=right, Y=up, Z=front. Target: X=right,
    # Y=front, Z=up.  The swap has determinant -1, so indexed triangles are
    # reversed below to preserve outward-facing normals.
    transformed: dict[int, list[tuple[float, float, float]]] = {}
    for accessor_index, values in source_positions.items():
        transformed_values = [
            (point[0] - center_x, point[2] - source_max[2], point[1] - source_min[1])
            for point in values
        ]
        transformed[accessor_index] = transformed_values
        write_accessor(document, binary, accessor_index, transformed_values)

    reversed_indices: set[int] = set()
    for primitive, _ in primitives:
        if int(primitive.get("mode") or 4) != 4:
            continue
        index_accessor = primitive.get("indices")
        if index_accessor is not None:
            index_accessor = int(index_accessor)
            if index_accessor not in reversed_indices and _is_index_accessor(document, index_accessor):
                _reverse_triangle_order(document, binary, index_accessor)
                reversed_indices.add(index_accessor)

    normal_accum: dict[int, list[list[float]]] = {
        accessor_index: [[0.0, 0.0, 0.0] for _ in values]
        for accessor_index, values in transformed.items()
    }
    uv_values: dict[int, list[tuple[float, float]]] = {}
    for accessor_index, values in transformed.items():
        mins, maxs = _position_bounds(values)
        span_x = max(maxs[0] - mins[0], 1e-6)
        span_z = max(maxs[2] - mins[2], 1e-6)
        uv_values[accessor_index] = [
            ((point[0] - mins[0]) / span_x, (point[2] - mins[2]) / span_z)
            for point in values
        ]

    normal_accessors: dict[int, int] = {}
    texcoord_accessors: dict[int, int] = {}
    for primitive, position_accessor in primitives:
        indices = read_accessor(document, binary, int(primitive["indices"])) if primitive.get("indices") is not None else [
            (float(index),) for index in range(len(transformed[position_accessor]))
        ]
        index_values = [int(round(row[0])) for row in indices]
        if primitive.get("indices") is None:
            for offset in range(0, len(index_values) - 2, 3):
                index_values[offset + 1], index_values[offset + 2] = index_values[offset + 2], index_values[offset + 1]
        points = transformed[position_accessor]
        for offset in range(0, len(index_values) - 2, 3):
            a, b, c = (index_values[offset], index_values[offset + 1], index_values[offset + 2])
            if max(a, b, c) >= len(points):
                continue
            p0, p1, p2 = points[a], points[b], points[c]
            edge1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            edge2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
            normal = _cross(edge1, edge2)
            for vertex in (a, b, c):
                normal_accum[position_accessor][vertex][0] += normal[0]
                normal_accum[position_accessor][vertex][1] += normal[1]
                normal_accum[position_accessor][vertex][2] += normal[2]
        if position_accessor not in normal_accessors:
            normal_accessors[position_accessor] = append_float_accessor(
                document,
                binary,
                [_normalize(tuple(value)) for value in normal_accum[position_accessor]],
                "VEC3",
            )
        if position_accessor not in texcoord_accessors:
            texcoord_accessors[position_accessor] = append_float_accessor(
                document,
                binary,
                uv_values[position_accessor],
                "VEC2",
            )
        primitive.setdefault("attributes", {})["NORMAL"] = normal_accessors[position_accessor]
        primitive.setdefault("attributes", {})["TEXCOORD_0"] = texcoord_accessors[position_accessor]

    document.setdefault("buffers", [{}])[0]["byteLength"] = len(binary)
    transformed_all = [point for values in transformed.values() for point in values]
    normalized_min, normalized_max = _position_bounds(transformed_all)
    return {
        "source_bounds_m": {"min": source_min, "max": source_max},
        "normalized_bounds_m": {"min": normalized_min, "max": normalized_max},
        "position_accessors": len(position_accessors),
        "normal_accessors": len(normal_accessors),
        "texcoord_accessors": len(texcoord_accessors),
        "reversed_index_accessors": len(reversed_indices),
    }


def _common_extras(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_key": meta["asset_key"],
        "vendor": "generic",
        "exact_model": meta["model"],
        "coordinate_system": "X=left_right,Y=front_back,Z=vertical",
        "front_direction": "+Y",
        "unit": "meter",
        "schema_version": SCHEMA_VERSION,
        "lod": "LOD0",
        "asset_kind": meta["asset_kind"],
        "source_export": "nexora_modular_switch_glb_demo",
    }


def _port_info(name: str) -> tuple[str, int, str] | None:
    match = re.search(r"^(?:(SLOT\d+)_)?(?:linecard_[^_]+_)?(GE|SFP)_(\d+)$", name, re.IGNORECASE)
    if not match:
        return None
    slot = match.group(1) or ""
    token = match.group(2).upper()
    return slot, int(match.group(3)), token


def _port_led_info(name: str) -> tuple[str, int] | None:
    match = re.search(r"^(?:(SLOT\d+)_)?(?:linecard_[^_]+_)?LED_(\d+)$", name, re.IGNORECASE)
    if not match:
        return None
    return match.group(1) or "", int(match.group(2))


def _classify_node(name: str, meta: dict[str, Any]) -> tuple[str, dict[str, Any], bool, str | None]:
    """Return (new name, extras, is_empty_anchor, port_anchor_name)."""

    upper = name.upper()
    extras = _common_extras(meta)
    new_name = name
    is_empty_anchor = False
    port_anchor_name: str | None = None

    slot_match = re.match(r"^(SLOT_?\d+)_ANCHOR$", upper)
    if upper in {"WORLD", "SCENE"}:
        return "ASSET_ROOT", {**extras, "component_type": "asset_root", "asset_origin": "BOTTOM_FRONT_CENTER"}, False, None
    if slot_match:
        slot = slot_match.group(1).replace("_", "")
        return f"{slot}_ANCHOR", {**extras, "component_type": "semantic_anchor", "anchor_type": "slot_insert", "slot_id": slot, "source_name": name}, True, None

    port = _port_info(name)
    if port:
        slot, index, token = port
        slot_prefix = f"{slot}_" if slot else ""
        new_name = f"{slot_prefix}PORT_{token}_{index:03d}"
        port_anchor_name = f"PORT_ANCHOR_FRONT_{slot_prefix}{index:03d}"
        port_group = f"{slot}_SERVICE" if slot else "SERVICE"
        extras.update({
            "component_type": "port_cage",
            "port_index": index,
            "port_media_type": "sfp" if token == "SFP" else "copper",
            "port_group": port_group,
            "connection_face": "front",
            "connection_anchor": port_anchor_name,
            "port_slot": slot or None,
            "source_name": name,
        })
        return new_name, extras, False, port_anchor_name

    led_port = _port_led_info(name)
    if led_port and "STATUS" not in upper:
        slot, index = led_port
        slot_prefix = f"{slot}_" if slot else ""
        new_name = f"{slot_prefix}PORT_LED_{index:03d}"
        port_anchor_name = f"PORT_ANCHOR_FRONT_{slot_prefix}{index:03d}"
        extras.update({
            "component_type": "port_led",
            "port_index": index,
            "port_media_type": "sfp",
            "connection_face": "front",
            "connection_anchor": port_anchor_name,
            "port_slot": slot or None,
            "source_name": name,
            "led_channel": "port",
        })
        return new_name, extras, False, port_anchor_name

    mgmt = re.search(r"^(SUP\d+)_MGMT_PORT_(\d+)$", upper)
    if mgmt:
        slot, index = mgmt.group(1), int(mgmt.group(2))
        new_name = f"{slot}_PORT_MGMT_{index:03d}"
        port_anchor_name = f"PORT_ANCHOR_FRONT_{slot}_{index:03d}"
        extras.update({
            "component_type": "port_cage",
            "port_index": index,
            "port_media_type": "mgmt",
            "port_group": f"{slot}_MANAGEMENT",
            "connection_face": "front",
            "connection_anchor": port_anchor_name,
            "port_slot": slot,
            "source_name": name,
        })
        return new_name, extras, False, port_anchor_name

    if "STATUS_LED" in upper or re.search(r"(?:^|_)LED(?:_|$)", upper):
        channel = "alarm" if re.search(r"ALARM|FAULT", upper) else "power" if re.search(r"POWER|PSU", upper) else "system"
        extras.update({"component_type": "status_led", "led_channel": channel, "source_name": name})
        return name, extras, False, None
    if "CHASSIS" in upper or upper.startswith("BODY") or upper.startswith("REAR_BRACE"):
        extras["component_type"] = "chassis_body"
    elif "RACK_EAR" in upper:
        extras["component_type"] = "mounting_ear"
    elif "GUIDE" in upper or "SERVICE_" in upper and "RAIL" in upper:
        extras["component_type"] = "slot_guide"
    elif "_BAY" in upper:
        extras["component_type"] = (
            "supervisor_bay" if upper.startswith("SUP_") else
            "power_bay" if upper.startswith("PSU_") else
            "fan_bay" if upper.startswith("FAN_") else "module_bay"
        )
    elif "BLANK" in upper:
        extras["component_type"] = "blank_panel"
    elif "EJECTOR" in upper:
        extras["component_type"] = "ejector"
    elif "LINECARD" in upper:
        extras["component_type"] = "linecard_body" if "BODY" in upper else "linecard_face"
    elif "SUPERVISOR" in upper:
        extras["component_type"] = "supervisor_module"
    elif "PSU" in upper or "POWER_INLET" in upper:
        extras["component_type"] = "power_module"
    elif "FAN" in upper:
        extras["component_type"] = "fan_tray"
    elif "LABEL" in upper:
        extras["component_type"] = "label"
    else:
        extras["component_type"] = "detail"
    extras["source_name"] = name
    return new_name, extras, is_empty_anchor, None


def _material_index(component_type: str, name: str) -> int:
    upper = name.upper()
    if component_type in {"port_led", "status_led"}:
        return 7 if "ALARM" in upper or "FAULT" in upper else 6
    if component_type in {"port_cage", "port_cavity", "port_contact", "blank_panel"}:
        return 3
    if component_type in {"label", "status_label"}:
        return 5
    if component_type in {"slot_guide", "mounting_ear", "ejector", "power_bay", "supervisor_bay", "fan_bay"}:
        return 2
    if component_type in {"chassis_body", "linecard_body", "supervisor_module", "power_module", "fan_tray"}:
        return 0
    return 1


def _annotate_nodes(document: dict[str, Any], binary: bytearray, meta: dict[str, Any]) -> dict[str, Any]:
    nodes = document.setdefault("nodes", [])
    root_index = int(document.get("scenes", [{"nodes": [0]}])[0].get("nodes", [0])[0])
    root = nodes[root_index]
    root["name"] = "ASSET_ROOT"
    root["extras"] = {**_common_extras(meta), "component_type": "asset_root", "asset_origin": "BOTTOM_FRONT_CENTER"}
    root.setdefault("children", [])
    semantic_counts: Counter[str] = Counter()
    pending_port_anchors: list[tuple[str, list[float], dict[str, Any]]] = []
    anchor_positions: dict[str, list[float]] = {}

    for node_index, node in enumerate(nodes):
        name = str(node.get("name") or f"NODE_{node_index:04d}")
        if node_index == root_index:
            continue
        new_name, extras, empty_anchor, port_anchor_name = _classify_node(name, meta)
        node["name"] = new_name
        node["extras"] = extras
        component_type = str(extras.get("component_type") or "detail")
        semantic_counts[component_type] += 1
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            mesh_index = int(mesh_index)
            mesh = document["meshes"][mesh_index]
            mesh.setdefault("extras", {})["component_type"] = component_type
            mesh["extras"]["normalized_bounds_m"] = {
                "min": _mesh_bounds(document, binary, mesh_index)[0],
                "max": _mesh_bounds(document, binary, mesh_index)[1],
            }
            for primitive in mesh.get("primitives", []):
                primitive["material"] = _material_index(component_type, new_name)
            if empty_anchor:
                mins, maxs = _mesh_bounds(document, binary, mesh_index)
                node["translation"] = [(mins[i] + maxs[i]) / 2.0 for i in range(3)]
                anchor_positions[new_name] = node["translation"]
                node.pop("mesh", None)
            elif port_anchor_name:
                mins, maxs = _mesh_bounds(document, binary, mesh_index)
                center = [(mins[i] + maxs[i]) / 2.0 for i in range(3)]
                anchor_extras = {
                    **_common_extras(meta),
                    "component_type": "semantic_anchor",
                    "anchor_type": "port_connection",
                    "port_index": extras.get("port_index"),
                    "port_media_type": extras.get("port_media_type"),
                    "port_slot": extras.get("port_slot"),
                    "connection_face": "front",
                    "connection_anchor": port_anchor_name,
                }
                pending_port_anchors.append((port_anchor_name, center, anchor_extras))

    existing_names = {str(node.get("name") or "") for node in nodes}
    for anchor_name, center, anchor_extras in pending_port_anchors:
        if anchor_name in existing_names:
            continue
        nodes.append({"name": anchor_name, "translation": center, "extras": anchor_extras})
        root["children"].append(len(nodes) - 1)
        existing_names.add(anchor_name)
        semantic_counts["semantic_anchor"] += 1
        anchor_positions[anchor_name] = center
    return {
        "root_index": root_index,
        "semantic_counts": dict(sorted(semantic_counts.items())),
        "port_anchor_count": len(pending_port_anchors),
        "anchor_positions": anchor_positions,
    }


def _set_document_metadata(document: dict[str, Any], meta: dict[str, Any], geometry: dict[str, Any], nodes: dict[str, Any]) -> None:
    common = _common_extras(meta)
    document.setdefault("asset", {})["version"] = "2.0"
    document["asset"]["generator"] = "Nexora modular demo normalizer"
    document["asset"]["extras"] = {
        **common,
        "production_baseline": False,
        "normalization": {
            "source_axes": "X=right,Y=up,Z=front",
            "target_axes": "X=right,Y=front,Z=vertical",
            "origin": "BOTTOM_FRONT_CENTER",
        },
    }
    document.setdefault("scenes", [{"nodes": [0]}])[0]["extras"] = {
        **common,
        "front_direction": "+Y",
        "origin": "BOTTOM_FRONT_CENTER",
        "normalized_bounds_m": geometry["normalized_bounds_m"],
    }
    document.setdefault("extensionsUsed", [])
    document["materials"] = copy.deepcopy(MATERIALS)
    document["extras"] = {
        "rackvision_schema_version": SCHEMA_VERSION,
        "rackvision_coordinate_system": "X=left_right,Y=front_back,Z=vertical",
        "rackvision_front_direction": "+Y",
        "rackvision_asset_key": meta["asset_key"],
        "rackvision_asset_kind": meta["asset_kind"],
        "normalization": {
            "geometry": geometry,
            "nodes": nodes,
        },
    }


def _triangle_count(document: dict[str, Any]) -> int:
    total = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if int(primitive.get("mode") or 4) != 4:
                continue
            if primitive.get("indices") is not None:
                total += int(document["accessors"][int(primitive["indices"])].get("count") or 0) // 3
            else:
                position = primitive.get("attributes", {}).get("POSITION")
                if position is not None:
                    total += int(document["accessors"][int(position)].get("count") or 0) // 3
    return total


def normalize_file(source: Path, output: Path) -> dict[str, Any]:
    meta = dict(FILE_META.get(source.name, {
        "asset_key": f"generic_{source.stem}",
        "model": source.stem,
        "asset_kind": "device",
        "role": "detail",
    }))
    document, binary = read_glb(source)
    geometry = _normalize_geometry(document, binary)
    nodes = _annotate_nodes(document, binary, meta)
    _set_document_metadata(document, meta, geometry, nodes)
    output_bytes = write_glb(document, binary, output)
    has_normals = all(
        "NORMAL" in primitive.get("attributes", {})
        for mesh in document.get("meshes", [])
        for primitive in mesh.get("primitives", [])
    )
    has_uvs = all(
        "TEXCOORD_0" in primitive.get("attributes", {})
        for mesh in document.get("meshes", [])
        for primitive in mesh.get("primitives", [])
    )
    return {
        "asset_key": meta["asset_key"],
        "source_file": source.name,
        "output_file": output.name,
        "source_sha256": _sha256(source.read_bytes()),
        "output_sha256": _sha256(output_bytes),
        "bytes": len(output_bytes),
        "nodes": len(document.get("nodes", [])),
        "meshes": len(document.get("meshes", [])),
        "triangles": _triangle_count(document),
        "materials": len(document.get("materials", [])),
        "has_normals": has_normals,
        "has_uvs": has_uvs,
        "node_extras": sum(1 for node in document.get("nodes", []) if node.get("extras")),
        "mesh_extras": sum(1 for mesh in document.get("meshes", []) if mesh.get("extras")),
        "geometry": geometry,
        "semantic_nodes": nodes,
    }


def _module_asset_key(file_name: str) -> str:
    return FILE_META.get(file_name, {}).get("asset_key", Path(file_name).stem)


def convert_manifest(source_path: Path, output_path: Path, reports: list[dict[str, Any]]) -> dict[str, Any]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    result = copy.deepcopy(source)
    result["schema_version"] = SCHEMA_VERSION
    result["source_schema_version"] = source.get("schema_version")
    result["source_coordinate_system"] = source.get("axis")
    result["axis"] = {"x": "right", "y": "front", "z": "up"}
    result["coordinate_system"] = "X=left_right,Y=front_back,Z=vertical"
    result["front_direction"] = "+Y"
    result["origin"] = "BOTTOM_FRONT_CENTER"
    result["status"] = "draft"
    result["conversion"] = {
        "tool": "tools/gltf/normalize_modular_demo.py",
        "source_archive": "nexora_modular_switch_glb_demo.zip",
        "source_manifest": source_path.name,
        "normalization": "swap source Y/Z, reverse triangle winding, bottom/front origin",
    }
    result.setdefault("device", {})["asset_key"] = "generic_modular_switch_assembled_demo"
    result["device"]["chassis_glb"] = "core_switch_chassis_8slot.glb"
    result["device"]["source_dimensions_m"] = source.get("device", {}).get("dimensions_m")
    chassis_report = next(
        (report for report in reports if report["asset_key"] == "generic_modular_switch_chassis_8slot"),
        {},
    )
    chassis_bounds = ((chassis_report.get("geometry") or {}).get("normalized_bounds_m") or {})
    chassis_min = chassis_bounds.get("min") or [0.0, 0.0, 0.0]
    chassis_max = chassis_bounds.get("max") or [0.0, 0.0, 0.0]
    result["device"]["declared_dimensions_m"] = source.get("device", {}).get("dimensions_m")
    result["device"]["dimensions_m"] = {
        "width": float(chassis_max[0] - chassis_min[0]),
        "height": float(chassis_max[2] - chassis_min[2]),
        "depth": float(chassis_max[1] - chassis_min[1]),
    }
    result["device"]["dimension_status"] = "demo_measured_pending_oem_verification"
    installed = {
        "SLOT01": "generic_modular_linecard_48ge",
        "SLOT02": "generic_modular_linecard_48ge",
        "SLOT03": "generic_modular_linecard_24sfp",
        "SLOT04": "generic_modular_blank_panel",
        "SLOT05": "generic_modular_linecard_48ge",
        "SLOT06": "generic_modular_linecard_24sfp",
        "SLOT07": "generic_modular_blank_panel",
        "SLOT08": "generic_modular_linecard_48ge",
    }
    chassis_anchors = ((chassis_report.get("semantic_nodes") or {}).get("anchor_positions") or {})
    for slot in result.get("slots", []):
        slot_id = str(slot.get("id") or "").upper()
        slot["source_position_m"] = slot.get("position_m")
        source_position = slot.get("position_m") or [0.0, 0.0, 0.0]
        actual_anchor = chassis_anchors.get(f"{slot_id}_ANCHOR")
        if isinstance(actual_anchor, list) and len(actual_anchor) == 3:
            # The converted chassis anchor is the source of truth.  The old
            # manifest positions described a different origin and, for this
            # demo, did not line up with the anchor meshes baked into the GLB.
            slot["position_m"] = [float(value) for value in actual_anchor]
            slot["position_reference"] = "converted_chassis_anchor"
        elif len(source_position) == 3:
            slot["position_m"] = [source_position[0], source_position[2], source_position[1]]
            slot["position_reference"] = "source_chassis_center_axis_swap"
        slot["insert_axis"] = [0, -1, 0]
        slot["installed_module_asset_key"] = installed.get(slot_id)
        slot["compatible_modules"] = [Path(item).name for item in slot.get("compatible_modules", [])]
    result["module_assets"] = [
        {
            "asset_key": report["asset_key"],
            "file": report["output_file"],
            "triangles": report["triangles"],
            "dimensions_m": {
                "width": report["geometry"]["normalized_bounds_m"]["max"][0] - report["geometry"]["normalized_bounds_m"]["min"][0],
                "height": report["geometry"]["normalized_bounds_m"]["max"][2] - report["geometry"]["normalized_bounds_m"]["min"][2],
                "depth": report["geometry"]["normalized_bounds_m"]["max"][1] - report["geometry"]["normalized_bounds_m"]["min"][1],
            },
        }
        for report in reports
        if report["asset_key"] != "generic_modular_switch_assembled_demo"
    ]
    result["assembled_fru"] = [
        {"id": "SUP1", "role": "supervisor", "asset_key": "generic_modular_supervisor", "file": "module_supervisor.glb"},
        {"id": "SUP2", "role": "supervisor", "asset_key": "generic_modular_supervisor", "file": "module_supervisor.glb"},
        {"id": "PSU1", "role": "power", "asset_key": "generic_modular_psu_ac", "file": "module_psu_ac.glb"},
        {"id": "PSU2", "role": "power", "asset_key": "generic_modular_psu_ac", "file": "module_psu_ac.glb"},
        {"id": "PSU3", "role": "power", "asset_key": "generic_modular_psu_ac", "file": "module_psu_ac.glb"},
        {"id": "FAN_TRAY", "role": "fan", "asset_key": "generic_modular_fan_tray", "file": "module_fan_tray.glb"},
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def write_readme(output_dir: Path, reports: list[dict[str, Any]]) -> None:
    lines = [
        "# Nexora modular switch demo (normalized draft)",
        "",
        "This directory is a converted copy of the external modular-switch demo.",
        "The original ZIP remains unchanged.  The output is **draft** and is not",
        "registered as an approved OEM asset.",
        "",
        "- Coordinate system: `X=left_right,Y=front_back,Z=vertical`",
        "- Front direction: `+Y`",
        "- Origin: `BOTTOM_FRONT_CENTER`",
        "- Added vertex normals and generated UVs",
        "- Added Nexora node-level semantic metadata and port anchors",
        "- Added named PBR material slots while preserving source vertex colors",
        "- No baked animations; module motion remains a front-end responsibility",
        "",
        "| file | triangles | nodes | materials | normals | UVs |",
        "| --- | ---: | ---: | ---: | :---: | :---: |",
    ]
    for report in reports:
        lines.append(
            f"| `{report['output_file']}` | {report['triangles']} | {report['nodes']} | "
            f"{report['materials']} | {'yes' if report['has_normals'] else 'no'} | "
            f"{'yes' if report['has_uvs'] else 'no'} |"
        )
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("assets/build/glb/modular_demo"))
    parser.add_argument("--publish-dir", type=Path, default=Path("public/assets/3d/modular_demo"))
    parser.add_argument("--manifest", type=Path, default=None)
    options = parser.parse_args()
    input_dir = options.input_dir.resolve()
    output_dir = options.output_dir.resolve()
    publish_dir = options.publish_dir.resolve()
    manifest = (options.manifest or input_dir / "slot_manifest.json").resolve()
    if not input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    publish_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    for file_name in FILE_META:
        source = input_dir / file_name
        if not source.is_file():
            raise SystemExit(f"Missing modular demo file: {source}")
        output = output_dir / file_name
        report = normalize_file(source, output)
        publish = publish_dir / file_name
        publish.write_bytes(output.read_bytes())
        report["publish_file"] = str(publish.relative_to(publish_dir.parent.parent))
        reports.append(report)
    if manifest.is_file():
        convert_manifest(manifest, output_dir / "slot_manifest.json", reports)
    write_readme(output_dir, reports)
    report_path = output_dir / "validation_report.json"
    report_path.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "status": "draft",
        "source_dir": str(input_dir),
        "output_dir": str(output_dir),
        "assets": reports,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "publish_dir": str(publish_dir), "assets": len(reports), "status": "draft"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
