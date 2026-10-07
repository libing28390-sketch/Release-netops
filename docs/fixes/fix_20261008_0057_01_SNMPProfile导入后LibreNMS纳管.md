# SNMP Profile 导入后 LibreNMS 纳管

## 问题现象

资产导入记录了管理 IP 与 `snmp_credential_id`，但设备没有因此进入 LibreNMS。凭据此前只参与 Nexora 自身的 SNMP 主机名读取，LibreNMS 不会自动获得该设备专用的 Profile，后续原生 OS 识别、Discovery、Poller 与硬件采集也就无法沿着预期链路工作。资产的 Profile 关联校验还只接受 SNMPv2。

## 根因

CMDB 导入流程原先没有调用 LibreNMS 官方添加设备 API，也没有把已保存的 v2/v3 Profile 映射到 LibreNMS 设备配置。Nexora 本地 binding 只能依赖已有的 LibreNMS 设备关联，无法在导入后自动创建并精确关联设备。

## 解决方案

- 将 LibreNMS 纳管作为资产事务提交后的独立步骤，逐个网络设备读取已保存的管理 IP 和凭据 ID；外部 API 失败仅记录逐行状态，不回滚已提交的 CMDB 资产。
- 对唯一精确 IP 命中的现有设备，更新 LibreNMS 原生 SNMP 配置；未命中时，通过官方 Add Device API 使用该资产 Profile 添加设备。只有精确核对原生设备 ID 与管理 IP 后才创建 Nexora binding。
- 支持经过校验的 SNMPv2c/v3 Profile，不回退到缺失或无法解密的旧凭据；导入响应按行给出纳管状态。
- 诊断与 Grafana 硬件展示读取 LibreNMS 原生结果；资产未绑定等状态能够显示给操作者。同步投影等待不再遮挡 LibreNMS 已保存的原生结果。
- cAdvisor 禁用未使用且触发 smaps 读取告警的 `referenced_memory` 指标。

## 实际修改文件

- `backend/api/assets.py`
- `backend/services/librenms_runtime_client.py`
- `backend/services/librenms_binding_service.py`
- `backend/services/librenms_enrollment_service.py`
- `backend/services/librenms_diagnostic_service.py`
- `backend/tests/configuration/test_asset_import_template.py`
- `backend/tests/configuration/test_asset_management_method_import.py`
- `backend/tests/monitoring/test_grafana_queries.py`
- `backend/tests/monitoring/test_librenms_diagnostic_service.py`
- `backend/tests/monitoring/test_librenms_runtime_client.py`
- `backend/tests/monitoring/test_librenms_binding_service.py`
- `backend/tests/monitoring/test_librenms_enrollment_service.py`
- `backend/tests/monitoring/test_monitoring_v1_deployment_contract.py`
- `src/components/SnmpMib/components/HardwareDiagnosticSummary.tsx`
- `src/components/SnmpMib/components/hardwareDiagnosticTypes.ts`
- `src/components/SnmpMib/components/hardwareDiagnosticUtils.ts`
- `src/pages/AssetManagement/components/AssetModal.tsx`
- `src/pages/AssetManagement/constants.ts`
- `src/pages/AssetManagement/constants.test.ts`
- `src/pages/AssetManagement/index.tsx`
- `docker-compose.yml`
- `monitoring/grafana/generate_dashboards.py`
- `monitoring/grafana/dashboards/nexora-network-overview.json`
- `public/templates/asset_import_template.xlsx`

## 验证命令与结果

- LibreNMS 客户端与纳管服务专项 pytest：55 passed。
- 资产导入、诊断、Grafana 查询和部署契约专项 pytest：99 passed。
- `npm run test:frontend`：124 个测试文件、476 项测试通过。
- `npm run lint`：通过。
- `npm run build`：通过。
- `python scripts/validate_postgresql_only.py`：0 项违规。
- Compose YAML 解析、修改模块 `compileall`、`git diff --check`：通过。
- 完整后端 pytest：3453 passed、0 failed、1 skipped，另有 26 项子测试通过，耗时 5239.83 秒。

## 未验证项

未连接真实 LibreNMS 实例或 HCL/生产设备执行运行时 API 验证。代码测试不会证明远端 Token 权限、设备 SNMP 可达性或厂商实际提供 CPU/内存传感器。

全量后端唯一跳过项为 `backend/tests/ip_locator/test_topology_lldp_snapshot_service.py:246`；该测试要求对配置 Redis 中的短期密钥进行明确授权，与本次 SNMP/LibreNMS 变更无关。

## 风险与回滚方式

导入后的 LibreNMS 调用依赖已启用且健康的实例、有效 API Token 和设备级 Add/Update 权限。外部调用失败时 CMDB 资产保留，并在行级结果中给出原因；超时后需先让 LibreNMS Discovery 完成再安全重试。若需要回滚，可回滚本记录列出的代码、前端、Compose、模板和看板改动；已在 LibreNMS 创建的设备及已提交的资产不会自动删除，应分别在各自系统中按运维流程处理。
