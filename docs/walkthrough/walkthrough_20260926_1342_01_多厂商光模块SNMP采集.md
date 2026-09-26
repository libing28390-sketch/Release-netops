# 多厂商光模块 SNMP 采集与备份默认命令走查

## 完成摘要

光模块专用采集统一走 SNMP WALK，不再使用 CLI 或在 SNMP 不支持时回退 CLI。按已核实的 MIB/OID 接入 H3C、Huawei、Juniper、Ruijie、ZTE、Raisecom；Cisco、Arista、DPtech、Maipu、Fortinet 缺少本轮可确认的 DOM 单位、索引和端口关联定义，返回明确的不支持状态，不猜 OID。

`/config/backup` 的默认命令按厂商优先选择，资产目录共审计 41 家厂商，当前有 11 家经过核实的 vendor-first 默认命令；另外 30 家没有可安全复用的通用命令，保持 fail closed，除非其厂商和平台与已发布 `get_running_config` Profile action 一致。厂商默认命令不受旧设备平台/Profile 绑定值影响；Profile action 则校验厂商、平台和发布状态。未知显式厂商不能因为 `platform=cisco_ios` 被误列为候选。候选列表、定时任务和定时预览共用同一资格判断，并排除 server/host 资产。

Grafana 相关改动一并保留并验证：01 总览不再展示跨设备硬件平均使用率，改为覆盖情况和热点；稳定 Down 接口不再反复列入“未联通”异常；04 接口流量、07 Linux 图例布局和 09 接口详情 DOM 功率视图已更新，并修正涉及看板的设备筛选变量。

## 实际修改文件

- 后端光模块：`backend/services/snmp_optical_service.py`、`backend/services/operational_data_service.py`、`backend/services/platform_registry_service.py`、`backend/services/monitoring_oid_catalog.py`、`backend/services/snmp_md_preset_catalog.py`、`backend/database/migrations/m0254_append_optical_oid_metrics.py`。
- 后端备份命令：`backend/services/config_backup_command_service.py`、`backend/api/configs.py`。
- 自动化 SNMP 调用链：`backend/api/playbooks/builtin_scenarios.py`、`backend/api/playbooks/engine.py`、`src/hooks/useAutomation.ts`、`src/pages/AutomationExecute/index.tsx`。
- 备份前端：`src/utils/configBackupCommands.ts`、`src/utils/configBackupCommands.test.ts`、`src/hooks/useConfigSnapshots.ts`。
- Grafana：`monitoring/grafana/generate_dashboards.py`；`nexora-interface-detail.json`、`nexora-linux-metrics.json`、`nexora-network-device.json`、`nexora-network-interface.json`、`nexora-network-overview.json`。
- 回归覆盖：`backend/tests/configuration/test_startup_config_backup.py`、`backend/tests/monitoring/test_domestic_and_wireless_monitoring.py`、`backend/tests/monitoring/test_monitoring_v1_compiler.py`、`backend/tests/monitoring/test_optical_oid_catalog_migration.py`、`backend/tests/platform_registry/test_platform_registry_optical_action.py`、`backend/tests/snmp/test_operational_data_device_scope.py`、`backend/tests/snmp/test_operational_data_optical_snmp_path.py`、`backend/tests/snmp/test_optical_snmp_collector.py`、`backend/tests/snmp/test_snmp_mib_repository.py`、`backend/tests/security/test_api_access_boundary.py`、`backend/tests/test_automation_credentials_and_platforms.py`、`backend/tests/vendor_audit/test_h3c_cisco_quick_queries.py`。
- 计划与此前关联的 Grafana 计划/走查：`docs/plans/plan_20260926_1342_01_多厂商光模块SNMP采集.md`；`docs/plans/plan_20260926_1242_01_Linux服务器大盘图例布局.md`、`plan_20260926_1250_01_链路状态列表过滤长期Down.md`、`plan_20260926_1309_01_网络总览硬件指标覆盖与热点.md`、`plan_20260926_1315_01_设备与接口看板参考样式.md`；对应的 `docs/walkthrough/` 走查记录。

## 关键实现说明

