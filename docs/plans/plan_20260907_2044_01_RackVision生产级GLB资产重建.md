# RackVision 生产级 GLB 资产重建计划

## 任务目标

将当前仅用于验证尺寸和导出链路的低多边形网络设备 GLB，重建为可直接用于 Nexora RackVision 生产展示的实时 3D 资产基线：保持机架坐标/单位契约，补齐真实设备常见的结构层级、端口语义、前后面板、安装耳、PSU/风扇、散热和 PBR 材质，并保留 Blender 源文件和可重复构建入口。

本次优先覆盖 Excel 中已有明确端口/尺寸输入且已生成的五个资产；不在没有官方尺寸、照片或 CAD 证据时冒充具体 OEM 型号，也不修改原始 Excel。

## 现状与问题

- 当前 `rackvision_blender_common.py` 主要由未倒角盒体组成，端口只是小方块，缺少真实插口层次和可视细节。
- 当前 GLB 已通过结构校验，但仍标记为 draft，不能作为生产资产批准。
- 生产运行时需要稳定的 `BODY`、前后面板、端口对象命名、尺寸、朝向和可解释元数据。

## 影响范围

- 离线 Blender 资产生成器和验证脚本。
- `assets/build/specs/` 下的资产规格、`assets/catalog/` registry，以及 `assets/source/blender/`、`assets/build/glb/`、`public/assets/3d/` 下的本地构建产物。
- RackVision 任务/交接/走查文档中的资产状态。
- 不修改后端接口、数据库、前端组件和原始 Excel；不执行 commit、push、部署或生产数据写入。`handoff.md` 只保留为内部交接材料，不复制到公开发布树。

## 拟修改文件

- `tools/blender/rackvision_blender_production.py`
- `tools/blender/validate_scene.py`
- `tools/blender/export_glb.py`（仅在需要明确导出选项时修改）
- `tools/blender/generate_device.py`、`tools/blender/batch_build.py`
- `assets/build/specs/*.json`（补充生产资产参数）
- `assets/catalog/asset_registry.json`、`assets/catalog/asset_registry.yaml`
- `assets/source/blender/*.blend`、`assets/build/glb/*.glb`、`public/assets/3d/*.glb`
- `docs/Nexora_RackVision_MASTER_TASKS.md`
- `docs/Nexora_RackVision_Backend_Data_API_TASKS.md`
- `handoff.md`
- 对应 `docs/walkthrough/walkthrough_20260907_2044_01_RackVision生产级GLB资产重建.md`

## 实施步骤

1. 读取 Excel、现有 registry、前端资产解析契约和当前 GLB 的命名/尺寸约束。
2. 重构 Blender 生成器：统一材质、倒角、面板层级、机架耳/安装孔、端口笼与插槽、LED、散热、后部 PSU/风扇和语义对象属性。
3. 为铜口、SFP/SFP+、QSFP/QSFP28、DC 高速交换机和 8U 模块化设备补充明确布局参数；保持所有尺寸来自 spec。
4. 用 Blender 5.2.1 headless 重新生成五个 BLEND、离线 GLB 和 `public/assets/3d` 生产静态资源，并让已具备通用规格证据的四个 Generic 条目切换为 `approved/glb`。
5. 运行场景校验、GLB 结构解析、尺寸/边界/端口语义检查，比较 build/public SHA-256，并抽取对象/材质统计。
6. 刷新实际 `/cmdb/racks` 浏览器页面，进入 3D 孪生，检查正面、背面和 45° 视角及控制台错误。
7. 只在自动校验通过后更新文档状态；仍缺官方外观证据的资产（当前 ZTE 8U 基线）保持 `draft`，不把“生产可用基线”误写成 OEM 精确模型。

## 验证计划

- Blender Python 脚本 `py_compile`。
- 每个资产执行 `validate_scene.py`，检查单位、必需节点、变换、尺寸、朝向、端口索引、安装边界和元数据。
- Python 标准库解析 GLB：glTF 2.0、JSON/二进制 chunk 长度、节点命名、材质和非空 buffer。
- 使用 Blender 重新打开导出的 BLEND，统计对象、面数、材质和语义端口，确认导出前后不丢节点。
- 浏览器打开 `http://192.168.56.1:5400/cmdb/racks`，确认 3D 孪生能够渲染生产目录资源，并在正面/背面/45° 视角下无 GLTF/GLB 错误。
- `git diff --check`；不运行与离线资产无关的全量业务回归。

