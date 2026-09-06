"""Render a small deterministic RackVision asset thumbnail."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rackvision_blender_common import require_blender


def blender_args() -> list[str]:
    args = sys.argv
    return args[args.index("--") + 1 :] if "--" in args else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args(argv if argv is not None else blender_args())
    runtime = require_blender()
    scene = runtime.context.scene
    options.output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(options.output.resolve())
    scene.render.film_transparent = False
    runtime.ops.render.render(write_still=True)
    if not options.output.is_file() or options.output.stat().st_size == 0:
        print("ERROR: Blender did not produce a thumbnail")
        return 1
    print(f"Rendered {options.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