- Optical service 按厂商 MIB 处理索引、单位和无效值；Huawei 的正值 µW / 负值百分 dBm 混合编码在采集时转换，Juniper 的零值和 Ruijie 的 `-10000` 无效哨兵会跳过。ZTE 根 OID 使用核实后的 MIB 路径。
- 自动化的 optical 类别在 CLI 命令解析和 SSH 凭据处理前走 SNMP；平台静态命令目录和历史发布档中的 transceiver CLI 命令都不会被返回或执行。接口详情统一 dBm 面板仅纳入 ifIndex/ifName 可关联且单位一致的厂商，避免把混合编码或复合索引伪装成同一单位。
- 备份命令由共享的前后端厂商目录解析。测试将 41 家目录厂商配合错误的 `cisco_ios` 平台值，确认 11 家命令映射按厂商执行，另 30 家不套用别家命令；未知显式 vendor 不会误套 Cisco 默认。Profile action 需要厂商/平台与绑定 Profile 一致，通用平台 action 执行和预览也会拒绝显式厂商不匹配。
- 备份候选列表、定时执行和定时预览采用相同资格条件；不支持厂商或 server/host 不会显示成“可备份”目标。
- 补充防护：设备 operational-data 的光模块 SNMP 调用按 tenant/site/device-group 范围授权；全局手动配置备份限制为 Administrator，Operator 不能在请求中选择 admin 凭据或借助 `auto` 回退到 admin 账号。
- Huawei 正值光功率按 µW 转 dBm（1000 µW = 0 dBm），以 entPhysicalName 将实体索引映射接口名并带回可用序列号；光模块 WALK 上限提高以覆盖大型接口表，所有指标 WALK 失败时报告采集失败。09 面板按 H3C、Ruijie、Juniper 过滤 exporter 哨兵样本。
- 只读项目诊断验证当前 H3C `S6850_1 / 10.254.0.1`：IF-MIB WALK 有 696 个接口；DOM 项与 ifIndex 可通过 ifName 映射；测得模块温度 35°C，并核实 H3C 收发功率 OID 和 raw hundredths-dBm 表示及 `2147483647` 无效值。没有运行 CLI，没有修改设备。

## 验证命令与结果

- 后端聚焦回归（SNMP、Operational Data、OID migration/compiler、MIB repository、H3C 查询、配置备份、DOM 与访问边界）：172 passed，144.46s。
- `npm run test:frontend -- --run src/utils/configBackupCommands.test.ts`：14 tests passed。
- `npm run lint`：通过；`npm run build`：通过。构建生成的 `dist/index.html` 已还原，不进入提交。
- `.venv/Scripts/python.exe scripts/validate_postgresql_only.py`：0 violation，PASS。
- Dashboard JSON 静态检查：9 份 JSON 全部有效，134 个面板 ID 在各自 dashboard 内唯一。
- `git diff --check`：通过。Git 对部分既有文本文件提示 LF/CRLF 转换警告，不是 whitespace 错误。

## 未执行验证及原因

- 其它五家已接入厂商没有可用现场设备/凭据，本地回归使用厂商 MIB 定义及模拟返回；没有尝试连接真实设备。
- 当前 Chrome 中的 Grafana 页面返回 `401 Authorization Required`，新版 JSON 也未同步到 Linux；因此不能在运行实例上验证新查询的实时数据和渲染。会完成 dashboard JSON、查询和变量契约的本地检查。用户已说明 Actions 通过后会自行更新服务器。
- GitHub CLI 未安装；代码推送后将通过仓库 Actions 状态接口检查工作流结果。

## 剩余风险与后续建议

- 设备固件、模块型号可能对可选 MIB 表的实现有差异；上线后先在实际设备的 09 详情核对 DOM 值和模块信息。未支持厂商保持不支持状态，取得可靠 LibreNMS/官方 MIB 证据后再单独接入。
- `/config/backup` 默认命令不是资产目录 41 家厂商全覆盖：11 家有已确认厂商默认命令，另外 30 家需已发布的 profile action 或进一步核实厂商和系统版本命令，避免把错误命令发到设备。
- 把代码同步到 Linux 并刷新 Grafana 后，复核 01/04/07/09 的查询结果、筛选器选项和光模块功率趋势。
- 推送后查看 GitHub Actions。用户自行执行 Linux 同步，本次不做生产部署或设备操作。
