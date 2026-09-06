"""Generate one RackVision family/generic device in a Blender scene."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rackvision_blender_common import create_device, reset_scene


def blender_args() -> list[str]:
    args = sys.argv
    return args[args.index("--") + 1 :] if "--" in args else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--blend-output", required=True, type=Path)
    options = parser.parse_args(argv if argv is not None else blender_args())
    spec = json.loads(options.input.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise SystemExit("Device input must be a JSON object")
    reset_scene()
    create_device(spec)
    options.blend_output.parent.mkdir(parents=True, exist_ok=True)
    import bpy  # type: ignore
    bpy.ops.wm.save_as_mainfile(filepath=str(options.blend_output.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

