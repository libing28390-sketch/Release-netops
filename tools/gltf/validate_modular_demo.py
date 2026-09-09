#!/usr/bin/env python3
"""Validate normalized modular-demo GLBs against the Nexora hand-off contract."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from normalize_modular_demo import SCHEMA_VERSION, read_glb


REQUIRED_MATERIALS = {
    "MAT_CHASSIS",
    "MAT_FRONT_PANEL",
    "MAT_BRUSHED_STEEL",
    "MAT_PORT",
    "MAT_SOCKET_BLACK",
    "MAT_LABEL",
    "MAT_LED_GREEN",
}


def validate(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        document, _ = read_glb(path)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    asset_extras = (document.get("asset") or {}).get("extras") or {}
    if asset_extras.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"asset schema_version is not {SCHEMA_VERSION}")
    if asset_extras.get("coordinate_system") != "X=left_right,Y=front_back,Z=vertical":
        issues.append("asset coordinate_system is not Nexora standard")
    if asset_extras.get("front_direction") != "+Y":
        issues.append("asset front_direction is not +Y")
    if not asset_extras.get("asset_key"):
        issues.append("asset extras missing asset_key")

    material_names = {str(item.get("name") or "") for item in document.get("materials", [])}
    missing_materials = sorted(REQUIRED_MATERIALS - material_names)
    if missing_materials:
        issues.append(f"missing materials: {', '.join(missing_materials)}")

    nodes = document.get("nodes", [])
    names = [str(node.get("name") or "") for node in nodes]
    duplicate_names = sorted({name for name in names if name and names.count(name) > 1})
    if duplicate_names:
        issues.append(f"duplicate node names: {', '.join(duplicate_names[:8])}")
    root_nodes = [node for node in nodes if node.get("name") == "ASSET_ROOT"]
    if len(root_nodes) != 1:
        issues.append("exactly one ASSET_ROOT node is required")
    elif root_nodes[0].get("mesh") is not None:
        issues.append("ASSET_ROOT must not render a mesh")

    anchors = {
        str(node.get("name")): node
        for node in nodes
        if (node.get("extras") or {}).get("component_type") == "semantic_anchor"
    }
    for anchor_name, anchor in anchors.items():
        if anchor.get("mesh") is not None:
            issues.append(f"semantic anchor renders geometry: {anchor_name}")
        translation = anchor.get("translation")
        if not isinstance(translation, list) or len(translation) != 3:
            issues.append(f"semantic anchor missing translation: {anchor_name}")

    port_count = 0
    for node in nodes:
        extras = node.get("extras") or {}
        if extras.get("component_type") != "port_cage":
            continue
        port_count += 1
        name = str(node.get("name") or "")
        if not re.search(r"PORT_(?:GE|SFP|MGMT)_\d{3}$", name):
            issues.append(f"invalid normalized port name: {name}")
        anchor_name = str(extras.get("connection_anchor") or "")
        if anchor_name not in anchors:
            issues.append(f"port has no semantic anchor: {name}")
        if extras.get("connection_face") != "front":
            issues.append(f"port is not marked front: {name}")

    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            attributes = primitive.get("attributes") or {}
            if "POSITION" not in attributes:
                issues.append(f"mesh {mesh.get('name')} has no POSITION")
            if "NORMAL" not in attributes:
                issues.append(f"mesh {mesh.get('name')} has no NORMAL")
            if "TEXCOORD_0" not in attributes:
                issues.append(f"mesh {mesh.get('name')} has no TEXCOORD_0")

    if len(document.get("meshes", [])) and port_count == 0 and "linecard" in str(asset_extras.get("asset_key") or ""):
        issues.append("linecard demo must contain at least one port cage")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args()
    directory = options.directory.resolve()
    files = sorted(directory.glob("*.glb"))
    if not files:
        print(f"No GLB files found in {directory}")
        return 2
    failures = 0
    for path in files:
        issues = validate(path)
        if issues:
            failures += 1
            for issue in issues:
                print(f"ERROR {path.name}: {issue}")
        else:
            print(f"PASS {path.name}")
    print(f"Validated {len(files)} GLBs; failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