## 风险与回滚思路

- 没有官方 CAD/完整产品照片时，无法证明 OEM 外观级精确；通过 registry 保持 draft 和来源/置信度字段，禁止静默批准。此次四个 Generic 是可用于实时展示的通用基线，不是具体厂商 SKU 的复刻。
- 细节过多可能增大 GLB，采用共享网格、实例化重复件和实时展示友好的面数上限；如浏览器性能不达标，可回退到已保留的旧 GLB，或调整 LOD 参数。
- 只覆盖本次明确选定的五个产物，不覆盖或删除其他用户资产；失败时保留旧 public 文件并报告失败资产。

## 2026-09-07 执行修订（以本节为准）

- 资产范围已扩展为 8 个：4 个 Generic 交换机、ZTE 9904-S、H3C S6800、42U 机柜和 CAT6 24 口配线架；全部已完成批量重导并同步到 `public/assets/3d`。
- 用户提供的两张 S6800 参考图约束同一设备的正反面：正面固定为 3×16 SFP+ 加 2×3 QSFP28，背面固定为管理/服务口、5 风扇和 2 电源；不得再按防火墙解释。
- 新增字体方向验收：标签必须在 glTF 浏览器正面近景可正常阅读，不能出现镜像、倒置或分组重叠；导出前应用所有文本变换。
- 新增线缆验收：真实线缆只来自 `topology_links`；当前无链路时显示 `is_preview` 视觉线缆并标注“未关联”，不写入 CMDB；“关/全线”控制必须可用。
- 前端影响范围已包含 `RackCableLayer`、`RackScene`、RackVision 页面和 GLB 加载路径；验收除 Blender/GLB 解析外，还需执行 `npm run lint`、RackVision topology 定向测试和已登录浏览器冒烟。
- 本轮已验证：S6800、配线架、机柜和 ZTE 8U 场景校验通过；8 个 build/public SHA-256 一致；前端 lint 与 3 个 topology tests 通过；浏览器正面近景可见正常字体和预览线缆，线缆开关可隐藏/恢复。
- 追加验收：正反面 U 标尺必须可见且不能镜像；机柜后板不得遮挡背面设备。当前已通过浏览器放大视图确认左右 U 数字方向正确，并通过背面视角确认 S6800 后部模块可见。

## 2026-09-07 增量计划：近远景可见性与状态灯动画

### 触发问题

- 近景打开“更多图层”时，面板压住设备区域，视觉信息过于拥挤。
- GLB 中的电源/状态灯和端口灯是静态发光材质，缺少运行时呼吸/活动反馈。
- 验收要求同时覆盖放大后的细节清晰度和远景的设备/灯光可见性。

### 修改边界

- `RackDeviceItem.tsx`：仅对 GLB clone 的 LED 材质做实例级动画，不写入 GLB、CMDB 或拓扑数据；为小尺寸灯体增加不改变外部尺寸契约的可见性增强。
- `Rack3D/index.tsx`：把图层控制移到视口右侧独立面板，面板打开时为 3D 场景预留宽度；保留现有只读、线缆预览和着色控制。
- `vite.config.ts`：忽略内部 `.codex-tmp` 临时目录，避免 Windows 文件监视器的 `EBUSY` 终止本地验证服务。
- `handoff.md` 与本 walkthrough：记录实际结果和未执行的生产发布门禁。

### 验证计划与结果

- RackVision 前端定向测试：`index.test.tsx` + `topology.test.ts`，已通过 2 个文件/9 个测试。
- 浏览器：已登录 `/cmdb/racks` 检查 3D 远景正面、底部近景、侧边图层面板和连续截图帧，未出现 GLB 加载错误。
- 差异检查：目标文件 `git diff --check` 已通过；未执行生产构建、提交、推送或部署。
- 本轮 3D 文件的 TypeScript 检查此前通过；最终全量 `npm run lint` 被工作区既有的 `src/components/BatchPlatformBindingModal.tsx:136` 类型比较错误阻断，与本轮 3D 改动无关，未擅自改动该用户文件。
