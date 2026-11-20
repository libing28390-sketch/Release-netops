# RackVision Blender 工作流

Blender 脚本位于 `tools/blender/`，生产 FastAPI 进程不需要安装 Blender。

## 单资产流程

```bash
blender --background --python tools/blender/generate_device.py -- \
  --input assets/build/specs/generic_switch_1u_24p.json \
  --blend-output assets/source/blender/generic_switch_1u_24p.blend

blender --background assets/source/blender/generic_switch_1u_24p.blend \
  --python tools/blender/export_glb.py -- \
  --output assets/build/glb/generic_switch_1u_24p.glb --height-u 1
```

## 批量流程

`batch_build.py` 只构建显式传入的 `--asset-key`，或者 registry 中明确设置 `build=true` 的条目；空选择会拒绝执行。这是为了防止把 120 个 exact SKU 意外生成 120 个独立 GLB。

## 验证

`validate_scene.py` 检查 Metric 单位、基础对象名、正尺寸、应用后的 transforms、设备高度和 `+Y` 前方向。`export_glb.py` 在校验失败时以非零码退出。缩略图由 `render_thumbnail.py` 生成到 `assets/thumbnails`。

## 人工审核门

1. 用官方资料核对尺寸、端口、PSU、风扇和前后方向。
2. 在 Blender 中检查 LOD、三角面数、材质和 origin。
3. 导出 GLB 并执行 validator。
4. 导入浏览器测试；通过后把 registry 状态从 `draft` 改为 `review`，由审核人确认后才可 `approved`。

## 外部模块化 Demo 归一化

没有 `.blend` 源文件的外部 GLB 只能先作为 draft hand-off。使用
`tools/gltf/normalize_modular_demo.py` 生成隔离的
`assets/build/glb/modular_demo` 与 `public/assets/3d/modular_demo`，再用
`tools/gltf/validate_modular_demo.py` 检查坐标、origin、法线、UV、材质和语义锚点。
该流程不会覆盖现有生产 GLB，也不会自动把 Demo 注册为 approved；通过官方尺寸/端口
资料和浏览器人工验收后，才可以建立正式的 `.blend` 源资产并进入 registry。
