"""Validate RackVision Blender scene naming, transforms, units, and semantics."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rackvision_blender_production import SCHEMA_VERSION, U_METERS, require_blender


DEVICE_REQUIRED_OBJECTS = {
    "ASSET_ROOT",
    "BODY",
    "FRONT_PANEL",
    "REAR_PANEL",
    "RACK_EAR_L",
    "RACK_EAR_R",
}
RACK_REQUIRED_OBJECTS = {
    "ASSET_ROOT",
    "RACK_BODY",
    "RACK_TOP_CAP",
    "RACK_BASE",
    "RACK_RAIL_FRONT_L",
    "RACK_RAIL_FRONT_R",
}
# Kept as a compatibility alias for callers that imported the original name.
REQUIRED_OBJECTS = DEVICE_REQUIRED_OBJECTS


def validate_scene(expected_height_u: int | None = None) -> list[str]:
    runtime = require_blender()
    issues: list[str] = []
    scene = runtime.context.scene
    asset_kind = str(scene.get("rackvision_asset_kind") or "device").strip().casefold()
    if asset_kind not in {"device", "patch_panel", "rack"}:
        issues.append(f"unsupported rackvision_asset_kind: {asset_kind}")
    required_objects = RACK_REQUIRED_OBJECTS if asset_kind == "rack" else DEVICE_REQUIRED_OBJECTS
    if abs(float(scene.unit_settings.scale_length) - 1.0) > 1e-6:
        issues.append("scene scale_length must be 1.0")
    if scene.unit_settings.system != "METRIC":
        issues.append("scene unit system must be METRIC")
    names = {obj.name for obj in scene.objects}
    missing = sorted(required_objects - names)
    if missing:
        issues.append(f"missing required objects: {', '.join(missing)}")
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        if any(abs(value - 1.0) > 1e-5 for value in obj.scale):
            issues.append(f"unapplied scale on {obj.name}")
        if any(value <= 0 for value in obj.dimensions):
            issues.append(f"non-positive dimensions on {obj.name}")
    body = scene.objects.get("RACK_BODY" if asset_kind == "rack" else "BODY")
    if body is not None:
        body_label = "RACK_BODY" if asset_kind == "rack" else "BODY"
        if expected_height_u is not None and body.type == "MESH":
            tolerance = 0.004
            expected = int(expected_height_u) * U_METERS
            if abs(float(body.dimensions.z) - expected) > tolerance:
                issues.append(f"{body_label} height {body.dimensions.z:.5f}m is not {expected:.5f}m for {expected_height_u}U")
        if body.get("front_direction") != "+Y":
            issues.append(f"{body_label} front_direction must be +Y")
        if body.get("schema_version") != SCHEMA_VERSION:
            issues.append(f"{body_label} schema_version must be {SCHEMA_VERSION}")
        expected_dimensions = (
            scene.get("rackvision_width_mm"),
            scene.get("rackvision_depth_mm"),
            scene.get("rackvision_height_mm"),
        )
        if body.type == "MESH" and all(value is not None for value in expected_dimensions):
            # The rack body is intentionally a thin front reference surface so
            # that installed device GLBs remain visible through the enclosure.
            # Validate its width/height envelope, while the complete depth is
            # represented by the side/rear panel objects.
            dimensions_to_check = zip("xz", (body.dimensions.x, body.dimensions.z), (expected_dimensions[0], expected_dimensions[2])) if asset_kind == "rack" else zip("xyz", body.dimensions, expected_dimensions)
            for axis, actual, expected_mm in dimensions_to_check:
                expected_m = float(expected_mm) / 1000.0
                if abs(float(actual) - expected_m) > 0.0005:
                    issues.append(f"{body_label} {axis} {actual:.6f}m is not {expected_m:.6f}m")

    if scene.get("rackvision_schema_version") != SCHEMA_VERSION:
        issues.append(f"scene rackvision_schema_version must be {SCHEMA_VERSION}")
    if scene.get("rackvision_front_direction") != "+Y":
        issues.append("scene rackvision_front_direction must be +Y")

    if asset_kind != "rack":
        port_cages = [
            obj for obj in scene.objects
            if obj.type == "MESH" and obj.get("component_type") == "port_cage"
        ]
        anchors = {
            obj.name for obj in scene.objects
            if obj.name.startswith("PORT_ANCHOR_") and obj.get("anchor_type") == "port_connection"
        }
        if not port_cages:
            issues.append("scene must contain at least one semantic port cage")
        for obj in port_cages:
            anchor_name = str(obj.get("connection_anchor") or "")
            if not anchor_name or anchor_name not in anchors:
                issues.append(f"missing semantic anchor for {obj.name}")
            if not re.match(r"^PORT_[A-Z0-9_]+_\d{3}$", obj.name):
                issues.append(f"invalid port name: {obj.name}")
        expected_port_count = scene.get("rackvision_port_count")
        if expected_port_count is not None and int(expected_port_count) > 0:
            front_count = sum(1 for obj in port_cages if obj.get("connection_face") == "front")
            if front_count != int(expected_port_count):
                issues.append(f"front port cage count {front_count} is not {int(expected_port_count)}")
        if len({obj.name for obj in port_cages}) != len(port_cages):
            issues.append("port cage names must be unique")

        component_counts: dict[str, int] = {}
        for obj in scene.objects:
            if obj.type != "MESH":
                continue
            component_type = str(obj.get("component_type") or "").strip()
            if component_type:
                component_counts[component_type] = component_counts.get(component_type, 0) + 1
        if component_counts.get("port_slot", 0) < len(port_cages) * 4:
            issues.append(
                f"port slot frame count {component_counts.get('port_slot', 0)} is below four per port cage ({len(port_cages) * 4})"
            )
        if component_counts.get("port_led", 0) < len(port_cages) * 2:
            issues.append(
                f"port LED count {component_counts.get('port_led', 0)} is below two per port cage ({len(port_cages) * 2})"
            )
        if asset_kind == "patch_panel":
            for component_type, label in (
                ("patch_port_guide", "patch port guide"),
                ("cable_guide", "cable guide"),
                ("cable_clip", "cable clip"),
                ("grounding_stud", "grounding stud"),
            ):
                if component_counts.get(component_type, 0) == 0:
                    issues.append(f"patch panel must contain at least one {label}")
    material_names = {
        material.name
        for obj in scene.objects
        if obj.type == "MESH"
        for material in obj.data.materials
        if material is not None
    }
    if len(material_names) < 6:
        issues.append(f"production asset requires at least 6 materials, found {len(material_names)}")
    return issues


def blender_args() -> list[str]:
    args = sys.argv
    return args[args.index("--") + 1 :] if "--" in args else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--height-u", type=int, default=None)
    options = parser.parse_args(argv if argv is not None else blender_args())
    issues = validate_scene(options.height_u)
    for issue in issues:
        print(f"ERROR: {issue}")
    if not issues:
        print("RackVision scene validation passed")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
