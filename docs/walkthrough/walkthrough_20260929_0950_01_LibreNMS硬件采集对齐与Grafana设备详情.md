# SNMP 硬件采集与 Grafana 设备详情实施记录

时间：2026-09-29，Asia/Shanghai。

对应计划：[LibreNMS 硬件采集对齐与 Grafana 设备详情整改计划](../../docs/plans/plan_20260929_0950_01_LibreNMS硬件采集对齐与Grafana设备详情.md)。

## 完成摘要

本轮适配范围按资产管理厂商目录校正：网络设备组 26 家、安全设备组 15 家，合计 41 个厂商选项。后端注册表与资产厂商/具体平台码同步，平台信息可以在没有单独 vendor 字段时推导资产厂商；不再只围绕 Cisco、Huawei、H3C、ZTE、Ruijie 几个例子规划。

已完成通用采集链路第一轮代码实施：保留结构化 LibreNMS OS 识别/硬件定义；把标准 MIB 与 LibreNMS 规则发现的部件合并为逐传感器清单；按记录的 OID、索引、换算计划进行后台轮询；将规范化值和质量暴露到独立 `/hardware-metrics` endpoint；Grafana 设备详情改为消费 `nexora_hw_*` 统一指标族。通用 HOST-RESOURCES/ENTITY-SENSOR 探测面向全部已识别资产，不会把“厂商被识别”自动等同于“该厂商私有硬件类别已适配”。

CPU 口径保留实际 `window`，并将窗口放入传感器稳定身份的 `series_variant`。同一设备同一 CPU 索引的 1m 与 5m 不会在合并或数据库 upsert 时覆盖。设备详情只选一台设备，并从这台设备真实存在的 `window` 值提供选择；KPI、走势、表格使用同一变量。1m、5m、unknown 不混合。跨设备比较需要按窗口分组。

跨厂商规则盘点发现：资产目录中的多个品牌都跨越不同 LibreNMS OS key；例如同厂商多个平台会使用不同规则，而 Edgecore OcNOS 的上游识别键是 IP Infusion `ocnos`。Junos、AOS、FortiGate、Ciena、Raisecom 等规则也使用此前未覆盖的通用过滤运算符。已补齐安全子集，并为尚未移植的 PHP OS class、设备条件、实体关联或转换函数保留明确的不支持状态。导入规则的覆盖与型号级适配状态分开报告。

厂商名单来源：[资产管理厂商常量](../../src/pages/AssetManagement/constants.ts)。26 家网络设备是本轮主范围；15 家安全设备保留单独统计。DPtech 等已有 Nexora OID catalog 的平台仍可走本地目录；没有上游专用规则或本地审核目录的平台只走标准 MIB fallback，不编造厂商私有 OID。

本轮对照资产管理 TypeScript 常量与后端 SNMP 注册表，网络厂商 26 项、安全厂商 15 项及全部具体 `VENDOR_PLATFORMS` 平台码逐项一致；这只是清单同步审阅，不代表硬件规则、真实设备或运行环境的验收。

既有工作记录中包含规则/探测和指标渲染的离线检查结果，但这些检查不能证明 26 家网络厂商或 15 家安全厂商的型号级适配完成。本次继续改动按用户要求不进行 Docker、真实设备、Grafana/VictoriaMetrics 验收；也不以验收结果作为本任务停止条件。

## 当前数据路径

```text
身份规则与标准 MIB
  → 每类硬件发现 + 完整索引
  → PostgreSQL snmp_hardware_sensors / snmp_hardware_capabilities
  → 后台按 OID 合并轮询并规范化，记录 raw/value/quality/last_success
  → FastAPI /hardware-metrics
  → vmagent platform_hardware_inventory (local collector)
  → VictoriaMetrics → Grafana nexora-network-device
```

接口监控仍走既有 SNMP Exporter 模块。硬件当前由后端轮询，不产生 snmp_exporter hardware module，也不依赖 vmalert。设备详情 `/monitor/grafana?asset_id=<ID>` 会默认打开硬件/设备详情；设备详情弹窗已加入该链接。

## 主要修改

- `backend/services/librenms_rule_service.py`：结构化识别条件和硬件定义解析，保留来源版本、索引、单位、换算、状态和诊断。
- `backend/services/snmp_hardware_probe_service.py`：标准 HOST-RESOURCES/ENTITY-SENSOR 探测、LibreNMS 规则发现、OID 分组轮询和规范化。
- `backend/services/snmp_hardware_inventory_service.py`、`backend/database/migrations/m0260_snmp_hardware_inventory.py`：发现运行、逐测量库存、能力状态、样本质量和 Prometheus exposition；窗口变体参与 CPU stable key。
- `backend/services/snmp_discovery_service.py`、`backend/services/background_monitor_service.py`：发现来源合并、同一持久化事务、周期轮询。
- `backend/api/grafana_metrics.py`：`/metrics` 保持聚合用途；逐设备硬件系列单独通过 `/hardware-metrics` 提供。
- `monitoring/vmagent/scrape.yml`、`backend/services/monitoring_compiler.py`：给本地采集器增加 60 秒硬件 scrape job；远端采集器不接收控制面 target。
- `monitoring/grafana/generate_dashboards.py`、`monitoring/grafana/dashboards/nexora-network-device.json`：改为规范指标、真实 CPU 窗口、单 asset 过滤、sensor info 关联和逐部件明细。
- `src/pages/GrafanaDashboardPage.tsx`、`src/components/DeviceDetailModal.tsx`：设备 asset_id 深链与设备详情跳转。

## 关键语义修正

