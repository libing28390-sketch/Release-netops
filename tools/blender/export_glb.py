"""Validate the active Blender scene and export a single GLB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_scene import validate_scene


def blender_args() -> list[str]:
    args = sys.argv
    return args[args.index("--") + 1 :] if "--" in args else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--height-u", type=int, default=None)
    options = parser.parse_args(argv if argv is not None else blender_args())
    issues = validate_scene(options.height_u)
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}")
        return 1
    import bpy  # type: ignore
    options.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(options.output.resolve()),
        export_format="GLB",
        use_selection=False,
        export_apply=True,
        # Keep the RackVision Blender contract (X=left/right, Y=front/back,
        # Z=vertical).  RackDeviceItem performs the single runtime conversion
        # to the viewer's axes, so the exporter must not add another one.
        export_yup=False,
        export_extras=True,
        export_cameras=False,
        export_lights=False,
    )
    if not options.output.is_file() or options.output.stat().st_size == 0:
        print("ERROR: Blender did not produce a non-empty GLB")
        return 1
    print(f"Exported {options.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
