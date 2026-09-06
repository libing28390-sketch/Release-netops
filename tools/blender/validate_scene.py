"""Validate RackVision Blender scene naming, transforms, units, and bounds."""

from __future__ import annotations

import argparse
import sys

from rackvision_blender_common import U_METERS, require_blender


REQUIRED_OBJECTS = {"BODY", "FRONT_PANEL", "REAR_PANEL"}


def validate_scene(expected_height_u: int | None = None) -> list[str]:
    runtime = require_blender()
    issues: list[str] = []
    scene = runtime.context.scene
    if scene.unit_settings.system != "METRIC":
        issues.append("scene unit system must be METRIC")
    names = {obj.name for obj in scene.objects}
    missing = sorted(REQUIRED_OBJECTS - names)
    if missing:
        issues.append(f"missing required objects: {', '.join(missing)}")
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        if any(abs(value - 1.0) > 1e-5 for value in obj.scale):
            issues.append(f"unapplied scale on {obj.name}")
        if any(value <= 0 for value in obj.dimensions):
            issues.append(f"non-positive dimensions on {obj.name}")
    body = scene.objects.get("BODY")
    if body is not None:
        if expected_height_u is not None:
            tolerance = 0.004
            expected = int(expected_height_u) * U_METERS
            if abs(float(body.dimensions.z) - expected) > tolerance:
                issues.append(f"BODY height {body.dimensions.z:.5f}m is not {expected:.5f}m for {expected_height_u}U")
        if body.get("front_direction") != "+Y":
            issues.append("BODY front_direction must be +Y")
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

