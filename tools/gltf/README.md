# GLB normalization tools

`normalize_modular_demo.py` converts the external modular-switch proof of
concept into a Nexora-compatible draft set without touching the source ZIP.

```powershell
.\.venv\Scripts\python.exe tools\gltf\normalize_modular_demo.py `
  --input-dir 'C:\path\to\nexora_modular_switch_glb_demo' `
  --output-dir assets\build\glb\modular_demo `
  --publish-dir public\assets\3d\modular_demo

.\.venv\Scripts\python.exe tools\gltf\validate_modular_demo.py `
  assets\build\glb\modular_demo
```

The normalizer swaps the source `Y=up/Z=front` axes to the RackVision
`Y=front/Z=up` contract, moves each asset to a bottom/front origin, reverses
triangle winding, generates normals and UVs, adds named PBR material slots,
and adds node-level semantic metadata plus invisible port/slot anchors.

The output remains `draft`: dimensions and visual fidelity still need review
against an official product datasheet or front/rear reference photographs
before adding an entry to the approved asset registry.
