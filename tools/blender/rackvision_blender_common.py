"""Shared Blender helpers for RackVision's reproducible asset build scripts.

These helpers are executed by Blender, not by the FastAPI runtime. They keep
the coordinate and naming contract in one place so generated GLBs can be
validated before being copied to the web asset directory.
"""

from __future__ import annotations

from typing import Any

try:  # Blender injects bpy; normal Python can still parse/test the scripts.
    import bpy  # type: ignore
except ImportError:  # pragma: no cover - only exercised outside Blender
    bpy = None


BLENDER_UNIT_METERS = 1.0
U_METERS = 0.04445
FRONT_Y = 0.0


class BlenderRuntimeUnavailable(RuntimeError):
    pass


def require_blender() -> Any:
    if bpy is None:
        raise BlenderRuntimeUnavailable("This command must run inside Blender with bpy available")
    return bpy


def configure_scene() -> None:
    runtime = require_blender()
    scene = runtime.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = BLENDER_UNIT_METERS
    scene.unit_settings.length_unit = "METERS"


def reset_scene() -> None:
    runtime = require_blender()
    runtime.ops.object.select_all(action="SELECT")
    runtime.ops.object.delete(use_global=False)
    for datablocks in (runtime.data.meshes, runtime.data.curves, runtime.data.materials, runtime.data.cameras, runtime.data.lights):
        for item in list(datablocks):
            if item.users == 0:
                datablocks.remove(item)


def make_material(name: str, color: tuple[float, float, float, float], *, roughness: float = 0.6) -> Any:
    runtime = require_blender()
    material = runtime.data.materials.get(name) or runtime.data.materials.new(name=name)
    material.diffuse_color = color
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = roughness
    return material


def add_box(
    name: str,
    dimensions: tuple[float, float, float],
    location: tuple[float, float, float],
    material: Any,
) -> Any:
    runtime = require_blender()
    runtime.ops.mesh.primitive_cube_add(location=location)
    obj = runtime.context.object
    obj.name = name
    obj.dimensions = dimensions
    runtime.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material:
        obj.data.materials.append(material)
    return obj


def _port_count(spec: dict[str, Any]) -> int:
    front_layout = spec.get("front_layout") or {}
    if isinstance(front_layout, dict):
        values = [int(value) for value in front_layout.values() if str(value).isdigit()]
        if values:
            return max(1, min(64, sum(values)))
    return int(spec.get("port_count") or 24)


def create_device(spec: dict[str, Any]) -> list[Any]:
    """Create a named, low-poly device family asset from a JSON spec."""

    require_blender()
    configure_scene()
    asset_key = str(spec.get("asset_key") or "generic_device")
    vendor = str(spec.get("vendor") or "generic")
    model = str(spec.get("exact_model") or spec.get("model") or asset_key)
    template = str(spec.get("template") or "switch_1u")
    height_u = spec.get("height_u")
    if height_u in (None, ""):
        height_u = 1 if "1u" in template.casefold() else 2
    height_u = max(1, int(height_u))
    width_mm = float(spec.get("width_mm") or 440.0)
    depth_mm = float(spec.get("depth_mm") or 400.0)
    height_mm = float(spec.get("height_mm") or height_u * 44.45)
    width = width_mm / 1000.0
    depth = depth_mm / 1000.0
    height = height_mm / 1000.0

    chassis = make_material("MAT_CHASSIS", (0.18, 0.21, 0.25, 1.0))
    panel = make_material("MAT_FRONT_PANEL", (0.08, 0.10, 0.13, 1.0))
    port = make_material("MAT_PORT", (0.015, 0.025, 0.04, 1.0))
    led = make_material("MAT_LED", (0.05, 0.8, 0.65, 1.0), roughness=0.35)
    label = make_material("MAT_LABEL", (0.7, 0.75, 0.8, 1.0))

    objects: list[Any] = []
    body = add_box("BODY", (width, depth, height), (0.0, -depth / 2.0, height / 2.0), chassis)
    front = add_box("FRONT_PANEL", (max(0.01, width - 0.01), 0.008, max(0.01, height - 0.006)), (0.0, 0.004, height / 2.0), panel)
    rear = add_box("REAR_PANEL", (max(0.01, width - 0.01), 0.008, max(0.01, height - 0.006)), (0.0, -depth - 0.004, height / 2.0), panel)
    objects.extend((body, front, rear))

    port_count = _port_count(spec)
    columns = min(24, max(1, int(spec.get("port_columns") or 24)))
    media_type = str(spec.get("port_media_type") or "copper").casefold()
    if "qsfp" in media_type or "osfp" in media_type:
        port_dimensions = (0.018, 0.014, 0.016)
    elif "sfp" in media_type or "optical" in media_type:
        port_dimensions = (0.010, 0.014, 0.012)
    else:
        port_dimensions = (0.012, 0.012, 0.014)
    for index in range(port_count):
        column = index % columns
        row = index // columns
        x = -width / 2.0 + 0.025 + column * ((width - 0.05) / max(1, columns - 1))
        z = height * 0.43 + (row % 2) * min(0.014, height * 0.16)
        objects.append(add_box(f"PORT_GE_{index + 1:02d}", port_dimensions, (x, 0.010, z), port))

    objects.append(add_box("LED_POWER", (0.008, 0.004, 0.008), (width / 2.0 - 0.035, 0.010, height * 0.72), led))
    objects.append(add_box("LED_SYSTEM", (0.008, 0.004, 0.008), (width / 2.0 - 0.055, 0.010, height * 0.72), led))
    objects.append(add_box("LOGO_VENDOR", (0.08, 0.004, 0.018), (-width / 2.0 + 0.065, 0.010, height * 0.78), label))

    for index in range(2 if height_u >= 2 else 1):
        objects.append(add_box(f"PSU_{index + 1:02d}", (0.08, 0.012, 0.08), (-width / 2.0 + 0.07 + index * 0.10, -depth - 0.010, height * 0.28), chassis))
        objects.append(add_box(f"FAN_{index + 1:02d}", (0.08, 0.012, 0.08), (width / 2.0 - 0.07 - index * 0.10, -depth - 0.010, height * 0.28), port))

    for obj in objects:
        obj["asset_key"] = asset_key
        obj["vendor"] = vendor
        obj["exact_model"] = model
        obj["height_u"] = height_u
        obj["coordinate_system"] = "X=left_right,Y=front_back,Z=vertical"
        obj["front_direction"] = "+Y"
    body["dimensions_mm"] = {"width": width_mm, "depth": depth_mm, "height": height_mm}
    return objects


__all__ = [
    "BLENDER_UNIT_METERS",
    "U_METERS",
    "BlenderRuntimeUnavailable",
    "configure_scene",
    "create_device",
    "require_blender",
    "reset_scene",
]
