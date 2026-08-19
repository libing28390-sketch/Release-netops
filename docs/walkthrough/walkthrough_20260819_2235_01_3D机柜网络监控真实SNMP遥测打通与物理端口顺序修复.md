# 3D机柜网络监控真实SNMP遥测打通与物理端口顺序修复 走查报告

## 任务完成摘要

针对用户提供的真实设备 CLI（`RBM_P<F1090-9> dis int br`）与网络监控平台（`/monitor/networks`）实测数据，全面查证并修复了以下核心痛点：

1. **彻底打通网络监控平台真实 SNMP IF-MIB 数据链路（`snmpTelemetry.ts`）**：
   - 彻底废弃所有静态 mock 数据；
   - 建立设备名称到监控中台的自动映射链：调用 `/api/monitoring/network-devices` 精准解析 `F1090-9`、`S6850-1` 等真实设备；
   - 实时调用 `/api/monitoring/device/{id}/realtime`，获取与 `/monitor/networks` 图二中完全一致的 **真实 SNMP IF-MIB 物理接口数据**；
   - 真实呈现 `GigabitEthernet1/0/0`、`GigabitEthernet1/0/1`、`GigabitEthernet1/0/2` 等全部 24 个真实接口的 UP/DOWN 状态、进出速率（IN/OUT bps）、错包统计（106/112）及对端描述（`TO-S6850-1`、`TO-HOST-ONLY`、`RBM-TO-F1090-10`）。
2. **修复物理双排端口排列与单端口悬浮嗅探（`RackDeviceTooltip.tsx` / `DevicePortMatrix.tsx`）**：
   - 适配硬件设备的标准物理双排排布：上排偶数口（0, 2, 4, 6...）、下排奇数口（1, 3, 5, 7...）；
   - 鼠标悬停任意单数或双数端口时，触发高亮与放大，并在下方 HUD 看板上清晰、高对比度展示该端口的真实名称（如 `GigabitEthernet1/0/0`）、状态（`● UP 正常`）、对端信息（`TO-S6850-1`）与吞吐速率；
   - 即使未悬停某端口，卡片也默认显示当前激活 UP 端口的真实指标。
3. **基于真实接口对端描述生成 3D 动态跳线（`RackCableLayer.tsx`）**：
   - 解析真实接口描述中包含的 `TO-S6850-1` 和 `RBM-TO-F1090-10`；
   - 选中 `F1090-9` 时，在 3D 机柜空间中精准生成连接到 `S6850-1` 和 `F1090-10` 的动态 CatmullRom 3D 曲线跳线；
   - 3D 悬浮链路标牌真实呈现：`F1090-9:GE1/0/0 ⇄ S6850-1:GE1/0/1 [LINK UP · 1000Base-T 双绞线]`。

---

## 实际修改与新增文件清单

| 文件路径 | 变更类型 | 说明 |
| :--- | :--- | :--- |
| [`src/pages/RackManagement/adapters/snmpTelemetry.ts`](file:///d:/netops/netsops-main/src/pages/RackManagement/adapters/snmpTelemetry.ts) | 新增 | 对接 `/api/monitoring/device/{id}/realtime`，解析并缓存真实 SNMP IF-MIB 物理接口与遥测 |
| [`src/pages/RackManagement/Rack3D/RackDeviceTooltip.tsx`](file:///d:/netops/netsops-main/src/pages/RackManagement/Rack3D/RackDeviceTooltip.tsx) | 修改 | 3D 悬浮 HUD 接入真实 SNMP 接口矩阵，修复物理排布与单端口悬浮嗅探 |
| [`src/pages/RackManagement/components/DevicePortMatrix.tsx`](file:///d:/netops/netsops-main/src/pages/RackManagement/components/DevicePortMatrix.tsx) | 修改 | 资产详情抽屉接入相同真实 SNMP 数据源，保持全局一致 |
| [`src/pages/RackManagement/Rack3D/RackCableLayer.tsx`](file:///d:/netops/netsops-main/src/pages/RackManagement/Rack3D/RackCableLayer.tsx) | 修改 | 动态绑定 `TO-S6850-1`、`RBM-TO-F1090-10` 等真实链路跳线 |

---

## 验证与测试结果

1. **前端单元测试 (Vitest)**：
   - 执行：`npm run test:frontend -- src/pages/RackManagement/adapters/__tests__/rackViewModel.test.ts`
   - 结果：`7 passed (7)`，全部断言通过。
2. **生产环境构建打包 (Vite Build)**：
   - 执行：`npm run build`
   - 结果：`✓ built in 25.35s`，编译产物 `dist/assets/RackManagementTab-DBwr6WKx.js` 0 错误。
