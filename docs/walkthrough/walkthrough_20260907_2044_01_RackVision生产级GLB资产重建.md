# RackVision 生产级 GLB 资产重建执行记录

## 完成摘要

本轮完成了 RackVision 8 个实时展示基线 GLB 的重建、离线校验、生产静态目录导入和浏览器 3D 冒烟验证。资产不再只是简单盒体：生成器增加了倒角机箱、前后面板、安装耳/孔位、端口笼与插槽、触点、LED、PSU、风扇、散热和可供运行时使用的端口连接锚点。

四个通用交换机资产已登记为 `approved/glb`，会被 Resolver 选为生产静态 GLB；`zte_zxr10_9904_s` 保持 `draft`，只作为有尺寸输入的展示基线，不宣称 OEM 精确还原。

后续增量修复已将 H3C S6800 的正反面按两张参考图拆开建模，并修复 3D 文字朝向；当前页面在没有已验证拓扑时显示明确标识的视觉预览线缆，不写入 CMDB。

## 输入与坐标契约

- 输入目录清单：`D:\data\downloads\Nexora_3D_Asset_Base_Catalog_v1.xlsx`，只读使用，未修改原始 Excel。
- Blender：`D:\blender\blender.exe`，版本 5.2.1 LTS。
- 设备坐标：`X=左右`、`Y=前后`、`Z=垂直`；`+Y=front`；1 Blender unit = 1 m。
- 前端既有 `RackDeviceItem` 的坐标/旋转契约保持不变，GLB 导出关闭 Y-up 转换以避免运行时重复旋转。

## 生成的资产

| asset key | 类型 | public 文件 | registry 状态 |
| --- | --- | --- | --- |
| `generic_switch_1u_24p` | 1U 24 口铜口交换机 | `public/assets/3d/generic_switch_1u_24p.glb` | `approved / glb` |
| `generic_switch_1u_48p` | 1U 48 口铜口交换机 | `public/assets/3d/generic_switch_1u_48p.glb` | `approved / glb` |
| `generic_switch_1u_sfp` | 1U 24 口 SFP/SFP+ 交换机 | `public/assets/3d/generic_switch_1u_sfp.glb` | `approved / glb` |
| `generic_switch_dc_1u` | 1U 高速 DC 交换机 | `public/assets/3d/generic_switch_dc_1u.glb` | `approved / glb` |
| `zte_zxr10_9904_s` | 8U 模块化交换机展示基线 | `public/assets/3d/zte_zxr10_9904_s.glb` | `draft / procedural_until_glb_approved` |
| `h3c_s6800_family` | 1U S6800 双面设备基线 | `public/assets/3d/h3c_s6800_family.glb` | `approved / glb` |
| `rack_42u_600x1000` | 42U 机柜 | `public/assets/3d/rack_42u_600x1000.glb` | `approved / glb` |
| `generic_patch_panel_cat6_24p` | 1U CAT6 24 口配线架 | `public/assets/3d/generic_patch_panel_cat6_24p.glb` | `approved / glb` |

每个资产同时保留：

- `assets/source/blender/<asset_key>.blend`
- `assets/build/glb/<asset_key>.glb`
- `assets/build/specs/<asset_key>.json`
- registry 中的尺寸、版本、来源和发布路径

## 关键实现

- 新增 `tools/blender/rackvision_blender_production.py`，集中处理生产基线材质、几何、端口语义、前后部件和模块化 8U 模板。
- `generate_device.py`、`validate_scene.py`、`batch_build.py` 已切换到新的生产生成器。
- 每个端口保留 `asset_key`、`port_index`、`port_media_type`、`connection_face`、`connection_anchor` 等自定义属性；端口组件不会覆盖成错误的通用 `port` 类型。
- `export_glb.py` 明确使用 GLB、保留 extras、关闭相机/灯光导出和 Y-up 转换，供现有 React Three Fiber 运行时直接使用。
- `batch_build.py` 会保留已审核的 spec 覆盖字段，避免批量构建时用 registry 基线覆盖端口布局和标签。
- S6800 专用 profile 使用三组 16 口 SFP+、两组 3 口 QSFP28 的正面布局，以及管理/服务口、5 风扇、2 电源的背面布局；不再将参考图解释为防火墙。
- 文本标签在生成阶段完成面向正面的朝向校正并应用变换，避免 glTF 查看器中的镜像/倒置；配线架补充端口导轨、底部理线条、线缆夹和接地柱。
- `RackCableLayer` 仅以拓扑接口数据绘制真实线缆；当当前机柜没有已验证链路时生成带 `is_preview` 标识的视觉预览，页面明确提示“不写入 CMDB”，并提供关闭/恢复控制。

## 构建与验证

执行入口：

```powershell
& 'D:\blender\blender.exe' --background --python 'tools\blender\batch_build.py' -- `
  --asset-key zte_zxr10_9904_s `
  --asset-key h3c_s6800_family `
  --asset-key rack_42u_600x1000 `
  --asset-key generic_patch_panel_cat6_24p `
  --asset-key generic_switch_1u_24p `
  --asset-key generic_switch_1u_48p `
  --asset-key generic_switch_1u_sfp `
  --asset-key generic_switch_dc_1u `
  --output-root 'assets' `
  --publish-root 'public/assets/3d' `
  --blender 'D:\blender\blender.exe'