按 [RFC 3433 ENTITY-SENSOR-MIB](https://www.ietf.org/rfc/rfc3433.txt.pdf) 修正通用传感器解释：`sensorType=9` 表示相对湿度，不能按温度或华氏度换算；scale 枚举是 yocto(1) 到 yotta(17)；固定点实际值依 scale 指数减去 precision 小数位计算。因此 units(9)、precision=1、value=425 得到 42.5。非 `ok(1)` 状态的样本不会被当作当前有效值，未知类型报告为部分/不支持。

## 跨厂商规则核查

只读解析了本机 LibreNMS checkout 在 commit `9831e4e438e438f17445000c872817eb72511b1e` 中的 695 份 OS discovery YAML。512 个 OS 定义硬件规则，合计 6,908 个 processor、mempool 和 sensor 条目。盘点发现 84 个此前未实现的字符串/正则/`exists` 运算符实例；另有 10 个 `device:` 条件、62 个 `user_func` 定义以及 209 个 `entPhysicalIndex_measured` 定义。现在 `device: hardware` 和 `device: version` 会分别映射到发现身份的型号和软件版本；已审查的 user_func 有 Python allowlist，其余仍显式 unsupported。通用 LibreNMS 探测保留实体索引，但没有普遍建立 `entPhysicalIndex_measured` 到 IF-MIB 的接口映射。

已实现字符串/正则/`exists` 的安全子集、`oid: index`、显式固定索引 OID，以及 class-level options 与条目级过滤值合并。已知型号/版本字段缺失时，或遇到其它未支持的 `device:` 字段时，会把条件和样本留在不支持状态；未知 `user_func` 使发现和轮询样本变成 `unsupported_mapping`，不会把原始值假装成规范值。规则快照来自 2026-08-13 的本机 Git 对象，不是最新上游同步；实际设备覆盖需结合目标资产和型号固件逐一确认。另生成 [136 个 OS profile 能力矩阵](../../docs/librenms-hardware-profile-capability-matrix.md)，按定义记录 OID 来源类别、user_func、skip operator、状态/阈值和实体/索引字段；矩阵中的静态 poll candidate 不等同于运行采集。

光模块手动查询和平台 `get_transceivers` 现统一调用 `snmp_librenms_optical_service.py`。旧 `collect_optical_snmp()` 及品牌硬编码 adapter 已删除。静态核对了 Huawei VRP `.32/.33` lane 与 `uw_to_dbm`、Juniper DOM/lane/IFOPTICS、Ruijie `.76/.81`/哨兵过滤，以及 ZTE `zxr10.yaml` 不含 transceiver 定义。投影只在发现明确接口映射时写 `ifIndex`，不会把 `entPhysicalIndex` 当作 `ifIndex`。UniFi 的两个 memory OID 引用缺失的 `FROGFOOT-RESOURCES-MIB`，当前报告 unsupported。

## 既有代码检查记录（不代表全厂商验收）

- `test_snmp_hardware_probe_service.py`：标准 CPU 与仅 RAM 内存池、多实例、ENTITY-SENSOR 值换算、状态缺失/异常、未知类型、CPU window、批量轮询。
- `test_snmp_hardware_inventory.py`：sensor identity、重发现幂等、部分覆盖、退役、旧采样顺序、规范 metrics rendering。
- 同一 CPU 索引下的 1m 和 5m inventory 同时持久化、发现合并保留两条、Prometheus exposition 分别导出窗口标签。
- `test_librenms_rule_service.py`：结构化规则解析、身份条件、诊断、通用过滤语义和 options 合并。
- `test_librenms_mib_source_sync.py`：旧 sparse checkout 在安全 fetch 前扩展 OS detection/discovery 路径，并在有 tracked edits 时保留现状。
- `test_grafana_metrics_export.py`：规范硬件值和 capability exposition、地址不外泄、硬件指标与 aggregate `/metrics` 分离。
- `test_monitoring_v1_compiler.py`：硬件 scrape job 只在 local collector 出现，路径与周期正确。
- LibreNMS optical service、运维入口、平台动作、规则、硬件 probe/inventory、Grafana metrics 和 monitoring compiler 聚焦测试：**70 passed**；MIB sparse source refresh 检查：**1 passed**。pytest 使用轻量 database stub，未运行完整后端测试集合。
- `npm run lint` (`tsc --noEmit`) 通过。Python 触及文件编译、12 份 Grafana dashboard JSON 解析、PostgreSQL-only 静态扫描（0 violation）、完整 MIB manifest 与 `git diff --check` 在 push 前复核。
- 子任务已检查生成器编译、12 个 dashboard JSON 可解析、设备 dashboard 变量/查询静态断言，并确认生成器只更新目标设备 dashboard JSON。
- 本次扩展资产厂商范围后未重新运行测试、容器服务或真实设备 SNMP；没有执行 Grafana/VictoriaMetrics 验收。

## 尚待完成

- 在目标 PostgreSQL 上验证 migration、并发发现和回滚行为。
- 实际 scrape `/hardware-metrics` 并确认新时序进入 VictoriaMetrics，浏览器验证 Grafana 12.1.0 的查询、窗口选择、空态、同名资产与大量部件。
- 为尚未移植的 PHP-only OS 类按资产平台继续增加原生适配；具体型号的现场验收不属于本任务停止条件。
- 对原生健康摘要与 Profile 统一公式做同 fixture 对照；本轮保留现有原生告警口径。
- 现场运行时的 SNMP 请求数、P95 和真实时序效果仍未知；这些作为环境可用后的运维观察，不阻止本轮代码适配工作。

真实设备 SNMP、Docker、VictoriaMetrics 与 Grafana 浏览器环境不在本轮验证范围。此前已有的资产/凭据页面工作区改动未纳入此任务。
