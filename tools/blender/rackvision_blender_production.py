"""Production-oriented procedural Blender asset builder for RackVision.

The builder targets real-time RackVision display assets.  It adds detailed
manufacturing-inspired geometry, stable semantic nodes, PBR materials and
metadata while keeping dimensions and orientation driven by a reviewed JSON
spec.  Without OEM CAD or an official dimension drawing it does not claim
exact product appearance; those assets remain draft in the registry.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any

try:  # Blender injects bpy; normal Python can still parse/test the scripts.
    import bpy  # type: ignore
except ImportError:  # pragma: no cover
    bpy = None


BLENDER_UNIT_METERS = 1.0
U_METERS = 0.04445
FRONT_Y = 0.0
SCHEMA_VERSION = "1.1"


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
    scene.render.film_transparent = True
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except Exception:
        pass
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass


def reset_scene() -> None:
    runtime = require_blender()
    runtime.ops.object.select_all(action="SELECT")
    runtime.ops.object.delete(use_global=False)
    for datablocks in (runtime.data.meshes, runtime.data.curves, runtime.data.materials, runtime.data.cameras, runtime.data.lights):
        for item in list(datablocks):
            if item.users == 0:
                datablocks.remove(item)


def _new_collections() -> dict[str, Any]:
    runtime = require_blender()
    scene = runtime.context.scene
    result: dict[str, Any] = {}
    existing_children = {child.name for child in scene.collection.children}
    for name in ("RV_ASSET", "RV_PORTS", "RV_DETAIL", "RV_MOUNTING"):
        collection = runtime.data.collections.get(name)
        if collection is None:
            collection = runtime.data.collections.new(name)
        if name not in existing_children:
            scene.collection.children.link(collection)
        result[name] = collection
    return result


def _move_to_collection(obj: Any, collection: Any | None) -> None:
    if collection is None:
        return
    for current in list(obj.users_collection):
        current.objects.unlink(obj)
    collection.objects.link(obj)


def make_material(
    name: str,
    color: tuple[float, float, float, float],
    *,
    roughness: float = 0.6,
    metallic: float = 0.0,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
) -> Any:
    runtime = require_blender()
    material = runtime.data.materials.get(name) or runtime.data.materials.new(name=name)
    material.diffuse_color = color
    material.use_nodes = True
    material["rackvision_material_role"] = name
    # Blender localizes node labels (for example, the Chinese UI exposes the
    # Principled BSDF node as ``原理化 BSDF``).  Looking it up by the stable
    # node type keeps exported glTF materials deterministic across locales.
    principled = next(
        (node for node in material.node_tree.nodes if node.bl_idname == "ShaderNodeBsdfPrincipled"),
        None,
    )
    if principled:
        if "Base Color" in principled.inputs:
            principled.inputs["Base Color"].default_value = color
        if "Roughness" in principled.inputs:
            principled.inputs["Roughness"].default_value = max(0.0, min(1.0, roughness))
        if "Metallic" in principled.inputs:
            principled.inputs["Metallic"].default_value = max(0.0, min(1.0, metallic))
        if emission is not None:
            if "Emission Color" in principled.inputs:
                principled.inputs["Emission Color"].default_value = emission
            elif "Emission" in principled.inputs:
                principled.inputs["Emission"].default_value = emission
            if "Emission Strength" in principled.inputs:
                principled.inputs["Emission Strength"].default_value = emission_strength
    return material


def _apply_bevel(obj: Any, width: float, segments: int = 2) -> None:
    if width <= 0 or not obj.dimensions:
        return
    minimum = min(float(value) for value in obj.dimensions)
    if minimum <= 0:
        return
    modifier = obj.modifiers.new(name="EDGE_BEVEL", type="BEVEL")
    modifier.width = min(float(width), minimum * 0.32)
    modifier.segments = max(1, min(3, int(segments)))
    modifier.limit_method = "ANGLE"


def add_box(
    name: str,
    dimensions: tuple[float, float, float],
    location: tuple[float, float, float],
    material: Any,
    *,
    collection: Any | None = None,
    bevel: float = 0.0,
    component_type: str = "detail",
) -> Any:
    runtime = require_blender()
    runtime.ops.mesh.primitive_cube_add(location=location)
    obj = runtime.context.object
    obj.name = name
    obj.dimensions = tuple(max(0.0001, float(value)) for value in dimensions)
    runtime.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material:
        obj.data.materials.append(material)
    _move_to_collection(obj, collection)
    _apply_bevel(obj, bevel)
    obj["component_type"] = component_type
    return obj


def add_cylinder(
    name: str,
    radius: float,
    depth: float,
    location: tuple[float, float, float],
    material: Any,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    collection: Any | None = None,
    vertices: int = 16,
    bevel: float = 0.0,
    component_type: str = "detail",
) -> Any:
    runtime = require_blender()
    runtime.ops.mesh.primitive_cylinder_add(
        vertices=max(8, int(vertices)),
        radius=max(0.0001, float(radius)),
        depth=max(0.0001, float(depth)),
        location=location,
        rotation=rotation,
    )
    obj = runtime.context.object
    obj.name = name
    if material:
        obj.data.materials.append(material)
    _move_to_collection(obj, collection)
    _apply_bevel(obj, bevel)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj["component_type"] = component_type
    return obj


def add_torus(
    name: str,
    major_radius: float,
    minor_radius: float,
    location: tuple[float, float, float],
    material: Any,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    collection: Any | None = None,
    component_type: str = "detail",
) -> Any:
    runtime = require_blender()
    runtime.ops.mesh.primitive_torus_add(
        major_segments=20,
        minor_segments=8,
        major_radius=max(0.0002, float(major_radius)),
        minor_radius=max(0.0001, float(minor_radius)),
        location=location,
        rotation=rotation,
    )
    obj = runtime.context.object
    obj.name = name
    if material:
        obj.data.materials.append(material)
    _move_to_collection(obj, collection)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    obj["component_type"] = component_type
    return obj


def add_empty(
    name: str,
    location: tuple[float, float, float],
    *,
    collection: Any | None = None,
    display_size: float = 0.01,
) -> Any:
    runtime = require_blender()
    runtime.ops.object.empty_add(type="PLAIN_AXES", location=location)
    obj = runtime.context.object
    obj.name = name
    obj.empty_display_size = display_size
    _move_to_collection(obj, collection)
    obj["component_type"] = "semantic_anchor"
    return obj


def add_text_mesh(
    name: str,
    text: str,
    location: tuple[float, float, float],
    size: float,
    material: Any,
    *,
    face: str = "front",
    collection: Any | None = None,
) -> Any | None:
    runtime = require_blender()
    if not str(text).strip():
        return None
    curve = runtime.data.curves.new(name=name, type="FONT")
    curve.body = str(text)
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    curve.size = max(0.001, float(size))
    curve.extrude = 0.00018
    curve.bevel_depth = 0.00006
    obj = runtime.data.objects.new(name, curve)
    target_collection = collection or runtime.context.scene.collection
    target_collection.objects.link(obj)
    obj.location = location
    # Blender text is authored in its local XY plane. Map local +Y to the
    # cabinet's world +Z so labels stay upright in either elevation. The
    # quarter-turn plus the cabinet's mirrored GLB scale leaves the visible
    # front glyph winding reversed; compensate on the text's local X axis so
    # port numbers and model labels read left-to-right in the web viewer.
    obj.rotation_euler = (math.pi / 2.0, 0.0, math.pi if face == "front" else 0.0)
    obj.scale.x = -1.0
    if material:
        curve.materials.append(material)
    runtime.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    runtime.context.view_layer.objects.active = obj
    runtime.ops.object.convert(target="MESH")
    obj = runtime.context.object
    # Apply the corrective reflection before export. GLTF's exporter rejects
    # unapplied negative scales, and keeping it unapplied would make the
    # readable winding correction disappear from production assets.
    runtime.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj["component_type"] = "label"
    return obj


def _port_count(spec: dict[str, Any]) -> int:
    groups = spec.get("port_groups")
    if isinstance(groups, list):
        counts = []
        for group in groups:
            if isinstance(group, dict):
                try:
                    counts.append(int(group.get("count") or 0))
                except (TypeError, ValueError):
                    pass
        if counts:
            return max(0, min(128, sum(counts)))
    layout = spec.get("front_layout")
    if isinstance(layout, dict):
        return max(0, min(128, sum(int(value) for value in layout.values() if str(value).isdigit())))
    return max(0, min(128, int(spec.get("port_count") or 24)))


def _port_groups(spec: dict[str, Any]) -> list[dict[str, Any]]:
    raw = spec.get("port_groups")
    groups: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                count = int(item.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            if count > 0:
                group = dict(item)
                group["count"] = min(128, count)
                groups.append(group)
    if groups:
        return groups
    media_type = str(spec.get("port_media_type") or "copper")
    count = _port_count(spec)
    columns = max(1, min(count or 1, int(spec.get("port_columns") or min(count, 24) or 1)))
    return [{"name": "GE" if media_type == "copper" else media_type.upper(), "count": count, "media_type": media_type, "columns": columns}]


def _media_token(media_type: str) -> str:
    value = str(media_type).casefold()
    if "qsfp" in value or "osfp" in value:
        return "QSFP"
    if "sfp" in value or "optical" in value:
        return "SFP"
    if "mgmt" in value:
        return "MGMT"
    return "GE"


def _port_dimensions(media_type: str) -> tuple[float, float, float]:
    token = _media_token(media_type)
    if token == "QSFP":
        return (0.024, 0.018, 0.015)
    if token == "SFP":
        return (0.013, 0.017, 0.010)
    if token == "MGMT":
        return (0.012, 0.015, 0.010)
    return (0.012, 0.016, 0.011)


def _tag_object(obj: Any, spec: dict[str, Any], component_type: str | None = None) -> Any:
    obj["asset_key"] = str(spec.get("asset_key") or "generic_device")
    obj["vendor"] = str(spec.get("vendor") or "generic")
    obj["exact_model"] = str(spec.get("exact_model") or spec.get("model") or obj["asset_key"])
    obj["coordinate_system"] = "X=left_right,Y=front_back,Z=vertical"
    obj["front_direction"] = "+Y"
    obj["unit"] = "meter"
    obj["schema_version"] = SCHEMA_VERSION
    obj["lod"] = "LOD0"
    if component_type:
        obj["component_type"] = component_type
    return obj


def _tag_port(obj: Any, spec: dict[str, Any], *, index: int, media_type: str, face: str, group_name: str) -> Any:
    # Preserve the component-specific role (port_cage, port_cavity, contact,
    # LED, etc.) while adding the shared connection metadata.
    _tag_object(obj, spec)
    obj["port_index"] = int(index)
    obj["port_media_type"] = str(media_type)
    obj["port_group"] = str(group_name)
    obj["connection_face"] = str(face)
    obj["connection_anchor"] = f"PORT_ANCHOR_{face.upper()}_{index:03d}"
    return obj


def _create_port(
    spec: dict[str, Any], *, name: str, index: int, group_name: str,
    media_type: str, face: str, x: float, z: float, surface_y: float,
    collections: dict[str, Any], port_scale: float = 1.0,
) -> list[Any]:
    sign = 1.0 if face == "front" else -1.0
    port_width, projection, port_height = _port_dimensions(media_type)
    port_scale = max(0.55, min(1.5, float(port_scale)))
    port_width *= port_scale
    projection *= port_scale
    port_height *= port_scale
    token = _media_token(media_type)
    materials = spec["_materials"]
    objects: list[Any] = []
    cage = add_box(
        name, (port_width, projection, port_height),
        (x, surface_y + sign * projection * 0.48, z), materials["cage"],
        collection=collections["RV_PORTS"], bevel=min(0.0012, port_width * 0.10), component_type="port_cage",
    )
    _tag_port(cage, spec, index=index, media_type=media_type, face=face, group_name=group_name)
    objects.append(cage)
    cavity_width = port_width * (0.78 if token == "QSFP" else 0.70)
    cavity_height = port_height * (0.66 if token == "QSFP" else 0.60)
    cavity = add_box(
        f"{name}_CAVITY", (cavity_width, 0.003, cavity_height),
        (x, surface_y + sign * projection * 0.98, z), materials["socket"],
        collection=collections["RV_PORTS"], bevel=min(0.0006, cavity_width * 0.08), component_type="port_cavity",
    )
    _tag_port(cavity, spec, index=index, media_type=media_type, face=face, group_name=group_name)
    objects.append(cavity)

    # A port is an assembly, not a colored dot: add four thin lips around the
    # dark opening so SFP/QSFP/RJ45 slots remain readable at viewer distance.
    frame_y = surface_y + sign * projection * 1.03
    frame_depth = min(0.0018, max(0.0008, projection * 0.16))
    frame_thickness = min(0.0014, max(0.0007, port_height * 0.14))
    frame_parts = (
        ("TOP", (port_width * 0.96, frame_depth, frame_thickness), (x, frame_y, z + cavity_height / 2.0)),
        ("BOTTOM", (port_width * 0.96, frame_depth, frame_thickness), (x, frame_y, z - cavity_height / 2.0)),
        ("LEFT", (frame_thickness, frame_depth, cavity_height), (x - cavity_width / 2.0, frame_y, z)),
        ("RIGHT", (frame_thickness, frame_depth, cavity_height), (x + cavity_width / 2.0, frame_y, z)),
    )
    for frame_name, frame_dimensions, frame_location in frame_parts:
        slot_frame = add_box(
            f"{name}_SLOT_{frame_name}", frame_dimensions, frame_location, materials["cage"],
            collection=collections["RV_DETAIL"], bevel=min(0.00025, frame_thickness * 0.2), component_type="port_slot",
        )
        _tag_port(slot_frame, spec, index=index, media_type=media_type, face=face, group_name=group_name)
        objects.append(slot_frame)
    if token == "GE":
        for contact_index in range(4):
            contact = add_box(
                f"{name}_CONTACT_{contact_index + 1:02d}",
                (port_width * 0.055, 0.0012, port_height * 0.22),
                (x - port_width * 0.27 + contact_index * port_width * 0.18,
                 surface_y + sign * projection * 1.06, z - port_height * 0.05),
                materials["accent"], collection=collections["RV_DETAIL"], bevel=0.0001, component_type="port_contact",
            )
            _tag_port(contact, spec, index=index, media_type=media_type, face=face, group_name=group_name)
            objects.append(contact)
    elif token == "SFP":
        latch = add_box(
            f"{name}_LATCH", (port_width * 0.62, 0.002, port_height * 0.08),
            (x, surface_y + sign * projection * 1.08, z + port_height * 0.35), materials["accent"],
            collection=collections["RV_DETAIL"], bevel=0.0002, component_type="port_latch",
        )
        _tag_port(latch, spec, index=index, media_type=media_type, face=face, group_name=group_name)
        objects.append(latch)
    else:
        for lane_index in range(4):
            lane = add_box(
                f"{name}_LANE_{lane_index + 1:02d}", (cavity_width * 0.18, 0.0012, cavity_height * 0.70),
                (x - cavity_width * 0.30 + lane_index * cavity_width * 0.20,
                 surface_y + sign * projection * 1.06, z), materials["accent"],
                collection=collections["RV_DETAIL"], bevel=0.0001, component_type="port_lane",
            )
            _tag_port(lane, spec, index=index, media_type=media_type, face=face, group_name=group_name)
            objects.append(lane)
    for led_name, led_x in (("A", -port_width * 0.30), ("B", port_width * 0.30)):
        led = add_box(
            f"{name}_LED_{led_name}", (port_width * 0.13, 0.0018, port_height * 0.13),
            (x + led_x, surface_y + sign * projection * 1.08, z - port_height * 0.38), materials["led"],
            collection=collections["RV_DETAIL"], bevel=0.00015, component_type="port_led",
        )
        _tag_port(led, spec, index=index, media_type=media_type, face=face, group_name=group_name)
        objects.append(led)

    include_port_labels = str(spec.get("include_port_labels", True)).casefold() not in {"0", "false", "no"}
    if include_port_labels and (face == "front" or str(spec.get("include_rear_port_labels", False)).casefold() in {"1", "true", "yes"}):
        port_label = add_text_mesh(
            f"{name}_LABEL", f"{index:02d}",
            (x, surface_y + sign * projection * 1.16, z + port_height * 0.72),
            min(0.0028, max(0.0018, port_height * 0.25)), materials["label"], face=face,
            collection=collections["RV_DETAIL"],
        )
        if port_label:
            _tag_port(port_label, spec, index=index, media_type=media_type, face=face, group_name=group_name)
            port_label["component_type"] = "port_label"
            objects.append(port_label)
    anchor = add_empty(
        f"PORT_ANCHOR_{face.upper()}_{index:03d}",
        (x, surface_y + sign * projection * 1.15, z), collection=collections["RV_PORTS"], display_size=0.003,
    )
    _tag_port(anchor, spec, index=index, media_type=media_type, face=face, group_name=group_name)
    anchor["anchor_type"] = "port_connection"
    objects.append(anchor)
    return objects


def _create_front_shell(spec: dict[str, Any], width: float, height: float, collections: dict[str, Any]) -> list[Any]:
    materials = spec["_materials"]
    asset_kind = str(spec.get("asset_kind") or "device").casefold()
    objects: list[Any] = []
    front = add_box(
        "FRONT_PANEL", (max(0.01, width - 0.012), 0.006, max(0.01, height - 0.004)),
        (0.0, 0.003, height / 2.0), materials["panel"], collection=collections["RV_ASSET"], bevel=0.001, component_type="front_panel",
    )
    objects.append(front)
    for name, z in (("FRONT_BEZEL_TOP", height - 0.003), ("FRONT_BEZEL_BOTTOM", 0.003)):
        objects.append(add_box(name, (width - 0.028, 0.004, 0.0025), (0.0, 0.007, z), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.0004, component_type="front_bezel"))
    front_label = str(spec.get("front_label") or spec.get("vendor") or "NEXORA").upper()
    model_label = str(spec.get("front_model_label") or spec.get("exact_model") or "NETWORK DEVICE").upper()
    logo = add_text_mesh("LOGO_VENDOR", front_label[:18], (-width / 2.0 + 0.050, 0.010, height * 0.77), min(0.010, max(0.004, height * 0.13)), materials["label"], collection=collections["RV_DETAIL"])
    if logo:
        objects.append(logo)
    model_text = add_text_mesh("LABEL_MODEL", model_label[:24], (-width / 2.0 + 0.050, 0.010, height * 0.62), min(0.006, max(0.003, height * 0.075)), materials["label"], collection=collections["RV_DETAIL"])
    if model_text:
        objects.append(model_text)
    if asset_kind != "patch_panel":
        objects.append(add_box("STATUS_PANEL", (0.060, 0.004, min(0.020, max(0.012, height * 0.38))), (-width / 2.0 + 0.050, 0.009, height * 0.31), materials["socket"], collection=collections["RV_DETAIL"], bevel=0.002, component_type="status_panel"))
        for led_index, (name, material_key) in enumerate((("LED_POWER", "led_green"), ("LED_SYSTEM", "led_blue"), ("LED_ALARM", "led_amber"))):
            objects.append(add_cylinder(name, 0.0022, 0.002, (-width / 2.0 + 0.029 + led_index * 0.020, 0.013, height * 0.31), materials[material_key], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_DETAIL"], vertices=16, bevel=0.0002, component_type="status_led"))
    return objects


def _create_patch_panel_details(spec: dict[str, Any], width: float, height: float, collections: dict[str, Any]) -> list[Any]:
    """Add the small mechanical details that distinguish a patch panel from a switch."""

    materials = spec["_materials"]
    objects: list[Any] = []
    objects.append(add_box("PATCH_PORT_GUIDE_TOP", (width - 0.060, 0.006, 0.003), (0.0, 0.019, height * 0.78), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.0004, component_type="patch_port_guide"))
    objects.append(add_box("PATCH_PORT_GUIDE_BOTTOM", (width - 0.060, 0.006, 0.003), (0.0, 0.019, height * 0.20), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.0004, component_type="patch_port_guide"))
    objects.append(add_box("PATCH_CABLE_GUIDE", (width - 0.100, 0.028, 0.006), (0.0, 0.031, height * 0.08), materials["chassis"], collection=collections["RV_MOUNTING"], bevel=0.001, component_type="cable_guide"))
    for index in range(6):
        x = -width * 0.34 + index * (width * 0.68 / 5.0)
        objects.append(add_box(f"PATCH_CABLE_CLIP_{index + 1:02d}", (0.018, 0.010, 0.008), (x, 0.049, height * 0.08), materials["steel"], collection=collections["RV_MOUNTING"], bevel=0.001, component_type="cable_clip"))
    objects.append(add_cylinder("PATCH_GROUND_STUD", 0.003, 0.004, (width / 2.0 - 0.040, 0.018, height * 0.18), materials["accent"], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_MOUNTING"], vertices=16, bevel=0.0003, component_type="grounding_stud"))
    label = add_text_mesh("PATCH_PORT_LABEL", "24 x CAT6 / RJ45", (0.0, 0.024, height * 0.90), min(0.004, max(0.002, height * 0.09)), materials["label"], collection=collections["RV_DETAIL"])
    if label:
        label["component_type"] = "patch_panel_label"
        objects.append(label)
    return objects


def _create_rear_shell(spec: dict[str, Any], width: float, depth: float, height: float, collections: dict[str, Any]) -> list[Any]:
    materials = spec["_materials"]
    asset_kind = str(spec.get("asset_kind") or "device").casefold()
    specialized_rear = bool(spec.get("rear_profile"))
    objects: list[Any] = []
    objects.append(add_box("REAR_PANEL", (max(0.01, width - 0.012), 0.006, max(0.01, height - 0.004)), (0.0, -depth - 0.003, height / 2.0), materials["panel"], collection=collections["RV_ASSET"], bevel=0.001, component_type="rear_panel"))
    power_type = str(spec.get("power_type") or "ac").casefold()
    psu_count = 0 if asset_kind == "patch_panel" or specialized_rear else max(1, min(4, int(spec.get("psu_count") or 2)))
    psu_width = min(0.125, max(0.075, width * 0.15))
    psu_height = min(height * 0.62, max(0.028, height * 0.68))
    for index in range(psu_count):
        x = -width / 2.0 + 0.085 + index * (psu_width + 0.012)
        objects.append(add_box(f"PSU_{index + 1:02d}", (psu_width, 0.012, psu_height), (x, -depth - 0.010, height * 0.50), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.002, component_type="power_supply"))
        if power_type == "dc":
            for terminal_index in range(2):
                objects.append(add_cylinder(f"PSU_{index + 1:02d}_DC_TERMINAL_{terminal_index + 1:02d}", 0.0032, 0.004, (x - psu_width * 0.20 + terminal_index * psu_width * 0.40, -depth - 0.019, height * 0.50), materials["accent"], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_DETAIL"], vertices=16, component_type="dc_terminal"))
        else:
            objects.append(add_box(f"PSU_{index + 1:02d}_IEC_INLET", (0.022, 0.003, 0.016), (x, -depth - 0.019, height * 0.50), materials["socket"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="ac_inlet"))
    fan_count = 0 if asset_kind == "patch_panel" or specialized_rear else max(1, min(6, int(spec.get("fan_count") or (2 if height < 0.15 else 4))))
    fan_left = -width / 2.0 + psu_count * (psu_width + 0.012) + 0.075
    fan_right = width / 2.0 - 0.075
    for index in range(fan_count):
        x = fan_left + (fan_right - fan_left) * ((index + 1) / (fan_count + 1))
        radius = min(0.036, max(0.018, height * 0.37))
        y = -depth - 0.011
        objects.append(add_cylinder(f"FAN_{index + 1:02d}_CENTER", radius * 0.88, 0.003, (x, y, height * 0.50), materials["vent"], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_DETAIL"], vertices=24, component_type="fan_center"))
        objects.append(add_torus(f"FAN_{index + 1:02d}_RING", radius * 0.78, max(0.001, radius * 0.09), (x, y - 0.002, height * 0.50), materials["steel"], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_DETAIL"], component_type="fan_grille"))
        for bar_index in range(4):
            bar = add_box(f"FAN_{index + 1:02d}_BAR_{bar_index + 1:02d}", (radius * 1.45, 0.002, 0.0025), (x, y - 0.004, height * 0.50), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.0004, component_type="fan_grille_bar")
            bar.rotation_euler[1] = bar_index * math.pi / 4.0
            objects.append(bar)
    if not specialized_rear:
        for index in range(8):
            x = -width / 2.0 + 0.030 + index * max(0.012, (width - 0.060) / 7.0)
            objects.append(add_box(f"REAR_VENT_SLOT_{index + 1:02d}", (0.006, 0.002, min(0.012, height * 0.22)), (x, -depth - 0.007, height * 0.17), materials["vent"], collection=collections["RV_DETAIL"], bevel=0.0004, component_type="rear_vent"))
    if asset_kind == "patch_panel":
        for index in range(6):
            x = -width / 2.0 + 0.045 + index * max(0.018, (width - 0.090) / 5.0)
            objects.append(add_box(f"REAR_CABLE_GUIDE_{index + 1:02d}", (0.010, 0.004, 0.014), (x, -depth - 0.010, height * 0.50), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="cable_guide"))
    return objects


def _create_s6800_rear_details(spec: dict[str, Any], width: float, depth: float, height: float, collections: dict[str, Any]) -> list[Any]:
    """Build the S6800 rear assembly shown in the supplied reference image.

    The S6800 front elevation is the three SFP+ banks plus two QSFP28 banks;
    its service elevation is a different assembly with the management block,
    five hot-swappable fan modules and two power modules.  Keeping this as a
    dedicated rear profile prevents the generic two-fan/two-PSU shell from
    erasing the product's recognizable modular layout.
    """

    materials = spec["_materials"]
    objects: list[Any] = []
    rear_y = -depth
    module_y = rear_y - 0.009
    face_y = rear_y - 0.016
    center_z = height * 0.50
    module_height = max(0.026, height - 0.008)

    def add_rear_label(name: str, text: str, x: float, z: float, size: float, component_type: str) -> None:
        label = add_text_mesh(
            name, text, (x, rear_y - 0.025, z), size, materials["label"], face="rear",
            collection=collections["RV_DETAIL"],
        )
        if label:
            label["component_type"] = component_type
            objects.append(label)

    # Left service/management block: optical management, electrical
    # management, console, mini-USB console and USB.  The two network ports
    # remain full semantic port assemblies so the runtime can attach links to
    # them just like the front-facing SFP/QSFP ports.
    mgmt_left = -width / 2.0 + 0.014
    mgmt_width = min(0.092, width * 0.22)
    mgmt_right = mgmt_left + mgmt_width
    for edge_name, dimensions, location in (
        ("TOP", (mgmt_width, 0.006, 0.002), ((mgmt_left + mgmt_right) / 2.0, module_y, height - 0.004)),
        ("BOTTOM", (mgmt_width, 0.006, 0.002), ((mgmt_left + mgmt_right) / 2.0, module_y, 0.004)),
        ("LEFT", (0.002, 0.006, module_height - 0.004), (mgmt_left, module_y, center_z)),
        ("RIGHT", (0.002, 0.006, module_height - 0.004), (mgmt_right, module_y, center_z)),
    ):
        objects.append(add_box(
            f"S6800_REAR_MGMT_FRAME_{edge_name}", dimensions, location, materials["steel"],
            collection=collections["RV_DETAIL"], bevel=0.00035, component_type="management_panel",
        ))

    objects.extend(_create_port(
        spec, name="PORT_REAR_SFP_001", index=1, group_name="MGMT OPTICAL", media_type="sfp",
        face="rear", x=mgmt_left + mgmt_width * 0.32, z=height * 0.65, surface_y=rear_y,
        collections=collections, port_scale=0.72,
    ))
    objects.extend(_create_port(
        spec, name="PORT_REAR_GE_002", index=2, group_name="MGMT ETH", media_type="copper",
        face="rear", x=mgmt_left + mgmt_width * 0.68, z=height * 0.65, surface_y=rear_y,
        collections=collections, port_scale=0.72,
    ))
    add_rear_label("S6800_REAR_MGMT_OPTICAL_LABEL", "MGMT", mgmt_left + mgmt_width * 0.32, height * 0.88, 0.0022, "management_label")
    add_rear_label("S6800_REAR_MGMT_ETH_LABEL", "MGMT", mgmt_left + mgmt_width * 0.68, height * 0.88, 0.0022, "management_label")

    small_port_z = height * 0.29
    small_ports = (
        ("CONSOLE", "CONSOLE_PORT", mgmt_left + mgmt_width * 0.18, 0.014, 0.006, materials["socket"]),
        ("MINI_USB", "MINI_USB_CONSOLE_PORT", mgmt_left + mgmt_width * 0.50, 0.010, 0.006, materials["socket"]),
        ("USB", "USB_PORT", mgmt_left + mgmt_width * 0.82, 0.014, 0.008, materials["socket"]),
    )
    for label_text, object_name, x, port_width, port_height, material in small_ports:
        objects.append(add_box(
            f"S6800_REAR_{object_name}", (port_width, 0.005, port_height), (x, face_y, small_port_z), material,
            collection=collections["RV_PORTS"], bevel=0.0005, component_type="service_port",
        ))
        if label_text == "USB":
            objects.append(add_box(
                "S6800_REAR_USB_INSERT", (port_width * 0.58, 0.0015, port_height * 0.48),
                (x, rear_y - 0.019, small_port_z), materials["led_blue"], collection=collections["RV_DETAIL"],
                bevel=0.00025, component_type="usb_insert",
            ))
        add_rear_label(
            f"S6800_REAR_{object_name}_LABEL", label_text, x, height * 0.12, 0.0021,
            "service_port_label",
        )

    # System and management link/activity indicators sit beneath the service
    # ports, matching the two status indicators in the reference panel.
    for index, (name, material_key, x) in enumerate((
        ("SYS", "led_blue", mgmt_left + mgmt_width * 0.32),
        ("MGMT_LINK", "led_green", mgmt_left + mgmt_width * 0.68),
    ), start=1):
        objects.append(add_cylinder(
            f"S6800_REAR_STATUS_LED_{index:02d}", 0.0020, 0.002, (x, rear_y - 0.022, height * 0.26),
            materials[material_key], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_DETAIL"],
            vertices=16, bevel=0.0002, component_type="status_led",
        ))
        add_rear_label(f"S6800_REAR_STATUS_LED_{index:02d}_LABEL", name, x, height * 0.38, 0.0019, "status_label")

    # Five identical hot-swappable fan modules with a dark hexagonal grille,
    # central hub/ring, blade bars and the characteristic red extraction tabs.
    fan_count = max(1, min(6, int(spec.get("rear_fan_count") or 5)))
    fan_width = min(0.041, max(0.030, width * 0.095))
    fan_gap = 0.005
    fan_bank_width = fan_count * fan_width + (fan_count - 1) * fan_gap
    fan_left = -width / 2.0 + 0.112
    fan_grille_y = rear_y - 0.020
    for index in range(fan_count):
        x = fan_left + fan_width / 2.0 + index * (fan_width + fan_gap)
        objects.append(add_box(
            f"S6800_REAR_FAN_MODULE_{index + 1:02d}_FRAME", (fan_width, 0.008, module_height),
            (x, module_y, center_z), materials["steel"], collection=collections["RV_DETAIL"],
            bevel=0.0012, component_type="fan_module",
        ))
        objects.append(add_box(
            f"S6800_REAR_FAN_MODULE_{index + 1:02d}_INNER", (fan_width - 0.008, 0.004, module_height - 0.006),
            (x, rear_y - 0.014, center_z), materials["socket"], collection=collections["RV_DETAIL"],
            bevel=0.0007, component_type="fan_faceplate",
        ))
        for handle_side, handle_x in (("L", x - fan_width / 2.0 + 0.003), ("R", x + fan_width / 2.0 - 0.003)):
            objects.append(add_box(
                f"S6800_REAR_FAN_MODULE_{index + 1:02d}_HANDLE_{handle_side}",
                (0.004, 0.006, module_height * 0.70), (handle_x, face_y, center_z), materials["module_red"],
                collection=collections["RV_MOUNTING"], bevel=0.0007, component_type="fan_handle",
            ))
        for row in range(4):
            for column in range(4):
                hx = x - fan_width * 0.30 + column * fan_width * 0.20
                hz = center_z - module_height * 0.26 + row * module_height * 0.17
                objects.append(add_cylinder(
                    f"S6800_REAR_FAN_MODULE_{index + 1:02d}_GRILLE_{row + 1:02d}_{column + 1:02d}",
                    0.0022, 0.0012, (hx, fan_grille_y, hz), materials["vent"],
                    rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_DETAIL"], vertices=6,
                    bevel=0.00015, component_type="fan_grille",
                ))
        objects.append(add_torus(
            f"S6800_REAR_FAN_MODULE_{index + 1:02d}_RING", 0.012, 0.0012,
            (x, rear_y - 0.022, center_z), materials["steel"], rotation=(math.pi / 2.0, 0.0, 0.0),
            collection=collections["RV_DETAIL"], component_type="fan_grille_ring",
        ))
        objects.append(add_cylinder(
            f"S6800_REAR_FAN_MODULE_{index + 1:02d}_HUB", 0.0055, 0.0018,
            (x, rear_y - 0.023, center_z), materials["steel"], rotation=(math.pi / 2.0, 0.0, 0.0),
            collection=collections["RV_DETAIL"], vertices=16, bevel=0.00025, component_type="fan_hub",
        ))
        for blade_index in range(4):
            blade = add_box(
                f"S6800_REAR_FAN_MODULE_{index + 1:02d}_BLADE_{blade_index + 1:02d}",
                (0.014, 0.0012, 0.0018), (x, rear_y - 0.024, center_z), materials["vent"],
                collection=collections["RV_DETAIL"], bevel=0.00015, component_type="fan_blade",
            )
            blade.rotation_euler[1] = blade_index * math.pi / 4.0
            objects.append(blade)
        add_rear_label(
            f"S6800_REAR_FAN_MODULE_{index + 1:02d}_LABEL", f"FAN {index + 1}", x, height * 0.90, 0.0020,
            "fan_module_label",
        )

    # Two hot-swappable AC power modules occupy the right side.  Red release
    # tabs, IEC sockets, contact bars and green status lenses keep them
    # visually distinct from a plain rectangular rear shell.
    psu_count = max(1, min(4, int(spec.get("rear_psu_count") or 2)))
    psu_width = min(0.046, max(0.036, width * 0.105))
    psu_gap = 0.008
    psu_left = fan_left + fan_bank_width + 0.010
    for index in range(psu_count):
        x = psu_left + psu_width / 2.0 + index * (psu_width + psu_gap)
        objects.append(add_box(
            f"S6800_REAR_PSU_{index + 1:02d}_FRAME", (psu_width, 0.008, module_height),
            (x, module_y, center_z), materials["steel"], collection=collections["RV_DETAIL"],
            bevel=0.0012, component_type="power_supply",
        ))
        objects.append(add_box(
            f"S6800_REAR_PSU_{index + 1:02d}_INNER", (psu_width - 0.008, 0.004, module_height - 0.006),
            (x, rear_y - 0.014, center_z), materials["panel"], collection=collections["RV_DETAIL"],
            bevel=0.0007, component_type="power_supply_faceplate",
        ))
        objects.append(add_box(
            f"S6800_REAR_PSU_{index + 1:02d}_HANDLE", (0.004, 0.006, module_height * 0.72),
            (x - psu_width / 2.0 + 0.003, face_y, center_z), materials["module_red"],
            collection=collections["RV_MOUNTING"], bevel=0.0007, component_type="power_handle",
        ))
        objects.append(add_box(
            f"S6800_REAR_PSU_{index + 1:02d}_IEC_INLET", (0.022, 0.004, 0.015),
            (x + psu_width * 0.08, rear_y - 0.020, center_z), materials["socket"],
            collection=collections["RV_PORTS"], bevel=0.0007, component_type="ac_inlet",
        ))
        for contact_index in range(2):
            objects.append(add_box(
                f"S6800_REAR_PSU_{index + 1:02d}_IEC_CONTACT_{contact_index + 1:02d}",
                (0.002, 0.0015, 0.006),
                (x + psu_width * 0.01 + contact_index * 0.010, rear_y - 0.022, center_z), materials["steel"],
                collection=collections["RV_DETAIL"], bevel=0.00015, component_type="ac_contact",
            ))
        objects.append(add_cylinder(
            f"S6800_REAR_PSU_{index + 1:02d}_STATUS_LED", 0.0018, 0.0018,
            (x + psu_width * 0.23, rear_y - 0.022, height * 0.23), materials["led_green"],
            rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_DETAIL"], vertices=16,
            bevel=0.00015, component_type="status_led",
        ))
        add_rear_label(
            f"S6800_REAR_PSU_{index + 1:02d}_LABEL", f"PWR {index + 1}", x, height * 0.90, 0.0020,
            "power_supply_label",
        )
    add_rear_label("S6800_REAR_POWER_LABEL", "AC INPUT", psu_left + (psu_count * psu_width + (psu_count - 1) * psu_gap) / 2.0, height * 0.12, 0.0021, "power_label")
    return objects


def _create_mounting_ears(spec: dict[str, Any], width: float, height: float, collections: dict[str, Any]) -> list[Any]:
    materials = spec["_materials"]
    objects: list[Any] = []
    rack_width = float(spec.get("rack_width_mm") or 482.6) / 1000.0
    extension = max(0.0, (rack_width - width) / 2.0)
    ear_width = max(0.010, extension + 0.008)
    height_u = max(1, int(spec.get("height_u") or round(height / U_METERS)))
    hole_count = 2 if height_u <= 1 else min(9, height_u + 1)
    for side, sign in (("L", -1.0), ("R", 1.0)):
        x = sign * (width / 2.0 + extension / 2.0)
        objects.append(add_box(f"RACK_EAR_{side}", (ear_width, 0.014, max(0.010, height - 0.004)), (x, 0.008, height / 2.0), materials["steel"], collection=collections["RV_MOUNTING"], bevel=0.001, component_type="rack_mounting_ear"))
        for index in range(hole_count):
            z = height * 0.50 if hole_count == 1 else 0.006 + index * max(0.001, (height - 0.012) / (hole_count - 1))
            objects.append(add_torus(f"RACK_HOLE_RING_{side}_{index + 1:02d}", 0.0048, 0.0010, (x, 0.016, z), materials["steel"], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_MOUNTING"], component_type="rack_mounting_hole_ring"))
            objects.append(add_cylinder(f"RACK_HOLE_{side}_{index + 1:02d}", 0.0038, 0.002, (x, 0.015, z), materials["socket"], rotation=(math.pi / 2.0, 0.0, 0.0), collection=collections["RV_MOUNTING"], vertices=20, component_type="rack_mounting_hole"))
    return objects


def _create_top_vents(spec: dict[str, Any], width: float, depth: float, height: float, collections: dict[str, Any]) -> list[Any]:
    materials = spec["_materials"]
    objects: list[Any] = []
    slot_count = max(8, min(32, int(width / 0.018)))
    for index in range(slot_count):
        x = -width / 2.0 + 0.020 + index * max(0.010, (width - 0.040) / max(1, slot_count - 1))
        objects.append(add_box(f"TOP_VENT_SLOT_{index + 1:02d}", (0.0045, min(0.16, depth * 0.24), 0.0018), (x, -depth * 0.70, height + 0.001), materials["vent"], collection=collections["RV_DETAIL"], bevel=0.00025, component_type="top_vent"))
    return objects


def _create_standard_ports(spec: dict[str, Any], width: float, height: float, depth: float, collections: dict[str, Any]) -> list[Any]:
    materials = spec["_materials"]
    objects: list[Any] = []
    groups = _port_groups(spec)
    default_left_margin = min(0.105, width * 0.24)
    left = -width / 2.0 + max(0.018, float(spec.get("port_left_margin_m") or default_left_margin))
    right = width / 2.0 - max(0.012, float(spec.get("port_right_margin_m") or 0.026))
    usable_width = max(0.08, right - left)
    total_count = max(1, sum(int(group.get("count") or 0) for group in groups))
    group_gap = min(0.010, max(0.004, float(spec.get("port_group_gap_m") or (0.008 if len(groups) > 1 else 0.0))))
    ratio_total = sum(max(0.01, float(group.get("width_ratio") or int(group.get("count") or 0) / total_count)) for group in groups)
    distributable_width = max(0.06, usable_width - group_gap * max(0, len(groups) - 1))
    cursor = left
    port_index = 1
    for group_index, group in enumerate(groups, start=1):
        count = int(group.get("count") or 0)
        if count <= 0:
            continue
        ratio = max(0.01, float(group.get("width_ratio") or count / total_count))
        bank_left = cursor
        bank_width = usable_width if len(groups) == 1 else distributable_width * ratio / ratio_total
        bank_right = right if len(groups) == 1 else min(right, cursor + bank_width)
        cursor = bank_right + (group_gap if len(groups) > 1 else 0.0)
        columns = max(1, min(count, int(group.get("columns") or min(count, 24))))
        rows = max(1, math.ceil(count / columns))
        media_type = str(group.get("media_type") or spec.get("port_media_type") or "copper")
        port_width, _projection, port_height = _port_dimensions(media_type)
        row_gap = min(0.008, max(0.002, height * 0.08))
        total_height = rows * port_height + max(0, rows - 1) * row_gap
        z_bottom = float(group.get("z_center") or height * 0.47) - total_height / 2.0
        group_name = str(group.get("name") or _media_token(media_type))
        group_token = _media_token(media_type)
        port_scale = float(group.get("port_scale") or spec.get("port_scale") or 1.0)
        if str(spec.get("include_port_group_labels", True)).casefold() not in {"0", "false", "no"}:
            group_label = add_text_mesh(
                f"PORT_GROUP_{group_index:02d}_{group_token}_LABEL", group_name[:16],
                ((bank_left + bank_right) / 2.0, 0.022, min(height - 0.004, z_bottom + total_height + 0.006)),
                min(0.0036, max(0.0022, height * 0.075)), materials["label"], collection=collections["RV_DETAIL"],
            )
            if group_label:
                group_label["component_type"] = "port_group_label"
                objects.append(group_label)
        for boundary_name, boundary_x in (("LEFT", bank_left), ("RIGHT", bank_right)):
            objects.append(add_box(
                f"PORT_GROUP_{group_index:02d}_{group_token}_DIVIDER_{boundary_name}",
                (0.0018, 0.0025, total_height + 0.008),
                (boundary_x, 0.016, z_bottom + total_height / 2.0), materials["accent"],
                collection=collections["RV_DETAIL"], bevel=0.0002, component_type="port_group_divider",
            ))
        for offset in range(count):
            row = offset // columns
            column = offset % columns
            x = (bank_left + bank_right) / 2.0 if columns == 1 else bank_left + column * ((bank_right - bank_left) / max(1, columns - 1))
            z = z_bottom + port_height / 2.0 + row * (port_height + row_gap)
            objects.extend(_create_port(spec, name=f"PORT_{_media_token(media_type)}_{port_index:03d}", index=port_index, group_name=group_name, media_type=media_type, face="front", x=x, z=z, surface_y=FRONT_Y, collections=collections, port_scale=port_scale))
            port_index += 1
    rear_specs = [] if spec.get("rear_profile") else (spec.get("rear_ports") or [])
    if isinstance(rear_specs, list):
        rear_index = 1
        for raw in rear_specs:
            if not isinstance(raw, dict):
                continue
            media_type = str(raw.get("media_type") or "mgmt")
            count = max(0, min(8, int(raw.get("count") or 1)))
            for offset in range(count):
                objects.extend(_create_port(spec, name=f"PORT_REAR_{_media_token(media_type)}_{rear_index:03d}", index=rear_index, group_name=str(raw.get("name") or _media_token(media_type)), media_type=media_type, face="rear", x=-width * 0.12 + offset * 0.035, z=height * 0.58, surface_y=-depth, collections=collections))
                rear_index += 1
    return objects


def _create_modular_ports(spec: dict[str, Any], width: float, height: float, collections: dict[str, Any]) -> list[Any]:
    materials = spec["_materials"]
    objects: list[Any] = []
    bay_count = max(1, min(8, int(spec.get("module_bays") or 4)))
    ports_per_bay = max(0, min(32, int(spec.get("ports_per_bay") or 8)))
    total_width = width - 0.115
    gap = 0.008
    bay_width = (total_width - (bay_count - 1) * gap) / bay_count
    bay_left = -width / 2.0 + 0.085
    global_index = 1
    for bay_index in range(bay_count):
        center = bay_left + bay_width / 2.0 + bay_index * (bay_width + gap)
        objects.append(add_box(f"MODULE_BAY_{bay_index + 1:02d}_FRAME", (bay_width, 0.012, height * 0.76), (center, 0.008, height * 0.48), materials["cage"], collection=collections["RV_DETAIL"], bevel=0.002, component_type="module_bay_frame"))
        objects.append(add_box(f"MODULE_BAY_{bay_index + 1:02d}_INNER", (bay_width - 0.016, 0.005, height * 0.70), (center, 0.015, height * 0.48), materials["panel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="module_faceplate"))
        objects.append(add_box(f"MODULE_BAY_{bay_index + 1:02d}_HANDLE", (bay_width * 0.76, 0.004, 0.010), (center, 0.019, height * 0.14), materials["steel"], collection=collections["RV_MOUNTING"], bevel=0.001, component_type="module_handle"))
        label = add_text_mesh(f"MODULE_BAY_{bay_index + 1:02d}_LABEL", f"LINE CARD {bay_index + 1:02d}", (center, 0.021, height * 0.83), min(0.008, height * 0.055), materials["label"], collection=collections["RV_DETAIL"])
        if label:
            objects.append(label)
        if ports_per_bay <= 0:
            continue
        columns = max(1, min(8, int(spec.get("module_port_columns") or 4)))
        rows = max(1, math.ceil(ports_per_bay / columns))
        media_type = str(spec.get("module_port_media_type") or "sfp")
        _port_width, _projection, port_height = _port_dimensions(media_type)
        port_left = center - bay_width / 2.0 + 0.020
        port_right = center + bay_width / 2.0 - 0.020
        port_top = height * 0.67
        for offset in range(ports_per_bay):
            row = offset // columns
            column = offset % columns
            x = (port_left + port_right) / 2.0 if columns == 1 else port_left + column * ((port_right - port_left) / max(1, columns - 1))
            z = port_top - row * (port_height + min(0.010, height * 0.025))
            objects.extend(_create_port(spec, name=f"PORT_{_media_token(media_type)}_{global_index:03d}", index=global_index, group_name=f"MODULE_{bay_index + 1:02d}", media_type=media_type, face="front", x=x, z=z, surface_y=0.020, collections=collections))
            global_index += 1
    return objects


def create_device(spec: dict[str, Any]) -> list[Any]:
    """Create a detailed RackVision asset from a reviewed JSON spec."""

    runtime = require_blender()
    configure_scene()
    collections = _new_collections()
    asset_key = str(spec.get("asset_key") or "generic_device")
    vendor = str(spec.get("vendor") or "generic")
    model = str(spec.get("exact_model") or spec.get("model") or asset_key)
    template = str(spec.get("template") or "switch_1u")
    height_u = max(1, int(spec.get("height_u") or (1 if "1u" in template.casefold() else 2)))
    width_mm = float(spec.get("width_mm") or 440.0)
    depth_mm = float(spec.get("depth_mm") or 400.0)
    height_mm = float(spec.get("height_mm") or height_u * 44.45)
    width, depth, height = width_mm / 1000.0, depth_mm / 1000.0, height_mm / 1000.0
    accent_color_raw = spec.get("accent_color")
    if isinstance(accent_color_raw, (list, tuple)) and len(accent_color_raw) >= 3:
        accent_color = tuple(max(0.0, min(1.0, float(value))) for value in accent_color_raw[:3]) + (1.0,)
    else:
        accent_color = (0.74, 0.42, 0.08, 1.0)
    materials = {
        "chassis": make_material("MAT_CHASSIS", (0.105, 0.125, 0.155, 1.0), roughness=0.40, metallic=0.78),
        "panel": make_material("MAT_FRONT_PANEL", (0.035, 0.045, 0.060, 1.0), roughness=0.34, metallic=0.68),
        "steel": make_material("MAT_BRUSHED_STEEL", (0.30, 0.34, 0.39, 1.0), roughness=0.28, metallic=0.92),
        "socket": make_material("MAT_SOCKET_BLACK", (0.006, 0.009, 0.014, 1.0), roughness=0.24, metallic=0.25),
        "cage": make_material("MAT_PORT_CAGE", (0.075, 0.090, 0.110, 1.0), roughness=0.32, metallic=0.72),
        "accent": make_material("MAT_CONTACT_GOLD", accent_color, roughness=0.22, metallic=0.88),
        "module_red": make_material("MAT_MODULE_RED", (0.68, 0.025, 0.045, 1.0), roughness=0.30, metallic=0.58),
        "label": make_material("MAT_LABEL", (0.68, 0.75, 0.82, 1.0), roughness=0.30, metallic=0.28),
        "vent": make_material("MAT_VENT", (0.012, 0.016, 0.022, 1.0), roughness=0.48, metallic=0.55),
        "led": make_material("MAT_LED_PORT", (0.02, 0.42, 0.20, 1.0), roughness=0.18, emission=(0.02, 1.0, 0.20, 1.0), emission_strength=3.0),
        "led_green": make_material("MAT_LED_GREEN", (0.02, 0.42, 0.20, 1.0), roughness=0.18, emission=(0.02, 1.0, 0.20, 1.0), emission_strength=3.0),
        "led_blue": make_material("MAT_LED_BLUE", (0.02, 0.25, 0.70, 1.0), roughness=0.18, emission=(0.05, 0.30, 1.0, 1.0), emission_strength=2.5),
        "led_amber": make_material("MAT_LED_AMBER", (0.70, 0.20, 0.02, 1.0), roughness=0.18, emission=(1.0, 0.24, 0.02, 1.0), emission_strength=2.8),
    }
    spec = dict(spec)
    spec["_materials"] = materials
    scene = runtime.context.scene
    asset_kind = str(spec.get("asset_kind") or "device")
    scene["rackvision_schema_version"] = SCHEMA_VERSION
    scene["rackvision_asset_kind"] = asset_kind
    scene["rackvision_asset_key"] = asset_key
    scene["rackvision_vendor"] = vendor
    scene["rackvision_model"] = model
    scene["rackvision_template"] = template
    scene["rackvision_width_mm"] = width_mm
    scene["rackvision_depth_mm"] = depth_mm
    scene["rackvision_height_mm"] = height_mm
    scene["rackvision_height_u"] = height_u
    scene["rackvision_front_direction"] = "+Y"
    scene["rackvision_port_count"] = _port_count(spec)
    scene["rackvision_metadata_json"] = json.dumps({
        "asset_key": asset_key, "vendor": vendor, "model": model, "template": template,
        "dimensions_mm": {"width": width_mm, "depth": depth_mm, "height": height_mm},
        "height_u": height_u, "coordinate_system": "X=left_right,Y=front_back,Z=vertical",
        "front_direction": "+Y", "schema_version": SCHEMA_VERSION,
        "production_baseline": True,
        "oem_accuracy": str(spec.get("dimension_status") or "") == "verified_official",
    }, ensure_ascii=False, sort_keys=True)
    objects: list[Any] = []
    root = add_empty("ASSET_ROOT", (0.0, 0.0, 0.0), collection=collections["RV_ASSET"], display_size=0.01)
    _tag_object(root, spec, "asset_root")
    root["asset_origin"] = "BODY_BOTTOM_FRONT_CENTER"
    objects.append(root)
    body = add_box("BODY", (width, depth, height), (0.0, -depth / 2.0, height / 2.0), materials["chassis"], collection=collections["RV_ASSET"], bevel=min(0.004, min(width, depth, height) * 0.08), component_type="chassis_body")
    _tag_object(body, spec, "chassis_body")
    body["dimensions_mm_width"] = width_mm
    body["dimensions_mm_depth"] = depth_mm
    body["dimensions_mm_height"] = height_mm
    objects.append(body)
    objects.extend(_create_front_shell(spec, width, height, collections))
    if asset_kind.casefold() == "patch_panel":
        objects.extend(_create_patch_panel_details(spec, width, height, collections))
    objects.extend(_create_rear_shell(spec, width, depth, height, collections))
    if spec.get("rear_profile") == "s6800_modular":
        objects.extend(_create_s6800_rear_details(spec, width, depth, height, collections))
    objects.extend(_create_mounting_ears(spec, width, height, collections))
    objects.extend(_create_top_vents(spec, width, depth, height, collections))
    if "modular" in template.casefold() or height_u >= 4:
        objects.extend(_create_modular_ports(spec, width, height, collections))
    else:
        objects.extend(_create_standard_ports(spec, width, height, depth, collections))
    for obj in objects:
        _tag_object(obj, spec)
    return objects


def create_rack(spec: dict[str, Any]) -> list[Any]:
    """Create a reusable cabinet shell in the same metric coordinate contract."""

    runtime = require_blender()
    configure_scene()
    collections = _new_collections()
    spec = dict(spec)
    asset_key = str(spec.get("asset_key") or "rack_42u_600x1000")
    vendor = str(spec.get("vendor") or "generic")
    model = str(spec.get("exact_model") or spec.get("model") or asset_key)
    height_u = max(1, int(spec.get("height_u") or 42))
    width_mm = float(spec.get("width_mm") or 600.0)
    depth_mm = float(spec.get("depth_mm") or 1000.0)
    height_mm = float(spec.get("height_mm") or height_u * 44.45)
    width = width_mm / 1000.0
    depth = depth_mm / 1000.0
    height = height_mm / 1000.0

    materials = {
        # The viewer uses a dark studio environment.  These values keep the
        # graphite cabinet readable without turning the side panels into a
        # featureless black slab.
        "chassis": make_material("MAT_RACK_CHASSIS", (0.120, 0.150, 0.195, 1.0), roughness=0.38, metallic=0.46),
        "panel": make_material("MAT_RACK_PANEL", (0.085, 0.110, 0.145, 1.0), roughness=0.48, metallic=0.18),
        "steel": make_material("MAT_RACK_STEEL", (0.38, 0.46, 0.57, 1.0), roughness=0.30, metallic=0.68),
        "socket": make_material("MAT_RACK_SOCKET", (0.004, 0.007, 0.012, 1.0), roughness=0.24, metallic=0.28),
        "accent": make_material("MAT_RACK_ACCENT", (0.025, 0.38, 0.70, 1.0), roughness=0.24, metallic=0.72),
        "label": make_material("MAT_RACK_LABEL", (0.62, 0.80, 0.96, 1.0), roughness=0.28, metallic=0.26),
        "vent": make_material("MAT_RACK_VENT", (0.018, 0.028, 0.046, 1.0), roughness=0.54, metallic=0.20),
    }
    spec["_materials"] = materials
    scene = runtime.context.scene
    scene["rackvision_schema_version"] = SCHEMA_VERSION
    scene["rackvision_asset_kind"] = "rack"
    scene["rackvision_asset_key"] = asset_key
    scene["rackvision_vendor"] = vendor
    scene["rackvision_model"] = model
    scene["rackvision_template"] = "rack"
    scene["rackvision_width_mm"] = width_mm
    scene["rackvision_depth_mm"] = depth_mm
    scene["rackvision_height_mm"] = height_mm
    scene["rackvision_height_u"] = height_u
    scene["rackvision_front_direction"] = "+Y"
    scene["rackvision_port_count"] = 0
    scene["rackvision_metadata_json"] = json.dumps({
        "asset_key": asset_key,
        "vendor": vendor,
        "model": model,
        "asset_kind": "rack",
        "dimensions_mm": {"width": width_mm, "depth": depth_mm, "height": height_mm},
        "height_u": height_u,
        "coordinate_system": "X=left_right,Y=front_back,Z=vertical",
        "front_direction": "+Y",
        "schema_version": SCHEMA_VERSION,
        "production_baseline": True,
        "oem_accuracy": False,
    }, ensure_ascii=False, sort_keys=True)

    objects: list[Any] = []
    root = add_empty("ASSET_ROOT", (0.0, 0.0, 0.0), collection=collections["RV_ASSET"], display_size=0.025)
    _tag_object(root, spec, "asset_root")
    root["asset_origin"] = "RACK_BOTTOM_FRONT_CENTER"
    objects.append(root)

    # RACK_BODY is a semantic envelope marker, not a rendered solid.  A
    # front-facing slab here would occlude the installed equipment GLBs in
    # the viewer; the cabinet's visible envelope is represented by the posts,
    # cap, base, side/rear panels, rails, and door frame below.
    body = add_empty("RACK_BODY", (0.0, 0.0, height / 2.0), collection=collections["RV_ASSET"], display_size=0.025)
    body["component_type"] = "rack_body"
    _tag_object(body, spec, "rack_body")
    body["dimensions_mm_width"] = width_mm
    body["dimensions_mm_depth"] = depth_mm
    body["dimensions_mm_height"] = height_mm
    objects.append(body)

    post_size = 0.045
    post_x = width / 2.0 - post_size / 2.0
    post_y_front = -0.035
    post_y_rear = -depth + 0.035
    post_height = max(0.10, height - 0.08)
    for side, x in (("L", -post_x), ("R", post_x)):
        for position, y in (("FRONT", post_y_front), ("REAR", post_y_rear)):
            objects.append(add_box(f"RACK_POST_{position}_{side}", (post_size, post_size, post_height), (x, y, 0.04 + post_height / 2.0), materials["steel"], collection=collections["RV_MOUNTING"], bevel=0.002, component_type="rack_post"))

    objects.append(add_box("RACK_TOP_CAP", (width + 0.02, depth + 0.02, 0.070), (0.0, -depth / 2.0, height - 0.035), materials["chassis"], collection=collections["RV_ASSET"], bevel=0.004, component_type="rack_top_cap"))
    objects.append(add_box("RACK_BASE", (width + 0.02, depth + 0.02, 0.080), (0.0, -depth / 2.0, 0.040), materials["socket"], collection=collections["RV_ASSET"], bevel=0.004, component_type="rack_base"))

    # Thin side and rear panels add cabinet mass without occluding the front
    # equipment; the rear panel remains visible in the rear camera preset.
    panel_height = max(0.10, height - 0.14)
    panel_depth = max(0.10, depth - 0.12)
    objects.append(add_box("RACK_SIDE_PANEL_L", (0.012, panel_depth, panel_height), (-width / 2.0 + 0.006, -depth / 2.0, height / 2.0), materials["panel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_side_panel"))
    objects.append(add_box("RACK_SIDE_PANEL_R", (0.012, panel_depth, panel_height), (width / 2.0 - 0.006, -depth / 2.0, height / 2.0), materials["panel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_side_panel"))
    # The rear must remain inspectable: a solid back sheet would occlude the
    # installed equipment's fan/PSU/service face in the rear camera.  Keep a
    # recessed perimeter instead, matching the open front reference while
    # preserving a recognizable cabinet frame.
    rear_y = -depth + 0.006
    rear_frame_depth = 0.018
    rear_side_width = 0.032
    rear_top_bottom_height = 0.042
    objects.append(add_box("RACK_REAR_PANEL", (width - 0.090, rear_frame_depth, rear_top_bottom_height), (0.0, rear_y, height - 0.112), materials["socket"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_rear_panel"))
    objects.append(add_box("RACK_REAR_PANEL_BOTTOM", (width - 0.090, rear_frame_depth, rear_top_bottom_height), (0.0, rear_y, 0.112), materials["socket"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_rear_panel"))
    objects.append(add_box("RACK_REAR_PANEL_LEFT", (rear_side_width, rear_frame_depth, panel_height - 0.084), (-width / 2.0 + 0.045, rear_y, height / 2.0), materials["socket"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_rear_panel"))
    objects.append(add_box("RACK_REAR_PANEL_RIGHT", (rear_side_width, rear_frame_depth, panel_height - 0.084), (width / 2.0 - 0.045, rear_y, height / 2.0), materials["socket"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_rear_panel"))

    # Shallow side ventilation ribs break up the large panel surface while
    # remaining physically plausible for a closed data-centre cabinet.
    side_vent_count = max(8, min(14, int(height / 0.13)))
    for side, sign in (("L", -1.0), ("R", 1.0)):
        x = sign * (width / 2.0 + 0.010)
        for index in range(side_vent_count):
            z = 0.18 + index * ((height - 0.36) / max(1, side_vent_count - 1))
            objects.append(add_box(
                f"RACK_SIDE_VENT_{side}_{index + 1:02d}",
                (0.012, max(0.30, depth * 0.58), 0.006),
                (x, -depth * 0.50, z),
                materials["vent"],
                collection=collections["RV_DETAIL"],
                bevel=0.0005,
                component_type="rack_side_vent",
            ))

    # 19-inch front/rear mounting rails and repeated U reference slots.
    rail_x = min(width * 0.42, 0.4826 / 2.0)
    rail_height = max(0.10, height - 0.16)
    for side, x in (("L", -rail_x), ("R", rail_x)):
        objects.append(add_box(f"RACK_RAIL_FRONT_{side}", (0.028, 0.050, rail_height), (x, -0.070, height / 2.0), materials["steel"], collection=collections["RV_MOUNTING"], bevel=0.001, component_type="rack_mounting_rail"))
        objects.append(add_box(f"RACK_RAIL_REAR_{side}", (0.028, 0.050, rail_height), (x, -depth + 0.070, height / 2.0), materials["steel"], collection=collections["RV_MOUNTING"], bevel=0.001, component_type="rack_mounting_rail"))
        for u in range(1, height_u + 1):
            z = (u - 0.5) * U_METERS
            objects.append(add_box(f"RACK_U_SLOT_{side}_{u:02d}", (0.014, 0.008, 0.008), (x, -0.101, z), materials["socket"], collection=collections["RV_MOUNTING"], bevel=0.0005, component_type="rack_u_slot"))

    # Perimeter-only front door frame: the opening remains clear so the GLB
    # device faces are visible in the normal front camera.
    door_y = 0.024
    objects.append(add_box("RACK_FRONT_HEADER", (width - 0.110, 0.038, 0.075), (0.0, 0.048, height - 0.105), materials["chassis"], collection=collections["RV_DETAIL"], bevel=0.002, component_type="rack_front_header"))
    objects.append(add_box("RACK_STATUS_STRIP", (width * 0.62, 0.010, 0.008), (0.0, 0.071, height - 0.105), materials["accent"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_status_strip"))
    objects.append(add_box("RACK_DOOR_TOP", (width - 0.070, 0.026, 0.026), (0.0, door_y, height - 0.095), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_door_frame"))
    objects.append(add_box("RACK_DOOR_BOTTOM", (width - 0.070, 0.026, 0.026), (0.0, door_y, 0.095), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_door_frame"))
    objects.append(add_box("RACK_DOOR_LEFT", (0.026, 0.026, height - 0.190), (-width / 2.0 + 0.048, door_y, height / 2.0), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_door_frame"))
    objects.append(add_box("RACK_DOOR_RIGHT", (0.026, 0.026, height - 0.190), (width / 2.0 - 0.048, door_y, height / 2.0), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.001, component_type="rack_door_frame"))
    objects.append(add_box("RACK_DOOR_LATCH", (0.018, 0.032, 0.240), (width / 2.0 - 0.108, 0.060, height / 2.0), materials["steel"], collection=collections["RV_DETAIL"], bevel=0.002, component_type="rack_door_latch"))

    # Top ventilation, cable entry, feet and a readable asset plate.
    for index in range(12):
        x = -width * 0.35 + index * (width * 0.70 / 11.0)
        objects.append(add_box(f"RACK_TOP_VENT_{index + 1:02d}", (0.012, depth * 0.28, 0.004), (x, -depth * 0.55, height + 0.002), materials["vent"], collection=collections["RV_DETAIL"], bevel=0.0004, component_type="rack_top_vent"))
    for index, (x, y) in enumerate(((-post_x, post_y_front), (post_x, post_y_front), (-post_x, post_y_rear), (post_x, post_y_rear)), start=1):
        objects.append(add_cylinder(f"RACK_CASTER_{index:02d}", 0.055, 0.100, (x, y, -0.050), materials["socket"], collection=collections["RV_MOUNTING"], vertices=20, bevel=0.002, component_type="rack_caster"))
    label = add_text_mesh("RACK_LABEL", str(spec.get("front_label") or "NEXORA RACK"), (0.0, 0.044, height - 0.052), 0.018, materials["label"], collection=collections["RV_DETAIL"])
    if label:
        objects.append(label)
    model_label = add_text_mesh("RACK_MODEL_LABEL", str(spec.get("front_model_label") or f"{height_u}U / {int(width_mm)}x{int(depth_mm)}"), (0.0, 0.044, height - 0.082), 0.010, materials["label"], collection=collections["RV_DETAIL"])
    if model_label:
        objects.append(model_label)

    for obj in objects:
        _tag_object(obj, spec)
    return objects


__all__ = ["BLENDER_UNIT_METERS", "U_METERS", "FRONT_Y", "SCHEMA_VERSION", "BlenderRuntimeUnavailable", "configure_scene", "create_device", "create_rack", "require_blender", "reset_scene"]
