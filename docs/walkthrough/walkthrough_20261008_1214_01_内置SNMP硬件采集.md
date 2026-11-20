# 内置 SNMP 硬件采集完成记录

## 完成摘要

Nexora 现在可以独立承担硬件发现与周期采样：复用仓库内 LibreNMS 版本化 OS/OID 规则和归一化模型，但由 Nexora 后台读取现存设备 SNMP 凭据、执行 SNMP GET/WALK 并写入本地硬件库存。无已启用的外部 LibreNMS 实例时，导入和诊断会转为本地采集状态；Grafana 硬件指标及无线明细可以消费 `legacy_snmp` 样本。没有修改 Docker Compose，也没有在 Ubuntu 或真实设备上执行部署、配置变更或采集。

## 实际修改文件

- 后端采集与调度：`backend/services/snmp_hardware_probe_service.py`、`backend/services/snmp_hardware_normalization.py`、`backend/services/snmp_hardware_poller_service.py`、`backend/engine/orchestrator.py`、`backend/services/background_monitor_service.py`。
- 库存、诊断与导入：`backend/services/snmp_hardware_inventory_service.py`、`backend/services/librenms_diagnostic_service.py`、`backend/services/librenms_enrollment_service.py`、`backend/api/assets.py`、`backend/api/devices.py`。
- Grafana：`monitoring/grafana/generate_dashboards.py`、`monitoring/grafana/dashboards/nexora-network-wireless.json`。
- 前端：`src/components/SnmpMib/TemplateBindingModal.tsx`、`src/components/SnmpMib/SnmpTestResultModal.tsx`、`src/components/SnmpMib/components/HardwareDiagnosticSummary.tsx`、`src/components/SnmpMib/components/HardwareDiagnosticSummary.test.tsx`、`src/components/SnmpMib/components/LiveWalkInspector.tsx`、`src/components/SnmpMib/components/LiveWalkInspector.test.tsx`、`src/components/SnmpMib/components/hardwareDiagnosticTypes.ts`、`src/components/SnmpMib/components/hardwareDiagnosticUtils.ts`、`src/pages/AssetManagement/components/AssetModal.tsx`、`src/pages/AssetManagement/index.tsx`。
- 回归测试：`backend/tests/snmp/test_snmp_hardware_probe_service.py`、`backend/tests/snmp/test_snmp_hardware_inventory.py`、`backend/tests/monitoring/test_snmp_hardware_poller_service.py`、`backend/tests/monitoring/test_librenms_diagnostic_service.py`、`backend/tests/monitoring/test_librenms_enrollment_service.py`、`backend/tests/monitoring/test_grafana_metrics_export.py`、`backend/tests/monitoring/test_telemetry_orchestrator_execution.py`、`backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`。
- 计划和记录：`docs/plans/plan_20261008_1214_01_内置SNMP硬件采集.md`、`docs/walkthrough/walkthrough_20261008_1214_01_内置SNMP硬件采集.md`。

## 关键实现说明

- 后台新增每分钟扫描一次的硬件采集循环，并发限制为 4；单台设备发现按 24 小时、部分结果按 1 小时、失败按 15 分钟退避，样本周期为 5 分钟。初次 SNMP 身份探测失败也会写入失败能力记录，避免每分钟重复超时探测。
- 采集使用 Nexora 凭据中心提供的 SNMP community，规则从本地 bundle 读取，不请求 LibreNMS API。服务器资产被排除；硬件发现和普通连通性/接口轮询分开调度。
- H3C/Comware WX 控制器按厂商、型号和设备角色启用专用无线适配器。通用资产角色不会再提前屏蔽 WX 型号的无线采集；带 `H3C ` 前缀的型号也能识别，本轮添加了对应离线测试。
- 本地样本写入现有硬件库存并以 `legacy_snmp` 来源导出，继续兼容 `librenms_native`。无线面板现在同时允许两种来源并查询所有 `wireless_*` 组件类别，包括控制器、AP、Radio、BSS 和 SSID 数据；站点/厂商/角色/设备变量合并现有 AC 目标和本地无线硬件指标，通用 role 的本地 AC 有样本后可以选中。
- 诊断优先展示 Nexora 本地库存；尚未采集时检查本地 SNMP 凭据并显示待采集或未配置状态。资产导入没有外部实例时记录 `local_snmp`，不会把可选 LibreNMS 纳管失败当作导入失败。

## 验证命令与结果

- 聚焦后端套件：`59 passed in 140.07s`（覆盖规则探测、库存、调度、诊断、导入、指标出口和 orchestrator）。随后对失败退避、规则探测异常记录、H3C WX 控制器分流和无线 Grafana 查询契约追加验证：`4 passed, 26 deselected`；无线变量查询另测 `1 passed, 12 deselected`。
- 前端 Vitest：`HardwareDiagnosticSummary.test.tsx` 与 `LiveWalkInspector.test.tsx`，`2 files / 12 tests passed`。
- `npm run lint`：通过。
- 独立目录生产构建：`node node_modules/vite/bin/vite.js build --outDir .codex-build-validation-nexora-local-snmp-20261008`：通过；该次生成的专用构建目录随后清理。
- Dashboard 生成器 `build_wireless_dashboard()` 与 `validate_dashboard()`：通过并更新无线 Dashboard JSON。
- 对修改的 Python 服务与测试运行 `python -m py_compile`：通过。
- `python scripts/validate_postgresql_only.py`：0 项违规，通过。
- `git diff --check`：通过；Git 仅报告工作区 LF/CRLF 转换提示。

## 未执行验证及原因

- 未向目标 Ubuntu 主机部署或访问运行环境，未触发 SNMP GET/WALK，也未验证 AC_11 的真实 sysObjectID、已保存 profile、硬件 OID 响应和 Grafana 实时序列。用户没有要求本轮部署，因此结论限于代码与模拟测试。
- AC_11 截图显示 SNMPv2c；本轮后台采集沿用现有 vault 凭据契约，默认 v2c，未新增 SNMPv3。

## 剩余风险与后续建议

代码和离线测试证明采集器已接入 Nexora 自身的发现、采样、库存、诊断和 Grafana 路径；它们不能证明已运行的应用已经包含这些修改，也不能证明 AC_11 的 profile、规则匹配或具体 OID 在设备上有效。现有后台凭据契约尚未接入 SNMPv3 Profile；截图显示的 SNMPv2c 在本轮支持范围内。只有将 Nexora 应用部署到目标环境并观察首轮发现及后续样本后，才能确认现场数据是否出现；这不需要部署 LibreNMS 容器。
