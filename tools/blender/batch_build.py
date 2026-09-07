"""Build explicitly selected registry assets headlessly.

Only entries selected by ``--asset-key`` or marked ``build=true`` in the input
manifest are built. This prevents an accidental command from turning all 120
exact catalogue rows into independent GLBs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def blender_args() -> list[str]:
    args = sys.argv
    return args[args.index("--") + 1 :] if "--" in args else args[1:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path("assets/catalog/asset_registry.json"))
    parser.add_argument("--asset-key", action="append", default=[])
    parser.add_argument("--output-root", type=Path, default=Path("assets"))
    parser.add_argument("--publish-root", type=Path, default=Path("public/assets/3d"))
    parser.add_argument("--blender", default="blender")
    options = parser.parse_args(argv if argv is not None else blender_args())
    registry = json.loads(options.registry.read_text(encoding="utf-8"))
    requested = set(options.asset_key)
    selected = [item for item in registry if not requested or item.get("asset_key") in requested]
    if not requested:
        selected = [item for item in selected if item.get("build") is True]
    if not selected:
        print("No explicitly selected/build=true assets; refusing mass build")
        return 2

    script_dir = Path(__file__).resolve().parent
    for entry in selected:
        key = str(entry["asset_key"])
        input_path = options.output_root / "build" / "specs" / f"{key}.json"
        blend_output = options.output_root / "source" / "blender" / f"{key}.blend"
        glb_output = options.output_root / "build" / "glb" / f"{key}.glb"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep reviewed build overrides (port groups, product profile, labels,
        # power layout, etc.) when a spec already exists.  Registry metadata
        # remains the baseline and still fills any missing fields.
        reviewed_spec = {}
        if input_path.is_file():
            try:
                candidate = json.loads(input_path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    reviewed_spec = candidate
            except (OSError, json.JSONDecodeError):
                reviewed_spec = {}
        build_spec = dict(entry)
        build_spec.update(reviewed_spec)
        input_path.write_text(json.dumps(build_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        generate = [
            options.blender, "--background", "--python", str(script_dir / "generate_device.py"),
            "--", "--input", str(input_path), "--blend-output", str(blend_output),
        ]
        export = [
            options.blender, "--background", str(blend_output), "--python", str(script_dir / "export_glb.py"),
            "--", "--output", str(glb_output), "--height-u", str(entry.get("height_u") or 1),
        ]
        subprocess.run(generate, check=True)
        subprocess.run(export, check=True)
        if not glb_output.is_file() or glb_output.stat().st_size == 0:
            raise SystemExit(f"GLB output missing after build: {glb_output}")
        publish_path = options.publish_root / f"{key}.glb"
        publish_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(glb_output, publish_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