```

已通过的检查：

- Blender headless 生成和 `validate_scene.py` 场景校验：8/8（ZTE 9904-S 按 8U 校验）。
- GLB glTF 2.0 头、JSON chunk、二进制 chunk 长度、节点、材质、端口笼和连接锚点解析：8/8。
- `assets/build/glb` 与 `public/assets/3d` 文件 SHA-256 一致：8/8。
- Python `py_compile`：通过。
- `git diff --check`：通过；仅有工作区换行符提示，无 whitespace error。

当前 public GLB 大小：约 1.9–15.1 MB；S6800 因双面端口、风扇和电源细节最大，为实时展示细节与下载体积之间的当前基线。

## 浏览器验证

在已运行的本地实例中刷新并打开：`http://192.168.56.1:5400/cmdb/racks`。

验证路径：

1. 选择机柜 `JG-02`。
2. 点击 `3D 孪生`，确认只读 3D 场景和 9 台设备列表出现。
3. 依次点击 `正面`、`背面`、`45°`，确认机柜、设备、导轨和场景仍正常渲染。
4. 在正面近景检查 S6800 的 `H3C/S6800`、分组标题、端口编号、slot 和状态灯方向；检查底部状态显示 `预览线缆 · 未关联`。
5. 打开“更多图层”，点击“关”确认线缆消失，再点击“全线”确认预览恢复；检查浏览器控制台没有 GLTF/GLB 加载错误。

观察到的两个既有 warning 为 Recharts 容器尺寸 `-1/-1` 和 Three.js `THREE.Clock` 弃用提示，本轮未出现 GLB 解析错误。

## 结论与边界

- `public/assets/3d` 已作为本地仓库的生产静态资源目录完成导入，8 个 build/public 文件一致，浏览器本地运行实例已完成 S6800 正面近景、字体方向、预览线缆和开关冒烟。
- 这批 Generic 文件是可直接用于实时 viewer 的生产基线，不是厂商 SKU 的工业设计/CAD 复刻。
- ZTE 8U 文件继续保持 `draft`，在补齐官方正反面照片、端口布局或 CAD 前，不应在 registry 中改为 OEM 精确 `approved`。
- 尚未执行目标服务器上的 Nginx/Docker 部署，因此 MIME、缓存头、压缩、404、线上性能和回滚仍属于发布前门禁。
- `handoff.md`、`.codex/`、`.agents/` 仍是内部协作资料，本轮没有复制到公开发布树。

## 增量修复：S6800 字体方向与线缆显示

- 两张用户参考图均归入 `h3c_s6800_family`：图 2 是三组 SFP+ 与两组 QSFP28 正面，图 1 是管理/服务口、五风扇和双电源背面。
- 通过文本局部反射、导出前应用变换修复镜像/倒置；浏览器近景确认标签可读。
- 当前机柜没有已验证链路（数据库 `topology_links` 为 0），所以显示的是带颜色和明确状态标识的视觉预览线缆；真实链路仍只由拓扑数据驱动。
- `更多图层 → 关/全线` 已在浏览器中实测可隐藏/恢复线缆；没有向 CMDB 写入任何模拟连接。
- U 标尺已提升为关闭深度遮挡的最外层叠加，右侧标尺移除水平镜像；放大浏览器画面中左右数字均为正常阅读方向。
- 机柜后板改为周边框架式开口，避免在背面视角遮住 S6800 的 5 个风扇、2 个电源和管理/服务口。

## 增量修复：近远景可见性与状态灯动画

### 完成摘要

- 将 `更多图层` 面板移到 3D 视口右侧，并在面板打开时让出对应场景宽度；近景时菜单不再覆盖设备，远景时整柜仍保持可见。
- 将 `.codex-tmp` 加入 Vite watch ignore，修复内部临时 GLB 被 Windows 文件监视器占用后导致本地前端服务退出的问题；服务已重启并恢复在 `5400` 端口。
- 为 GLB 运行时加入实例级状态灯动画：状态/电源指示灯做明显呼吸脉冲，端口灯做较平稳的活动脉冲；灯材质关闭 tone mapping 并对灯体做轻微可见性增强，兼顾远景亮点和近景细节。
- 动画仅发生在浏览器内存中的 GLB clone，不会回写 GLB、CMDB 或拓扑数据。

### 实际修改文件

- `src/pages/RackManagement/Rack3D/RackDeviceItem.tsx`
- `src/pages/RackManagement/Rack3D/index.tsx`
- `handoff.md`

### 浏览器复核

- 已恢复本地前端服务并重新进入 `3D 孪生`。
- `正面` 远景确认整柜、U 标尺和设备层级可见。
- `聚焦底部` 近景确认 S6800 的端口、标签、线缆预览和绿色状态灯可见；打开“更多图层”后面板位于右侧，设备区域没有被菜单盖住。
- 连续截图帧检查页面保持响应，GLB 无加载错误；灯光变化由 `useFrame` 按帧更新实例材质。

### 新增验证结果

- `npm run test:frontend -- src/pages/RackManagement/Rack3D/index.test.tsx src/pages/RackManagement/Rack3D/topology.test.ts`：2 个文件、9 个测试通过。
- `git diff --check -- src/pages/RackManagement/Rack3D/RackDeviceItem.tsx src/pages/RackManagement/Rack3D/index.tsx`：无 whitespace error；仅有工作区换行符提示。
- 针对本轮 3D 文件的 TypeScript 检查此前通过；最终全量 `npm run lint` 被工作区既有的 `src/components/BatchPlatformBindingModal.tsx:136` 类型比较错误阻断，与本轮 3D 改动无关，未擅自改动该用户文件。
- 未执行生产构建、提交、推送或 Docker/Nginx 发布；服务仍为本地验证实例。
