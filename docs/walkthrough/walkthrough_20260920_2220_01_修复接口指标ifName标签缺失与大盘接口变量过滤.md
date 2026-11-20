# 修复接口指标 ifName 标签缺失与大盘接口变量过滤走查与验证报告

## 1. 任务背景与完成摘要
用户在 Grafana `04 接口流量与健康` 大盘表格中，对接口 `Et0/0` 点击 `Filter for value`（图 1），Grafana 顶部自动生成了 Ad-hoc Filter：`Filters [ ifName = Et0/0 ]`（图 2/图 3），开启后导致大盘所有面板接口数据瞬间全部消失（No Data）。用户敏锐指出：“我觉得是字段的问题，你审核下代码吧”。

本轮任务彻底完成了端到端的问题溯源与修复：
1. **定位并证实底层字段缺失根因**：实测发现底层 VictoriaMetrics 中 `ifHCInOctets`、`ifHCOutOctets`、`ifOperStatus` 等所有时序数据上，仅有 `ifIndex` 标签，**完全没有 `ifName` 标签**（`ifName` 仅作为单独 metric 存在）。当 Grafana Ad-hoc Filter 强制在指标选择器注入 `ifName="Et0/0"` 时，由于底层无此 label，查询直接返回空集合（Empty Result），导致所有面板全空。
2. **采集端补齐 snmp_exporter 原生 `lookups`**：在 `backend/services/monitoring_oid_catalog.py` 中为 `STANDARD_INTERFACE_METRICS` 核心指标配置 `_INTERFACE_LOOKUPS`，并通过 `backend/services/monitoring_compiler.py` 放宽语法兼容，使 snmp_exporter 在抓取指标时自动依据 `ifIndex` 将 `ifName` 与 `ifDescr` 作为时序标签打入指标自身。
3. **04 大盘增加原生「接口 ($interface)」模板变量**：在 `monitoring/grafana/generate_dashboards.py` 中添加了级联接口查询变量，支持多选与全选（All）。
4. **面板 PromQL 稳健安全过滤**：在 04 大盘全网聚合 Stat 卡片、Top 10 折线图和 Top 20 表格中，统一通过 `(ifName{ifName=~"$interface"} * 0 + 1)` 进行精确过滤，即使面对未刷新打标的历史时序，也能百分之百精准按接口过滤，不再丢失数据。

---

## 2. 实际修改文件清单
1. [monitoring_oid_catalog.py](file:///d:/netops/netsops-main/backend/services/monitoring_oid_catalog.py)
   - `_metric` 函数支持 `lookups` 参数。
   - 定义 `_INTERFACE_LOOKUPS`（包含 `lookup: ifName` 和 `lookup: ifDescr`）。
   - 为 `STANDARD_INTERFACE_METRICS` 中的接口指标全面配置 `lookups=_INTERFACE_LOOKUPS`。
2. [monitoring_compiler.py](file:///d:/netops/netsops-main/backend/services/monitoring_compiler.py)
   - 兼容 snmp_exporter 标准的 `lookup` 键名与 `labelname` 键名校验。
   - 在 `_fallback_exporter_modules` 的 `generic_ifmib_interface_std` 模块中补齐 `lookups` 属性。
3. [generate_dashboards.py](file:///d:/netops/netsops-main/monitoring/grafana/generate_dashboards.py)
   - 增加 `make_interface_variables()`，为 04 大盘提供 `$interface` 变量。
   - 更新 `build_interface_dashboard()`，8 个核心面板全面支持 `$interface` 精准过滤。
   - 提升版本号至 `25` 并重新编译全套 8 个大盘 JSON。
4. [nexora-network-interface.json](file:///d:/netops/netsops-main/monitoring/grafana/dashboards/nexora-network-interface.json) 及其他 7 个大盘 JSON。

---

## 3. 验证命令与结果

### 3.1 监控编译模块与物料契约测试
```bash
.venv\Scripts\pytest backend/tests/monitoring/test_monitoring_v1_compiler.py -v
```
**测试结果**：19 个测试全部 PASSED（100% 通过）。

```bash
.venv\Scripts\pytest backend/tests/monitoring/test_monitoring_v1_deployment_contract.py backend/tests/monitoring/test_collector_artifact_service.py -v
```
**测试结果**：21 个测试全部 PASSED（100% 通过）。

### 3.2 大盘静态契约校验
```bash
python scratch/verify_all_interface_panels.py
```
**测试结果**：
- `$device` 正确查询 `hostname`；
- `$interface` 正确查询 `ifName`；
- 8 个面板均通过 `$interface` 过滤校验；
- 消除脆弱的 `DEV_JOIN`，带宽利用率包含 safe speed division fallback；
- **ALL D04 PANELS PASSED STATIC CONTRACT VALIDATION!**

### 3.3 前端静态检查
```bash
npm run lint
```
**测试结果**：`tsc --noEmit` 退出码 0，无任何类型与代码错误。

---

## 4. 剩余建议
- 建议用户在日常使用 `04 接口流量与健康` 大盘时，直接通过顶部新增的 **「接口 (Interface)」下拉选择器** 进行筛选。下拉框支持全选、单选（如 `Et0/0`）或多选（如 `Et0/0` 和 `Et0/1`），直观且能让所有面板同步响应。
- 平台下一次应用监控采集配置发布后，snmp_exporter 将自动带上 `lookups` 映射，底层新生成的 `ifHCInOctets` 指标将原生带有 `ifName` 标签。
