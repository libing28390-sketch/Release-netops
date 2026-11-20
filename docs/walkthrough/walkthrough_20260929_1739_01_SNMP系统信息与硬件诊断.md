# SNMP 系统信息与硬件指标诊断

## 完成摘要

SNMP 诊断页新增两个独立入口：系统信息读取设备名称、厂商、软件平台、型号与版本；硬件指标复用当前 LibreNMS/标准 MIB 硬件发现链路，展示采集类别状态与传感器读数。资产回退字段有来源标记。接口对托管设备执行只读探测，不写回资产。

旧 SNMP WALK、IF-MIB 与 LLDP 查询流程未改动；新诊断页签通过功能开关接入已有诊断组件。

## 关键实现

- 后端新增系统信息和硬件发现诊断 API。两者要求 Operator、校验当前用户可见的唯一托管设备，从服务端解析 SNMP 凭据，不将 community 返回给前端。
- 硬件结果保留 LibreNMS 规则/来源、硬件类别状态和原因；传感器响应最多 200 条并返回总数与截断标记。
- 系统字段分开返回实时识别与资产回退来源；SNMP 四个标准系统 OID 并行读取，空响应会返回超时错误。
- 新页面状态支持请求取消、切换设备后清空旧结果、独立错误提示；失败时不再同时显示初始空态。
- 修复 LibreNMS 符号 MIB OID 查找的 PostgreSQL 事务隔离，避免一个可选规则查询失败影响随后的平台资料读取。
- 看板契约测试改为验证当前 `asset_id` 设备范围及实际接口状态表；修正 PEN 24681 用例的预期证据来源。

## 实际修改文件

- `backend/api/devices.py`（本次提交仅含两个诊断 API 路由）
- `backend/services/librenms_rule_service.py`
- `backend/services/snmp_discovery_service.py`
- `backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`
- `backend/tests/platform_registry/test_platform_identification.py`
- `backend/tests/snmp/test_snmp_walk_api.py`
- `src/components/SnmpMib/components/LiveWalkInspector.tsx`
- `src/pages/SnmpWalkPage.tsx`
- `docs/plans/plan_20260929_1739_01_SNMP系统信息与硬件诊断.md`
- `docs/fixes/fix_20260929_1758_01_SNMP诊断与Actions失败.md`

## 验证结果

- `npm run lint`：通过，TypeScript 无错误。
- `node node_modules/vite/bin/vite.js build --outDir node_modules/.cache/codex-build-snmp-diagnostics-final-20260929`：生产构建通过，4320 个模块完成构建。
- `.venv/Scripts/python.exe -m pytest backend/tests/snmp/test_snmp_walk_api.py`：16 passed。
- `.venv/Scripts/python.exe -m pytest backend/tests/monitoring/test_domestic_and_wireless_monitoring.py::test_dashboards_suite_completeness backend/tests/monitoring/test_domestic_and_wireless_monitoring.py::test_dashboard_device_variables_use_current_up_targets backend/tests/platform_registry/test_platform_identification.py::test_platform_detection_probes_live_snmp_before_cli_when_version_is_not_cached backend/tests/platform_registry/test_platform_identification.py::test_live_snmp_vendor_identity_suggests_dptech_and_hillstone_without_mutating_asset`：6 passed，覆盖上次 Actions 的 4 个失败节点及 3 个厂商来源参数。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 violations。
- `git diff --check`：通过。

## 未执行验证与剩余风险

- 未连接真实设备验证 SNMP 响应；实际指标仍取决于设备可达性、权限与 LibreNMS/标准 MIB 支持范围。
- 未在运行中的 Grafana 实例验证渲染。
- 未重跑完整后端套件；已重跑上次 Actions 的具体失败节点和 SNMP 诊断 API 测试。
- `TestClient` 输出一条现有 Starlette/httpx 弃用提示；不影响 16 项测试通过。

## 回滚

撤销本次提交可移除新增诊断 API、界面入口、事务恢复及对应测试修改；不会触碰真实设备配置或资产记录。
