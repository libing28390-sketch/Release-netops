# RackVision QA 清单

## 数据和 API

- [x] 未登录访问 assets/health/topology/rack-assets 返回 401。
- [x] Viewer 不能执行安装、移动、删除和质量关闭（角色门禁与稳定错误响应已接入；重点路径由 focused suite 覆盖）。
- [x] 资产响应不含密码、SNMP community、Vault 路径（显式 DTO allowlist + set 标志）。
- [x] rack_devices 的标准安装、移动、卸载事务通过 PostgreSQL 测试。
- [x] 0U、侧挂、落地、unknown 不占用标准 U。
- [x] full-depth 占用前后两面并参与冲突检测。
- [x] quality issue upsert/list/resolve 可重复操作。
- [x] layout read model 同时提供 placements、occupancy、data_quality 和 revision meta。
- [x] 目录导入默认 dry-run，存在重复型号或人工尺寸冲突时整批阻断。
- [ ] 部署数据库执行 m0210 后完成真实历史回填审批。

## 前端

- [x] 2D/3D 共享 layout read model。
- [x] 2D 立面下方显示非标准位置/待确认设备，并可点击打开 Inspector。
- [x] 非 U 设备在列表、Inspector 和 3D 问题面板可见。
- [x] 3D 场景对非 U/invalid 设备显示可选中的待确认标记。
- [x] 非 U 设备不显示为 U1。
- [x] 未知高度以 bounded render placeholder 绘制，但通过 heightKnown/质量提示明确不代表 1U。
- [x] 设备健康未知不伪装为 healthy。
- [ ] 真实 GLB 加载、缓存和 LOD 在发布资产后验证。

## 资产和 Blender

- [x] Excel 原文件未修改，目录有源文件 SHA-256。
- [x] 120 exact SKU 映射到可复用 registry，而非 120 个独立 GLB。
- [x] 71 条缺失尺寸保留 pending_verification。
- [x] Blender 生成、验证、导出和缩略图脚本可 headless 调用。
- [x] 可选 GLB 单个加载失败时回退到程序化面板，不影响同柜其他设备。
- [ ] 在安装 Blender 的构建机实际生成并验收 M0 GLB。
- [ ] 每个 approved GLB 完成尺寸、方向、origin、材质、LOD 和导入验收。
